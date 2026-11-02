param(
    [ValidateSet('lint', 'test', 'smoke', 'all')][string]$Task = 'all',
    [string]$Python = $env:PYTHON,
    [string]$BaseUrl = $env:SMOKE_BASE_URL
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Host '[FAIL] 找不到 python，请用 -Python "C:\path\to\python.exe" 指定' -ForegroundColor Red
        exit 1
    }
    $Python = $cmd.Source
}

if (-not $BaseUrl) { $BaseUrl = 'http://127.0.0.1:8000' }

function Invoke-Ruff {
    & $Python -m ruff check . 2>&1 | Tee-Object -Variable out | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Pytest {
    & $Python -m pytest 2>&1 | Tee-Object -Variable out | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Smoke {
    $env:SMOKE_BASE_URL = $BaseUrl
    & $Python scripts/smoke.py 2>&1 | Tee-Object -Variable out | Out-Host
    return ($LASTEXITCODE -eq 0)
}

$results = @()

if ($Task -in @('lint', 'all')) {
    # 先确认 ruff 可用，否则给出安装命令而不是一堆红字
    $probe = & $Python -c "import ruff" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] 当前解释器没装 ruff：$Python" -ForegroundColor Yellow
        Write-Host "      安装：& `"$Python`" -m pip install -r requirements.txt" -ForegroundColor Yellow
        $results += @('lint', $false)
    } else {
        $results += @('lint', (Invoke-Ruff))
    }
}

if ($Task -in @('test', 'all')) {
    $probe = & $Python -c "import pytest" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] 当前解释器没装 pytest：$Python" -ForegroundColor Yellow
        $results += @('test', $false)
    } else {
        $results += @('test', (Invoke-Pytest))
    }
}

if ($Task -in @('smoke', 'all')) {
    $results += @('smoke', (Invoke-Smoke))
}

Write-Host ''
Write-Host '==================== 汇总 ====================' -ForegroundColor Cyan
$failed = 0
for ($i = 0; $i -lt $results.Count; $i += 2) {
    $name = $results[$i]
    $ok = $results[$i + 1]
    if ($ok) {
        Write-Host "[PASS] $name" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $name" -ForegroundColor Red
        $failed++
    }
}

if ($failed -gt 0) {
    Write-Host "结果：$failed 项未通过" -ForegroundColor Red
    exit 1
}
Write-Host '结果：全绿。把这段输出整段贴进 PR 描述。' -ForegroundColor Green
exit 0
