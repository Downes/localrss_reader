@echo off
setlocal EnableExtensions
cd /d %~dp0

REM ===== Configuration =====
REM Default DB location (edit if you prefer)
set "RSS_DB=E:\localRSS\rss.db"

REM Log file for troubleshooting
set "LOGFILE=%~dp0localrss_run.log"

echo === LocalRSSReader startup === > "%LOGFILE%"
echo Folder: %~dp0 >> "%LOGFILE%"
echo RSS_DB=%RSS_DB% >> "%LOGFILE%"
echo Time: %DATE% %TIME% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Using DB: %RSS_DB%
if not exist "%RSS_DB%" (
  echo WARNING: DB file not found at "%RSS_DB%"
  echo WARNING: DB file not found at "%RSS_DB%" >> "%LOGFILE%"
)

REM Create venv if missing
if not exist "venv\Scripts\python.exe" (
  echo Creating venv...
  echo Creating venv... >> "%LOGFILE%"
  py -3 -m venv venv >> "%LOGFILE%" 2>&1
  if errorlevel 1 (
    python -m venv venv >> "%LOGFILE%" 2>&1
  )
  if errorlevel 1 (
    echo ERROR: Could not create venv. See %LOGFILE%
    echo ERROR: Could not create venv. >> "%LOGFILE%"
    pause
    exit /b 1
  )
)

REM Install deps
echo Installing/updating requirements...
echo Installing/updating requirements... >> "%LOGFILE%"
venv\Scripts\python.exe -m pip install -r requirements.txt >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo ERROR: pip install failed. See %LOGFILE%
  echo ERROR: pip install failed. >> "%LOGFILE%"
  pause
  exit /b 1
)

REM Open the UI once
start "" http://127.0.0.1:8787

REM Run the server (keep this window open; if it crashes, show log)
echo Starting server...
echo Starting server... >> "%LOGFILE%"
venv\Scripts\python.exe app.py >> "%LOGFILE%" 2>&1

echo.
echo === Server exited or crashed ===
echo See log: %LOGFILE%
pause
