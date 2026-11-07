@echo off
rem ------------------------------------------------------------------
rem Run the gate commands. Double-click friendly (pauses at the end).
rem Why this wrapper exists: on machines where PowerShell policy forbids
rem unsigned scripts, running scripts\check.ps1 directly fails with
rem "not digitally signed". cmd + -ExecutionPolicy Bypass avoids it
rem without changing any system setting.
rem Usage: scripts\check.cmd              (same as -Task all)
rem        scripts\check.cmd -Task lint
rem        scripts\check.cmd -Task test
rem        scripts\check.cmd -Task smoke
rem Keep this file ASCII-only: cmd.exe reads .cmd as ANSI/GBK, and
rem non-ASCII bytes can corrupt the parser.
rem ------------------------------------------------------------------
chcp 65001 >nul
setlocal
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

set "PASSARGS=%*"
if "%PASSARGS%"=="" set "PASSARGS=-Task all"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0check.ps1" %PASSARGS%
set "CODE=%ERRORLEVEL%"

rem No arguments = probably double-clicked: pause so output stays visible.
if "%~1"=="" pause
exit /b %CODE%
