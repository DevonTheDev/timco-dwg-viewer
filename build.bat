@echo off
echo Building Timco DWG Viewer...
echo.

cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
)

echo Running PyInstaller...
venv\Scripts\pyinstaller pyinstaller.spec --noconfirm

echo.
echo Build complete! Output: dist\TimcoDWG\
echo Copy the entire TimcoDWG folder to distribute.
pause
