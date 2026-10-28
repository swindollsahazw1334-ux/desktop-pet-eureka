"""
开机自启：写在当前用户的注册表 Run 项里 (HKCU，不需要管理员权限)，默认关闭

    is_enabled()     现在开着没有
    set_enabled(on)  打开 / 关闭
"""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "EurekaDesktopPet"


def command():
    """开机时执行的命令：打包后直接运行 exe，源码运行时用 pythonw 启动 gui_main.py (不弹黑框)"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_main.py")
    return f'"{pythonw}" "{script}"'


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
