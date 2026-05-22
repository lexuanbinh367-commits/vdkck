@echo off
echo Dang dung MQTT...
net stop mosquitto >nul 2>&1
taskkill /F /IM mosquitto.exe >nul 2>&1
echo Dong cua so "Solar Web" bang Ctrl+C hoac dong cua so.
echo Xong.
