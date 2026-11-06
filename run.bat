@echo off
chcp 65001 >nul
title Slide to Markdown (close this window to stop)
cd /d "%~dp0"

set "VENV=%~dp0.venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo Creating virtual environment: %VENV%
  where py >nul 2>nul && (py -3 -m venv "%VENV%") || (python -m venv "%VENV%")
  if not exist "%VENV%\Scripts\python.exe" (
    echo [ERROR] Python 3.10+ is required. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
  )
)
set "PY=%VENV%\Scripts\python.exe"

"%PY%" -c "import fastapi, uvicorn, multipart, pymupdf, pptx, PIL" 2>nul || (
  echo Installing packages from requirements.txt ...
  "%PY%" -m pip install --upgrade pip >nul
  "%PY%" -m pip install -r requirements.txt || (pause & exit /b 1)
)

rem The server listens on 127.0.0.1 only and opens http://127.0.0.1:8766 in the browser when ready.
rem Use another port:  set SLIDE2MD_PORT=8800  before running this file.
"%PY%" -m slide2md.server %*
if errorlevel 1 pause
