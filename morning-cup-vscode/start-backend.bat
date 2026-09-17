@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".python-path" (
  echo Run install.bat on THIS computer first.
  pause
  exit /b 1
)
set /p MORNING_PYTHON=<".python-path"
if not exist "%MORNING_PYTHON%" (
  echo Python environment not found. Run install.bat again.
  pause
  exit /b 1
)
set MORNING_LIVE_SERVER=1
echo Open index.html with VS Code Live Server on port 5500.
echo Keep this window open. Backend: http://127.0.0.1:8765
"%MORNING_PYTHON%" app.py
pause
