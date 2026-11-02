param(
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$Open,
    [string]$Python = $env:PYTHON
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-Interpreter([string]$exe) {
    if (-not $exe) { return $false }
    if (-not (Test-Path $exe)) { return $false }
    $null = & $exe -c "import fastapi, uvicorn" 2>&1
    return ($LASTEXITCODE -eq 0)
}

$cmd = Get-Command python -ErrorAction SilentlyContinue

$candidates = @()
if ($Python) { $candidates += $Python }
$candidates += (Join-Path $root '.venv\Scripts\python.exe')
$candidates += 'C:\Users\Lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
if ($cmd) { $candidates += $cmd.Source }

$chosen = $null
foreach ($candidate in $candidates) {
    if (Test-Interpreter $candidate) { $chosen = $candidate; break }
}

if (-not $chosen) {
    Write-Host ''
    Write-Host '================================================' -ForegroundColor Red
    Write-Host ' 没找到装好依赖的 Python，服务无法启动' -ForegroundColor Red
    Write-Host '================================================' -ForegroundColor Red
    Write-Host ''
    Write-Host "你 PATH 里的 python 是：$(if ($cmd) { $cmd.Source } else { '(没有)' })"
    Write-Host '它里面没有 fastapi / uvicorn —— 这就是"网页打不开"最常见的原因。'
    Write-Host ''
    Write-Host '解决办法（二选一）：' -ForegroundColor Yellow
    Write-Host '  1) 先装依赖：  python -m pip install -r requirements.txt'
    Write-Host '  2) 指定一个装好的解释器：'
    Write-Host '     .\scripts\start.ps1 -Python "C:\Python311\python.exe"'
    Write-Host ''
    exit 1
}

$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "[提示] 端口 $Port 已被占用。换一个端口：" -ForegroundColor Yellow
    Write-Host "     .\scripts\start.ps1 -Port 8010"
    exit 1
}

$url = "http://127.0.0.1:$Port"
Write-Host "解释器：$chosen"
Write-Host ''
Write-Host "  演示页   $url" -ForegroundColor Green
Write-Host "  接口文档 $url/docs" -ForegroundColor Green
Write-Host "  健康检查 $url/health" -ForegroundColor Green
Write-Host ''
Write-Host '按 Ctrl+C 停止服务。' -ForegroundColor DarkGray

if ($Open) {
    $null = Start-Process -FilePath 'powershell' -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoProfile', '-Command', "Start-Sleep -Seconds 3; Start-Process '$url'"
    )
}

$uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")
if ($Reload) { $uvicornArgs += '--reload' }

& $chosen @uvicornArgs
