@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

set "APP_NAME=UIIC_Surveyor_Automation"
set "VENV_DIR=%PROJECT_ROOT%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "DIST_DIR=%PROJECT_ROOT%dist\%APP_NAME%"
set "BUILD_ASSETS=%PROJECT_ROOT%build_assets"
set "PLAYWRIGHT_CACHE=%BUILD_ASSETS%\ms-playwright"
set "PADDLEOCR_CACHE=%BUILD_ASSETS%\paddleocr"
set "SKIP_INSTALL="

if /I "%~1"=="--rebuild" (
    set "SKIP_INSTALL=1"
)

echo.
echo ================================================================
echo   UIIC Surveyor Automation - Windows EXE Build
echo ================================================================
echo.

if not exist "%VENV_PYTHON%" (
    call :resolve_base_python
    if errorlevel 1 exit /b 1

    echo [1/7] Creating virtual environment with %BASE_PYTHON_LABEL%...
    call %BASE_PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b 1
) else (
    echo [1/7] Reusing existing virtual environment...
)

echo [2/7] Verifying builder Python...
"%VENV_PYTHON%" -c "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)"
if errorlevel 1 (
    echo [ERROR] Build Python must be 3.10, 3.11, or 3.12.
    exit /b 1
)
"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Python 3.10 is preferred for release builds. Continuing with the active venv anyway.
)

if defined SKIP_INSTALL (
    echo [3/7] Skipping dependency install (--rebuild)
) else (
    echo [3/7] Installing build dependencies...
    "%VENV_PYTHON%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo [INFO] pip is missing in the virtual environment. Bootstrapping with ensurepip...
        "%VENV_PYTHON%" -m ensurepip --upgrade
        if errorlevel 1 exit /b 1
    )
    "%VENV_PYTHON%" -m pip install --upgrade pip wheel
    if errorlevel 1 exit /b 1
    "%VENV_PYTHON%" -m pip install -r requirements-build.txt
    if errorlevel 1 exit /b 1
)

if not exist "%BUILD_ASSETS%" mkdir "%BUILD_ASSETS%"
if not exist "%PLAYWRIGHT_CACHE%" mkdir "%PLAYWRIGHT_CACHE%"
if not exist "%PADDLEOCR_CACHE%" mkdir "%PADDLEOCR_CACHE%"

set "PLAYWRIGHT_BROWSERS_PATH=%PLAYWRIGHT_CACHE%"
set "PADDLEOCR_HOME=%PADDLEOCR_CACHE%"

echo [4/7] Preparing bundled Playwright Chromium runtime...
"%VENV_PYTHON%" -m playwright install chromium
if errorlevel 1 exit /b 1

echo [5/7] Preparing bundled PaddleOCR models...
"%VENV_PYTHON%" -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=False, lang='en', show_log=False); print('PaddleOCR models ready.')"
if errorlevel 1 exit /b 1

echo [6/7] Cleaning old build output...
if exist "%PROJECT_ROOT%build" rmdir /s /q "%PROJECT_ROOT%build"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"

echo [7/7] Running PyInstaller...
set "PYTHONWARNINGS=ignore:The numpy.array_api submodule is still experimental.:UserWarning,ignore:invalid escape sequence.*:SyntaxWarning"
"%VENV_PYTHON%" -m PyInstaller --noconfirm --clean uiic_automation.spec
if errorlevel 1 exit /b 1

if not exist "%DIST_DIR%\%APP_NAME%.exe" (
    echo [ERROR] Build finished without producing %APP_NAME%.exe
    exit /b 1
)

echo.
echo ================================================================
echo   BUILD SUCCESSFUL
echo ================================================================
echo Output folder:
echo   %DIST_DIR%
echo.
echo EXE:
echo   %DIST_DIR%\%APP_NAME%.exe
echo.
echo Bundled runtime dependencies:
echo   - Playwright Chromium from build_assets\ms-playwright
echo   - PaddleOCR models from build_assets\paddleocr
echo.
exit /b 0

:resolve_base_python
set "BASE_PYTHON_CMD="
set "BASE_PYTHON_LABEL="

py -3.10 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "BASE_PYTHON_CMD=py -3.10"
    set "BASE_PYTHON_LABEL=py -3.10"
    exit /b 0
)

python -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BASE_PYTHON_CMD=python"
    set "BASE_PYTHON_LABEL=python"
    exit /b 0
)

echo [ERROR] Python 3.10-3.12 is required to build the EXE.
echo         Install Python 3.10 for the most stable PaddleOCR release build.
exit /b 1
