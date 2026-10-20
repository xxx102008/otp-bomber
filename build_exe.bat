@echo off
chcp 65001 >nul
title Build bomber.exe
color 0A

echo ==========================================
echo    Building bomber.exe
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python not found.
    echo     Download from python.org/downloads
    echo     and CHECK "Add python.exe to PATH"
    echo.
    pause
    exit /b
)

echo [1/4] Upgrading pip...
python -m pip install --upgrade pip >nul 2>nul

echo [2/4] Installing requests + pyinstaller...
python -m pip install requests pyinstaller
if errorlevel 1 (
    echo.
    echo [X] Install failed. Check your internet.
    pause
    exit /b
)

echo.
echo [3/4] Building... this takes 1-3 minutes
python -m PyInstaller --onefile --name bomber --clean --noconfirm bomber.py
if errorlevel 1 (
    echo.
    echo [X] Build failed.
    pause
    exit /b
)

echo.
echo [4/4] Moving bomber.exe next to this file...
if exist dist\bomber.exe move /y dist\bomber.exe .\bomber.exe >nul

echo.
echo ==========================================
echo    DONE!  bomber.exe is in this folder
echo ==========================================
echo.
pause
