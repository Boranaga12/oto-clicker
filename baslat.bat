@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "BASE_PYTHON="
set "BASE_ARGS="
set "VENV_DIR=%~dp0kodlar\.venv"
set "VENV_PYTHON=%~dp0kodlar\.venv\Scripts\python.exe"
set "VENV_PYTHONW=%~dp0kodlar\.venv\Scripts\pythonw.exe"
set "REQUIREMENTS=%~dp0kodlar\requirements.txt"
set "REQUIREMENTS_STAMP=%~dp0kodlar\.venv\requirements.installed"

if exist "%VENV_PYTHON%" goto dependencies

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
    if not errorlevel 1 (
        set "BASE_PYTHON=py"
        set "BASE_ARGS=-3"
    )
)

if not defined BASE_PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
        if not errorlevel 1 set "BASE_PYTHON=python"
    )
)

if not defined BASE_PYTHON (
    echo HATA: Python 3.10 veya daha yenisi bulunamadi.
    echo Python'u https://www.python.org/downloads/ adresinden bir kez kurun.
    echo Kurulumda "Add python.exe to PATH" secenegini isaretleyin.
    echo Ardindan bu dosyayi yeniden calistirin.
    goto failure
)

:create_environment
echo Uygulama ortami hazirlaniyor...
"%BASE_PYTHON%" %BASE_ARGS% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo HATA: Sanal Python ortami olusturulamadi.
    goto failure
)

:dependencies
if not exist "%REQUIREMENTS_STAMP%" goto install_dependencies
fc /b "%REQUIREMENTS%" "%REQUIREMENTS_STAMP%" >nul 2>&1
if errorlevel 1 goto install_dependencies
"%VENV_PYTHON%" -c "import pynput" >nul 2>&1
if not errorlevel 1 goto launch

:install_dependencies
echo Gerekli kutuphaneler kuruluyor...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%REQUIREMENTS%"
if errorlevel 1 (
    echo HATA: Gerekli Python kutuphaneleri yuklenemedi.
    goto failure
)
copy /y "%REQUIREMENTS%" "%REQUIREMENTS_STAMP%" >nul

:launch
if defined OTO_CLICKER_VALIDATE_ONLY (
    "%VENV_PYTHON%" -c "import kodlar.main"
    if errorlevel 1 goto failure
    echo Baslatma denetimi basarili.
    exit /b 0
)

if defined OTO_CLICKER_DEBUG goto debug_launch
if not exist "%VENV_PYTHONW%" goto debug_launch
start "" "%VENV_PYTHONW%" -m kodlar.launcher
exit /b 0

:debug_launch
rem Hata ayiklamada konsolu acik tut.
"%VENV_PYTHON%" -u -X faulthandler -m kodlar.main
if errorlevel 1 goto failure
exit /b 0

:failure
echo.
echo Ayrintilari kontrol etmek icin bu pencereyi kapatmadan once yukaridaki hatayi okuyun.
pause
exit /b 1
