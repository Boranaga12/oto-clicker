@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "BASE_PYTHON="
set "BASE_ARGS="
set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
set "REQUIREMENTS=%~dp0kodlar\requirements.txt"
set "REQUIREMENTS_STAMP=%~dp0.venv\requirements.installed"
set "INSTALLER_PATH=%~dp0python_installer.exe"

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

if not defined BASE_PYTHON goto install_python
goto create_environment

:install_python
echo Python 3.10 veya daha yenisi bulunamadi.
echo Python kullanici hesabiniza kuruluyor; lutfen bekleyin...

if not exist "%~dp0python_installer.exe" (
    echo HATA: Python yukleyicisi bulunamadi.
    echo Python'u python.org adresinden kurup tekrar deneyin.
    goto failure
)

powershell.exe -NoProfile -NonInteractive -Command "if ((Get-AuthenticodeSignature -LiteralPath $env:INSTALLER_PATH).Status -ne 'Valid') { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo HATA: Python yukleyicisinin dijital imzasi gecerli degil.
    goto failure
)

start "" /wait "%INSTALLER_PATH%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0
if errorlevel 1 (
    echo HATA: Python kurulumu tamamlanamadi.
    goto failure
)

if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
    set "BASE_PYTHON=%LocalAppData%\Programs\Python\Python310\python.exe"
) else (
    echo HATA: Kurulum tamamlandi ancak python.exe bulunamadi.
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
"%VENV_PYTHON%" -c "import kodlar.main" >nul 2>&1
if errorlevel 1 (
    echo HATA: Uygulama modulleri yuklenemedi.
    echo Ayrintili denetim icin: .venv\Scripts\python.exe -m kodlar.main
    goto failure
)

if defined OTO_CLICKER_VALIDATE_ONLY (
    echo Baslatma denetimi basarili: %VENV_PYTHON%
    exit /b 0
)

if exist "%VENV_PYTHONW%" (
    start "" "%VENV_PYTHONW%" -m kodlar.main
) else (
    start "" "%VENV_PYTHON%" -m kodlar.main
)
exit /b 0

:failure
echo.
echo Ayrintilari kontrol etmek icin bu pencereyi kapatmadan once yukaridaki hatayi okuyun.
pause
exit /b 1
