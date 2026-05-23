@echo off
setlocal

:: =====================================================================
:: dev-stop.bat  v3
::
:: Thin wrapper around scripts\dev-cleanup.ps1 which does the heavy
:: lifting (kills full process trees including reloader children, scoped
:: to this repository).
:: =====================================================================

cd /d "%~dp0"
echo Stopping dev servers...

:: Resolve PowerShell - on some minimal cmd PATHs powershell.exe is not
:: in PATH so fall back to its hard-coded location.
set "PS_EXE=powershell.exe"
where powershell.exe >nul 2>&1
if errorlevel 1 set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-cleanup.ps1" -ProjectDir "%~dp0."

echo Done.
endlocal
exit /b 0
