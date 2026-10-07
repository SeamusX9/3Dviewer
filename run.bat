@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 未找到虚拟环境。请先执行：
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "%~dp0main.py" %*
if errorlevel 1 pause
