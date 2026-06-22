@echo off
chcp 65001 >nul
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo.
echo  Bilibili Downloader Web
echo ==============================
echo.
python app.py
if %errorlevel% neq 0 (
    echo.
    pause
)
