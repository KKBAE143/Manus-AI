@echo off
setlocal enabledelayedexpansion

:: =====================================================================
:: dev.bat  v3  (no-wait launcher)
::
:: Kills anything still listening on 8000 (backend) or 5000 (frontend),
:: then immediately opens two new terminal windows: one for FastAPI,
:: one for Vite. Re-runs cleanly any number of times.
:: =====================================================================

cd /d "%~dp0"
echo.
echo ===============================================
echo   Manuscript / Quiz Cleaner - dev launcher v3
echo ===============================================
echo.

:: --- 1. Verify backend venv exists -----------------------------------
if not exist "backend\venv\Scripts\python.exe" (
    echo [ERROR] Python venv not found at backend\venv\Scripts\python.exe
    echo         Create it with:
    echo             cd backend
    echo             python -m venv venv
    echo             venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: --- 2. Free port 8000 (backend) -------------------------------------
echo [1/3] Freeing port 8000 (backend)...
set "KILLED_8000=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    if not "%%P"=="" if not "%%P"=="0" (
        echo       killing PID %%P on :8000
        taskkill /F /PID %%P >nul 2>&1
        set "KILLED_8000=1"
    )
)
if "!KILLED_8000!"=="0" echo       nothing was listening on :8000

:: --- 3. Free port 5000 (frontend) ------------------------------------
echo [2/3] Freeing port 5000 (frontend)...
set "KILLED_5000=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    if not "%%P"=="" if not "%%P"=="0" (
        echo       killing PID %%P on :5000
        taskkill /F /PID %%P >nul 2>&1
        set "KILLED_5000=1"
    )
)
if "!KILLED_5000!"=="0" echo       nothing was listening on :5000

:: --- 4. Start backend + frontend in their own windows ----------------
:: Both start at the same time. The backend boots in ~1s; the frontend
:: page automatically retries the backend until it is ready.
::
:: Each window uses cmd /k so it stays open even if the server crashes,
:: so you can read the error. Close the window manually to stop.
echo [3/3] Launching backend and frontend windows...

start "Manuscript-API (port 8000)" cmd /k "cd /d %~dp0backend && set PYTHONPATH=.. && venv\Scripts\python.exe -m uvicorn app.main:app --host localhost --port 8000 --reload --reload-dir app || echo. & echo [API EXITED] press any key to close. & pause >nul"

start "Manuscript-Web (port 5000)" cmd /k "cd /d %~dp0 && npm run dev || echo. & echo [WEB EXITED] press any key to close. & pause >nul"

echo.
echo ===============================================
echo   Two new windows opened:
echo     - Manuscript-API   http://localhost:8000
echo     - Manuscript-Web   http://localhost:5000
echo.
echo   Quiz Cleaner page:   http://localhost:5000/quiz-cleaner
echo.
echo   Backend usually ready within 1-2 seconds.
echo   The page auto-refreshes when the backend comes up.
echo.
echo   To stop everything: run dev-stop.bat
echo ===============================================
echo.
endlocal
exit /b 0
