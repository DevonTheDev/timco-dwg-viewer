@echo off
:: Timco DWG Viewer — First-time setup / troubleshooter
:: Run this if TimcoDWG.exe fails with "Failed to load Python DLL".
:: Installs the Visual C++ Runtime that Python needs, then launches the app.

cd /d "%~dp0"

echo ============================================
echo   Timco DWG Viewer - Setup
echo ============================================
echo.

:: ── Check if VC++ runtime is already available ──
:: python3*.dll depends on vcruntime140.dll — if it's loadable, we're good.
where /Q vcruntime140.dll 2>NUL
if not errorlevel 1 (
    echo [OK] Visual C++ Runtime is already installed.
    goto :launch
)
:: Also check the _internal folder (PyInstaller bundles it there)
if exist "_internal\vcruntime140.dll" (
    echo [OK] Visual C++ Runtime found in app bundle.
    goto :launch
)

echo [!!] Visual C++ Runtime is missing.
echo     This is required for TimcoDWG to start.
echo.

:: ── Try to install via winget ──
where /Q winget 2>NUL
if errorlevel 1 (
    echo winget is not available on this system.
    echo.
    echo Please install the Visual C++ Runtime manually:
    echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.
    echo Download and run the installer, then try launching TimcoDWG.exe again.
    pause
    exit /b 1
)

echo Installing Visual C++ Runtime via winget...
echo (This only needs to happen once)
echo.
winget install Microsoft.VCRedist.2015+.x64 --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo.
    echo Installation may have failed. You can install it manually:
    echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.
    pause
    exit /b 1
)
echo.
echo [OK] Visual C++ Runtime installed successfully.

:launch
echo.
echo Starting Timco DWG Viewer...
start "" "TimcoDWG.exe"
