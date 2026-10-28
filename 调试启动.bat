@echo off
:: 调试启动：保留命令行窗口，能直接看到报错
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ==========================================
echo      尤里卡 (调试模式) 启动中...
echo ==========================================

python gui_main.py

:: 程序意外退出时停住，方便看报错
pause
