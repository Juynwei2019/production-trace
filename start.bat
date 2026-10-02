@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.14"
if defined PYTHON_CMD goto python_found
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.13"
if defined PYTHON_CMD goto python_found
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.12"
if defined PYTHON_CMD goto python_found
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.11"
if defined PYTHON_CMD goto python_found
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

:python_found

if not defined PYTHON_CMD (
  echo [ERROR] Python 3.10 or newer was not found.
  echo Please install Python from https://www.python.org/downloads/
  pause
  exit /b 1
)

echo Using:
%PYTHON_CMD% --version

if exist ".venv" if not exist ".venv\Scripts\python.exe" (
  echo Removing incomplete virtual environment...
  rmdir /s /q ".venv"
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  echo Please check the network connection and the messages above.
  pause
  exit /b 1
)

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
