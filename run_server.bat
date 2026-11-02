@echo off
setlocal
cd /d "%~dp0"
title HD2 Stratagem LAN Server

echo.
echo ============================================================
echo   HELLDIVERS 2 - STRATAGEM LAN SERVER
echo ============================================================
echo.

if not exist "app.py" (
    echo ERROR: app.py was not found.
    echo Extract the complete ZIP archive before launching this file.
    pause
    exit /b 1
)

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.14 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.14"
    if not defined PY_CMD (
        py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3.13"
    )
    if not defined PY_CMD (
        py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3.12"
    )
    if not defined PY_CMD (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3"
    )
)
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo ERROR: Python 3.12 or newer was not found.
    echo Install Python from https://www.python.org/downloads/windows/
    echo During installation, enable "Add Python to PATH".
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Existing virtual environment uses Python older than 3.12. Recreating it...
        rmdir /s /q .venv
        if errorlevel 1 (
            echo ERROR: Could not replace the outdated virtual environment.
            pause
            exit /b 1
        )
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creating Python virtual environment...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo [2/2] Checking required packages...
.venv\Scripts\python.exe -c "from importlib.metadata import version; from pip._vendor.packaging.version import Version as V; assert V(version('fastapi')) >= V('0.115.0') and V(version('fastapi')) < V('1.0') and V(version('uvicorn')) >= V('0.34.0') and V(version('uvicorn')) < V('1.0') and V(version('pydantic')) >= V('2.8.0') and V(version('pydantic')) < V('3.0'); import websockets, watchfiles, httptools, yaml, dotenv" >nul 2>&1
if errorlevel 1 (
    echo Required packages are missing or outdated. Installing them...
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Could not install Python packages.
        echo Check your internet connection and try again.
        pause
        exit /b 1
    )
) else (
    echo Required packages are already installed. Skipping pip.
)

echo.
echo Starting server. Keep this window open while playing.
echo.
.venv\Scripts\python.exe app.py
set "SERVER_EXIT=%ERRORLEVEL%"

echo.
echo Server process has stopped. Exit code: %SERVER_EXIT%
echo If an error appeared above, take a screenshot of this window.
pause
exit /b %SERVER_EXIT%
