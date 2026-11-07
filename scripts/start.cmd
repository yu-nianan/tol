@echo off
rem ------------------------------------------------------------------
rem Start the demo server. Double-click friendly.
rem Why this wrapper exists: on machines where PowerShell policy forbids
rem unsigned scripts, running scripts\start.ps1 directly fails with
rem "not digitally signed". cmd + -ExecutionPolicy Bypass avoids it
rem without changing any system setting.
rem Usage: scripts\start.cmd              (default port 8000)
rem        scripts\start.cmd -Port 8010
rem        scripts\start.cmd -Open
rem Keep this file ASCII-only: cmd.exe reads .cmd as ANSI/GBK, and
rem non-ASCII bytes can corrupt the parser.
rem ------------------------------------------------------------------
chcp 65001 >nul
setlocal
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "CODE=%ERRORLEVEL%"

rem Double-clicked (no args) and failed: keep the window open so the
rem error stays readable. Ctrl+C exit code is not treated as failure.
if "%~1"=="" if not "%CODE%"=="0" if not "%CODE%"=="3221225786" (
    echo.
    echo [start.cmd] failed with exit code %CODE%. See README section "web page will not open".
    pause
)
exit /b %CODE%
