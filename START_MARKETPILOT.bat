@echo off
setlocal
cd /d "%~dp0"
title MarketPilot Launcher

echo.
echo ========================================
echo           MARKETPILOT BTC 5M
 echo ========================================
echo.

py --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed or the py launcher is unavailable.
  echo Install Python, then run install_windows.bat.
  pause
  exit /b 1
)

py -c "import flask, requests, pandas, numpy, dotenv" >nul 2>&1
if errorlevel 1 (
  echo Required packages are missing. Installing them now...
  py -m pip install --prefer-binary -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Core package installation failed. Send the error above to ChatGPT.
    pause
    exit /b 1
  )
)

echo Starting MarketPilot bot...
start "MarketPilot Bot" cmd /k "cd /d "%~dp0" && py bot.py"

echo Starting MarketPilot website on http://127.0.0.1:8765 ...
start "MarketPilot Website" cmd /k "cd /d "%~dp0" && set PORT=8765 && py webapp.py"

echo Waiting for the website to become ready...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='http://127.0.0.1:8765/health'; $ok=$false; for($i=0;$i -lt 50;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 1; if($r.StatusCode -eq 200){$ok=$true; break} } catch{}; Start-Sleep -Milliseconds 500 }; if($ok){ Start-Process 'http://127.0.0.1:8765'; exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo.
  echo The website did not start.
  echo Look at the "MarketPilot Website" black window and send ChatGPT a screenshot of the error.
  pause
  exit /b 1
)

echo MarketPilot is running.
echo Leave the Bot and Website windows open.
timeout /t 3 /nobreak >nul
exit /b 0
