@echo off
setlocal enabledelayedexpansion

:: =====================================================================
:: dev-stop.bat - kill whatever is currently bound to ports 5000 / 8000
:: =====================================================================

echo Stopping dev servers...

set "ANY=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    if not "%%P"=="" if not "%%P"=="0" (
        echo   killing PID %%P on :8000
        taskkill /F /PID %%P >nul 2>&1
        set "ANY=1"
    )
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    if not "%%P"=="" if not "%%P"=="0" (
        echo   killing PID %%P on :5000
        taskkill /F /PID %%P >nul 2>&1
        set "ANY=1"
    )
)

if "!ANY!"=="0" (
    echo   nothing was running on :5000 or :8000
)

echo Done.
endlocal
exit /b 0
