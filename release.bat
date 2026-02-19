@echo off
setlocal enabledelayedexpansion

:: Release script for Timco DWG Viewer
:: Usage: release.bat <version> [release notes]
:: Example: release.bat 1.1.0 "Fixed layer export bug"

if "%~1"=="" (
    echo Usage: release.bat ^<version^> [release notes]
    echo Example: release.bat 1.1.0 "Fixed layer export bug"
    exit /b 1
)

set VERSION=%~1
set NOTES=%~2
if "%NOTES%"=="" set NOTES=Release v%VERSION%

echo ============================================
echo  Timco DWG Viewer - Release v%VERSION%
echo ============================================
echo.

:: Step 1: Build
echo [1/4] Building...
call build.bat
if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

:: Step 2: Create zip for distribution
echo.
echo [2/4] Packaging dist\TimcoDWG into zip...
cd /d "%~dp0"
if exist "dist\TimcoDWG-v%VERSION%-windows.zip" del "dist\TimcoDWG-v%VERSION%-windows.zip"
powershell -Command "Compress-Archive -Path 'dist\TimcoDWG\*' -DestinationPath 'dist\TimcoDWG-v%VERSION%-windows.zip' -Force"
if errorlevel 1 (
    echo Packaging failed!
    exit /b 1
)

:: Step 3: Create release on the PUBLIC releases repo
echo.
echo [3/4] Publishing release to GitHub...
gh release create "v%VERSION%" "dist\TimcoDWG-v%VERSION%-windows.zip" --repo DevonTheDev/timco-dwg-releases --title "v%VERSION%" --notes "%NOTES%"
if errorlevel 1 (
    echo GitHub release failed!
    exit /b 1
)

:: Step 4: Commit version bump to source repo
echo.
echo [4/4] Pushing source to private repo...
git add -A
git commit -m "Release v%VERSION%"
git push

echo.
echo ============================================
echo  Released v%VERSION% successfully!
echo  https://github.com/DevonTheDev/timco-dwg-releases/releases/tag/v%VERSION%
echo ============================================
pause
