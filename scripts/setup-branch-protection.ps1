# setup-branch-protection.ps1 —— 一次性把 main 的分支保护配成"CI 说了算"
#
# 方案 A：Required approvals = 0（自己不能批自己，所以不要求人批）
#         Required status checks = check + docs（CI 变红就不许合）
#         禁止强推、禁止删除分支
#
# 用法（任选其一）：
#   1) 交互式，token 不进命令历史：
#        .\scripts\setup-branch-protection.ps1
#   2) 先设环境变量（只在本进程有效）：
#        $env:GITHUB_TOKEN = "github_pat_xxx"; .\scripts\setup-branch-protection.ps1
#   3) 只预览不改：
#        .\scripts\setup-branch-protection.ps1 -DryRun
#
# Token 需要：仓库的 Admin 权限（classic PAT 勾 repo；fine-grained 给 Administration: Read and write）

[CmdletBinding()]
param(
    [string]$Token = $env:GITHUB_TOKEN,
    [string]$Repo = "yu-nianan/tol",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Api = "https://api.github.com"
$Checks = @("check", "docs")   # 与 .github/workflows/{ci,docs}.yml 的 job 名一致

function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color }

# ---------- 预览模式：不需要 token ----------
$RulesetPreview = @{
    name        = "main-protection-ci"
    target      = "branch"
    enforcement = "active"
    conditions  = @{ ref_name = @{ include = @("~DEFAULT_BRANCH"); exclude = @() } }
    rules       = @(
        @{ type = "deletion" }
        @{ type = "non_fast_forward" }
        @{
            type       = "pull_request"
            parameters = @{
                required_approving_review_count   = 0
                dismiss_stale_reviews_on_push     = $true
                require_code_owner_review         = $false
                require_last_push_approval        = $false
                required_review_thread_resolution = $false
            }
        }
        @{
            type       = "required_status_checks"
            parameters = @{
                strict_required_status_checks_policy = $true
                required_status_checks               = @($Checks | ForEach-Object { @{ context = $_ } })
            }
        }
    )
}

if ($DryRun) {
    Say "（DryRun）不连 GitHub，只展示将要写入的 ruleset：" "Cyan"
    $RulesetPreview | ConvertTo-Json -Depth 10
    exit 0
}

if (-not $Token) {
    Say "没有拿到 token。请先创建一个 Personal Access Token：" "Yellow"
    Say "  GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)"
    Say "  勾选 repo（含 admin 权限）→ 生成后复制"
    Say ""
    Say "然后在本机执行（token 不会出现在命令历史里）：" "Yellow"
    Say '  $t = Read-Host -AsSecureString "粘贴 token"; $env:GITHUB_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($t))'
    Say '  .\scripts\setup-branch-protection.ps1'
    exit 2
}

$Headers = @{
    Authorization          = "Bearer $Token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "setup-branch-protection"
}

function CallApi {
    param([string]$Method, [string]$Path, $Body)
    $uri = if ($Path -like "http*") { $Path } else { "$Api$Path" }
    $p = @{ Method = $Method; Headers = $Headers; ErrorAction = "Stop" }
    if ($Body) {
        $p.Body = ($Body | ConvertTo-Json -Depth 10)
        $p.ContentType = "application/json; charset=utf-8"
    }
    try {
        Invoke-RestMethod @p -Uri $uri
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        $detail = ""
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $detail = $reader.ReadToEnd()
        } catch { }
        [pscustomobject]@{ Ok = $false; Code = $code; Detail = $detail; Response = $null }
    }
}

# ---------- 0. 权限自检 ----------
Say "· 检查仓库 $Repo ..."
$repoInfo = CallApi GET "/repos/$Repo"
if ($null -eq $repoInfo.Response) {
    $repoInfo = CallApi GET "/repos/$Repo"   # 失败时返回 pscustomobject
}
if ($repoInfo -is [pscustomobject] -and $repoInfo.PSObject.Properties.Name -contains "Ok" -and -not $repoInfo.Ok) {
    Say "拉取仓库信息失败：HTTP $($repoInfo.Code)" "Red"
    Say $repoInfo.Detail "DarkGray"
    exit 1
}

Say ("  默认分支：{0}    私有：{1}    admin：{2}" -f $repoInfo.default_branch, $repoInfo.private, $repoInfo.permissions.admin)

if (-not $repoInfo.permissions.admin) {
    Say "这个 token 没有 admin 权限，改不了分支保护。换一个 token 或用网页操作。" "Red"
    exit 1
}

$Branch = $repoInfo.default_branch
$Exists = CallApi GET "/repos/$Repo/branches/$Branch/protection"
if ($null -eq $Exists.Response) { $Exists = CallApi GET "/repos/$Repo/branches/$Branch/protection" }
$Protected = $true
if ($Exists -is [pscustomobject] -and $Exists.PSObject.Properties.Name -contains "Ok" -and -not $Exists.Ok) {
    $Protected = $false
    Say "  $Branch 当前没有 classic 分支保护（可能是没有，或只用了 ruleset）"
} else {
    Say "  $Branch 当前已有 classic 保护，将被覆盖为统一配置"
}

# ---------- 1. 要写入的配置 ----------
# 1a) 与预览用同一份 ruleset 定义（改上面那处即可）
$Ruleset = $RulesetPreview

# 1b) 老版 classic 保护（rulesets 建不了时的退路）
$Classic = @{
    required_status_checks        = @{ strict = $true; contexts = $Checks }
    enforce_admins                = $false
    required_pull_request_reviews = @{ required_approving_review_count = 0; dismiss_stale_reviews = $true }
    restrictions                  = $null
    allow_force_pushes            = $false
    allow_deletions               = $false
}

# ---------- 2. 先试 rulesets ----------
Say ""
Say "· 尝试创建 ruleset（推荐方式）..."
$existing = CallApi GET "/repos/$Repo/rulesets"
if ($null -eq $existing.Response) { $existing = CallApi GET "/repos/$Repo/rulesets" }

$created = $null
if ($existing -is [array]) {
    $mine = $existing | Where-Object { $_.name -eq $Ruleset.name }
    if ($mine) {
        Say "  已存在同名 ruleset（id=$($mine.id)），改为更新"
        $created = CallApi PUT "/repos/$Repo/rulesets/$($mine.id)" $Ruleset
    }
}
if (-not $created) {
    $created = CallApi POST "/repos/$Repo/rulesets" $Ruleset
}

if ($created -is [pscustomobject] -and $created.PSObject.Properties.Name -contains "id" -and $created.id) {
    Say "  ✅ ruleset 已生效：id=$($created.id)，必需检查 = $($Checks -join ' / ')，审批数 = 0" "Green"
    exit 0
}

Say "  ✗ ruleset 创建失败：HTTP $($created.Code)" "Yellow"
if ($created.Detail) { Say ("    " + ($created.Detail -replace "\s+", " ").Substring(0, [Math]::Min(300, ($created.Detail -replace "\s+", " ").Length))) "DarkGray" }
Say "  改用 classic 分支保护..."

# ---------- 3. 退路：classic 保护 ----------
$classicResult = CallApi PUT "/repos/$Repo/branches/$Branch/protection" $Classic
if ($null -eq $classicResult.Response) { $classicResult = CallApi PUT "/repos/$Repo/branches/$Branch/protection" $Classic }

if ($classicResult -is [pscustomobject] -and $classicResult.PSObject.Properties.Name -contains "url") {
    Say "  ✅ classic 分支保护已生效（$Branch）" "Green"
    exit 0
}

Say "  ✗ classic 也失败：HTTP $($classicResult.Code)" "Red"
if ($classicResult.Detail) { Say ("    " + ($classicResult.Detail -replace "\s+", " ")) "DarkGray" }
Say ""
Say "常见原因：" "Yellow"
Say "  · 免费私有仓库不支持分支保护 → 升 Pro，或把仓库设为 public（注意比赛匿名风险）"
Say "  · token 没有 admin 权限 → 重新生成，勾 repo（classic）"
Say "  · 组织策略禁止 → 换成网页操作：Settings → Rules → Rulesets"
exit 1
