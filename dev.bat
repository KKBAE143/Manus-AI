@echo off
setlocal enabledelayedexpansion

:: =====================================================================
:: dev.bat  v4  (aggressive cleanup launcher)
::
:: 1) Calls dev-stop.bat which kills the entire process tree of any
::    leftover uvicorn / vite / cmd window owning our dev servers,
::    plus orphaned multiprocessing-spawn workers scoped to this repo.
:: 2) Opens two fresh terminal windows for backend and frontend.
::
:: Re-runs cleanly any number of times - no zombies.
:: =====================================================================

cd /d "%~dp0"
echo.
echo ===============================================
echo   Manuscript / Quiz Cleaner - dev launcher v4
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

:: --- 2. Aggressive cleanup of any previous run -----------------------
echo [1/2] Cleaning up any previous dev processes...
call dev-stop.bat

:: Brief grace period so Windows fully releases the sockets and the
:: file handles uvicorn / vite were holding.
timeout /t 1 /nobreak >nul

:: --- 3. Start backend + frontend in their own windows ----------------
echo.
echo [2/2] Launching backend and frontend windows...

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
