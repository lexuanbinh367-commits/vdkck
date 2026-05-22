@echo off
chcp 65001 >nul
title Solar Tracker

setlocal

:: ===== DUONG DAN =====
set "ROOT=%~dp0"
set "SRV=%ROOT%server"

set "MOSQ=C:\Program Files\mosquitto\mosquitto.exe"
set "CONF=%SRV%\mosquitto\mosquitto.conf"

set "PY=%SRV%\venv\Scripts\python.exe"

cd /d "%SRV%"

echo.
echo =========================================
echo    NANG LUONG MAT TROI - KHOI DONG
echo =========================================
echo.

:: =====================================================
:: KIEM TRA MOSQUITTO
:: =====================================================

if not exist "%MOSQ%" (
    echo [LOI] Khong tim thay Mosquitto:
    echo %MOSQ%
    echo.
    echo Cai dat tai:
    echo https://mosquitto.org/download/
    echo.
    pause
    exit /b 1
)

:: =====================================================
:: KIEM TRA PYTHON VENV
:: =====================================================

if not exist "%PY%" (
    echo [LOI] Khong tim thay Python venv:
    echo %PY%
    echo.
    echo Tao moi:
    echo python -m venv venv
    echo venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: =====================================================
:: TAT MOSQUITTO CU
:: =====================================================

echo [1] Tat MQTT cu...

net stop mosquitto >nul 2>&1
taskkill /F /IM mosquitto.exe >nul 2>&1

timeout /t 2 /nobreak >nul

:: =====================================================
:: BAT MQTT
:: =====================================================

echo [2] Bat MQTT Broker...

start "MQTT Broker" cmd /k ""%MOSQ%" -v -c "%CONF%""

timeout /t 5 /nobreak >nul

:: =====================================================
:: KIEM TRA PORT 1883
:: =====================================================

netstat -ano | find ":1883" >nul

if errorlevel 1 (
    echo.
    echo =========================================
    echo [LOI] MQTT KHONG MO CONG 1883
    echo =========================================
    echo.
    echo Thu lai bang CMD ADMIN:
    echo.
    echo net stop mosquitto
    echo.
    echo Sau do chay lai CHAY.bat
    echo.
    pause
    exit /b 1
)

echo MQTT OK
echo.

:: =====================================================
:: BAT DJANGO
:: =====================================================

echo [3] Bat Django Web...

start "Solar Web" cmd /k ""%PY%" manage.py runserver 127.0.0.1:8000"

timeout /t 3 /nobreak >nul

:: =====================================================
:: MO TRINH DUYET
:: =====================================================

start "" "http://127.0.0.1:8000/"

echo.
echo =========================================
echo               HE THONG SAN SANG
echo =========================================
echo.
echo Dashboard:
echo http://127.0.0.1:8000/
echo.
echo MQTT Port:
echo 1883
echo.
echo Luu y:
echo - Giu nguyen cua so MQTT
echo - Giu nguyen cua so Solar Web
echo - ESP phai hien "MQTT Connected"
echo.

pause