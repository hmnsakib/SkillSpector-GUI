@echo off
REM Builds SkillSpectorScanner.exe  (run on a Windows PC with Python 3.12+ installed)
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Python was not found on this computer.
  echo 1. Download Python 3.12 or newer from https://www.python.org/downloads/windows/
  echo 2. In the installer, tick "Add python.exe to PATH" and keep "tcl/tk and IDLE" ticked.
  echo 3. Close this window and run build.bat again.
  echo.
  echo If you installed it from the Microsoft Store and it still fails, open Settings
  echo ^> Apps ^> Advanced app settings ^> App execution aliases and turn ON the python alias.
  pause
  exit /b 1
)

%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo Python was found but it has no Tkinter. Reinstall Python and keep "tcl/tk and IDLE" ticked.
  pause
  exit /b 1
)

echo Using: %PY%
%PY% -m pip install --upgrade pyinstaller || goto :err
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile --name SkillSpectorScanner skillspector_gui.py || goto :err
echo.
echo Done. Your app is: dist\SkillSpectorScanner.exe
echo (Tip: if antivirus flags the one-file build, change --onefile to --onedir and share the whole dist folder.)
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
