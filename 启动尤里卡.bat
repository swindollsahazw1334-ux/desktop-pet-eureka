@echo off
:: 正常启动尤里卡桌宠 (不显示黑色命令行窗口；运行日志写在 eureka.log)
cd /d "%~dp0"
start "" pythonw gui_main.py
