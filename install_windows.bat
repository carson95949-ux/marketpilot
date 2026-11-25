@echo off
setlocal
cd /d "%~dp0"
echo.
echo ========================================
echo       MarketPilot - installing packages
echo ========================================
echo.
py --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python launcher ^(py^) was not found.
  echo Install Python from python.org and enable Add Python to PATH.
  pause
  exit /b 1
)
py -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :fail
py -m pip install --prefer-binary -r requirements.txt
if errorlevel 1 goto :fail
echo.
echo SUCCESS: MarketPilot is installed.
echo The Polymarket account connector no longer needs a separate crypto package install.
pause
exit /b 0
:fail
echo.
echo INSTALL FAILED. Copy the last 20 lines above and send them to ChatGPT.
pause
exit /b 1
