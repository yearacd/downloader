@echo off
cd /d "%~dp0"
venv\Scripts\pip install qrcode[pil]
if errorlevel 1 (
    echo 安装失败，请手动运行: venv\Scripts\pip install qrcode[pil]
    pause
) else (
    echo 安装成功!
    pause
)
