@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ===================================================
echo   Image to PDF (no-paper) - EXE build
echo ===================================================
echo.

echo [1/5] Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found.
    echo Install Python from https://www.python.org/downloads/
    echo During install, make sure to check "Add python.exe to PATH".
    echo Then run this file again.
    echo.
    pause
    exit /b 1
)
python --version

echo.
echo [2/5] Preparing virtual environment (venv folder)...
if not exist venv (
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo.
echo [3/5] Installing required packages... (needs internet, may take a few minutes)
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install packages from requirements.txt.
    pause
    exit /b 1
)
pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install pyinstaller.
    pause
    exit /b 1
)

echo.
echo [4/5] Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist meltPDF.spec del /q meltPDF.spec

echo.
echo [5/5] Building EXE... (this can take a few minutes)
pyinstaller --noconfirm --onefile --windowed --name "meltPDF" --collect-all tkinterdnd2 --collect-all fitz --collect-all pymupdf --collect-all PIL --collect-all pikepdf --collect-all img2pdf main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the log above.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo   Done! Check dist\meltPDF.exe
echo ===================================================
echo.
if exist dist\meltPDF.exe (
    explorer.exe /select,"dist\meltPDF.exe"
)
pause
