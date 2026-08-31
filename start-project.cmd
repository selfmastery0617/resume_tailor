@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "FRONTEND_DIR=%PROJECT_ROOT%frontend"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"

echo.
echo Resume Tailor development launcher
echo ==================================

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python virtual environment was not found:
    echo   %PYTHON_EXE%
    echo Create the virtual environment and install backend requirements first.
    goto :failed
)

where.exe npm.cmd >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm.cmd was not found on PATH. Install Node.js first.
    goto :failed
)

if not exist "%FRONTEND_DIR%\node_modules\" (
    echo ERROR: Frontend dependencies are not installed.
    echo Run: cd /d "%FRONTEND_DIR%" ^&^& npm.cmd install
    goto :failed
)

call :check_port 8000 Backend
if errorlevel 1 goto :failed

call :check_port 5173 Frontend
if errorlevel 1 goto :failed

if /I "%~1"=="--check" (
    echo Preflight checks passed. Ports 8000 and 5173 are free.
    exit /b 0
)

echo [1/3] Applying pending database migrations...
pushd "%BACKEND_DIR%"
"%PYTHON_EXE%" -m alembic upgrade head
set "MIGRATION_EXIT=%ERRORLEVEL%"
popd
if not "%MIGRATION_EXIT%"=="0" (
    echo ERROR: Database migration failed. Servers were not started.
    goto :failed
)

echo [2/3] Starting backend at http://127.0.0.1:8000 ...
start "Resume Tailor Backend" /D "%BACKEND_DIR%" "%ComSpec%" /k "..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo [3/3] Starting frontend at http://localhost:5173 ...
start "Resume Tailor Frontend" /D "%FRONTEND_DIR%" "%ComSpec%" /k "set VITE_BACKEND_URL=http://127.0.0.1:8000&& npm.cmd run dev"

echo.
echo Started backend and frontend in separate terminal windows.
echo Close those windows or press Ctrl+C in each one to stop the project.
exit /b 0

:check_port
netstat -ano | findstr.exe /R /C:":%~1 .*LISTENING" >nul
if not errorlevel 1 (
    echo ERROR: %~2 port %~1 is already in use.
    echo Close the existing server before running this launcher again:
    netstat -ano | findstr.exe /R /C:":%~1 .*LISTENING"
    exit /b 1
)
exit /b 0

:failed
echo.
echo Project startup stopped.
pause
exit /b 1
