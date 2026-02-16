@echo off
REM Build script for LocalRSS Reader desktop application

echo ============================================
echo Building LocalRSS Reader Desktop App
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or higher from python.org
    pause
    exit /b 1
)

echo Installing/updating dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements-desktop.txt

echo.
echo Building executable with PyInstaller...
pyinstaller localrss.spec --clean

if errorlevel 0 (
    echo.
    echo ============================================
    echo Build successful!
    echo ============================================
    echo.
    echo The executable is located in: dist\LocalRSS\
    echo Run: dist\LocalRSS\LocalRSS.exe
    echo.
    echo You can copy the entire dist\LocalRSS\ folder to any location.
    echo.
) else (
    echo.
    echo ============================================
    echo Build failed!
    echo ============================================
    echo Please check the error messages above.
    echo.
)

pause
