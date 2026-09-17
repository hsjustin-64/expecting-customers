@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
for %%V in (3.12 3.11 3.10) do (
  py -%%V -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>&1
  if not errorlevel 1 (
    py -%%V install.py
    goto done
  )
)
python install.py
:done
if errorlevel 1 (
  echo Installation failed. See the error above. Windows x64, Python 3.10-3.12 and internet are required.
  pause
  exit /b 1
)
echo Ready. Open this folder in VS Code, press F5, then open index.html with Live Server.
pause
