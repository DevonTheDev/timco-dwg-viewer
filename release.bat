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
echo [1/6] Building...
call build.bat
if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

:: Step 2: Generate manifest
echo.
echo [2/6] Generating manifest...
python build_manifest.py dist\TimcoDWG %VERSION%
if errorlevel 1 (
    echo Manifest generation failed!
    exit /b 1
)

:: Step 3: Build patch zip (compares with previous release)
echo.
echo [3/6] Building patch...
python build_patch.py dist\TimcoDWG %VERSION%
:: Patch may not be created (e.g. first manifest release) — that's OK

:: Step 4: Create full zip
echo.
echo [4/6] Packaging full zip...
cd /d "%~dp0"
if exist "dist\TimcoDWG-v%VERSION%-full.zip" del "dist\TimcoDWG-v%VERSION%-full.zip"
powershell -Command "Compress-Archive -Path 'dist\TimcoDWG\*' -DestinationPath 'dist\TimcoDWG-v%VERSION%-full.zip' -Force"
if errorlevel 1 (
    echo Packaging failed!
    exit /b 1
)

:: Step 5: Create release on the PUBLIC releases repo
echo.
echo [5/6] Publishing release to GitHub...
set ASSETS="dist\TimcoDWG-v%VERSION%-full.zip" "dist\TimcoDWG\manifest.json"
if exist "dist\TimcoDWG-v%VERSION%-patch.zip" (
    set ASSETS=!ASSETS! "dist\TimcoDWG-v%VERSION%-patch.zip"
)
gh release create "v%VERSION%" %ASSETS% --repo DevonTheDev/timco-dwg-releases --title "v%VERSION%" --notes "%NOTES%"
if errorlevel 1 (
    echo GitHub release failed!
    exit /b 1
)

:: Step 6: Commit version bump to source repo
echo.
echo [6/6] Pushing source to private repo...
git add -A
git commit -m "Release v%VERSION%"
git push

echo.
echo ============================================
echo  Released v%VERSION% successfully!
echo  https://github.com/DevonTheDev/timco-dwg-releases/releases/tag/v%VERSION%
echo ============================================
pause
