@echo off
REM ============================================================
REM  MoonScan build script
REM  Double-click this file to produce MoonScan.exe
REM ============================================================

setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo  Building MoonScan.exe
echo ============================================================
echo.

REM --- Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python is not installed or not on your PATH.
    echo.
    echo  1. Go to https://www.python.org/downloads/
    echo  2. Download and install Python 3.10 or newer
    echo  3. IMPORTANT: tick "Add Python to PATH" on the first install screen
    echo  4. Run this build.bat again
    echo.
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM --- Install dependencies ---
echo Installing dependencies (one-time, may take a minute)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install dependencies. Check your internet connection.
    echo.
    pause
    exit /b 1
)

REM --- Clean previous build ---
if exist build rmdir /s /q build >nul 2>&1
if exist dist rmdir /s /q dist >nul 2>&1

REM --- Build ---
echo.
echo Building executable... (1 to 3 minutes, please wait)
echo.
python -m PyInstaller moonscan.spec --noconfirm
if errorlevel 1 (
    echo.
    echo  BUILD FAILED. See the error messages above.
    echo.
    pause
    exit /b 1
)

REM --- Verify ---
if not exist "dist\MoonScan.exe" (
    echo.
    echo  BUILD FAILED - MoonScan.exe was not produced.
    echo.
    pause
    exit /b 1
)

REM --- Done ---
echo.
echo ============================================================
echo  DONE
echo ============================================================
echo.
echo  Your file:  dist\MoonScan.exe
echo.
echo  HOW TO SHARE WITH YOUR ALLIANCE:
echo.
echo    1. Open the "dist" folder (it's right next to this script)
echo    2. Upload MoonScan.exe to Google Drive, OneDrive, or Dropbox
echo       (Discord won't work, the file is too big for most servers)
echo    3. Get a shareable link from your upload
echo    4. Post the link in your alliance Discord
echo.
echo  TELL ALLIANCE MATES:
echo    - Download MoonScan.exe
echo    - Double-click to run
echo    - Windows will say "Windows protected your PC" the first time -
echo      click "More info" then "Run anyway". This is normal for any
echo      app that isn't signed by a paid certificate.
echo    - First launch shows the setup wizard - pick Geminate then
echo      KR-XF4 then leave all systems checked, then Finish.
echo.
pause
endlocal
