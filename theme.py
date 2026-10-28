"""
尤里卡的界面主题：所有颜色、字体、圆角都从这里来，保证各个窗口看起来是一套

风格：奶白底 + 她头发的粉色做点缀，深紫灰写字；圆角、轻阴影
改颜色只改这里的 PALETTE，全部界面会一起变。
"""
import os
import sys

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGraphicsDropShadowEffect


def _app_path():
    """打包进程序的资源目录：打包后在 _internal (sys._MEIPASS) 里"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


ICON_DIR = os.path.join(_app_path(), "assets", "ui").replace("\\", "/")

PALETTE = {
    "bg": "#FFF9FC",          # 窗口底色 (奶白带一点粉)
    "surface": "#FFFFFF",     # 卡片、输入框
    "surface_alt": "#FFF2F8", # 按钮底、次要块
    "border": "#F5D6E5",
    "primary": "#FF6FA8",     # 主色：她头发的粉
    "primary_dark": "#E2558F",
    "primary_soft": "#FFE3EF",
    "text": "#3A3242",
    "muted": "#8E8299",
    "thought_bg": "#F3EEFF",  # 内心独白
    "thought_text": "#6B5B95",
    # 状态小标签前面的小圆点
    "listening": "#FF5C7A",
    "thinking": "#F5A524",
    "acting": "#5B8DEF",
    "focus": "#2EB67D",
    "break": "#F5A524",
    "tasks": "#8B7CF6",
    "done": "#F5A524",
}
P = PALETTE

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"


def font(size=10, bold=False, italic=False):
    f = QFont(FONT_FAMILY, size)
    f.setBold(bold)
    f.setItalic(italic)
    return f


def add_shadow(widget, blur=18, alpha=40, dy=3):
    """轻轻的投影，让小部件从桌面上 "浮" 起来"""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(120, 60, 90, alpha))
    widget.setGraphicsEffect(effect)
    return effect


def chip_style():
    """桌宠身边的小标签 (状态、专注倒计时、任务进度) 的统一样式"""
    return (f"QLabel {{ background-color: rgba(255, 255, 255, 240); color: {P['text']};"
            f" border: 1px solid {P['border']}; border-radius: 11px; padding: 3px 10px; }}")


def chip_text(text, dot_color):
    """前面带一个彩色小圆点的标签文字"""
    return f'<span style="color:{dot_color};">●</span>&nbsp;{text}'


APP_QSS = f"""
/* ---------- 对话框和窗口 ---------- */
QDialog, QMessageBox, QInputDialog, QWidget#window {{
    background-color: {P['bg']};
}}
QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel, QWidget#window QLabel {{
    color: {P['text']};
}}
QLabel#pageTitle {{ font-size: 17px; font-weight: bold; color: {P['text']}; padding: 2px 2px 6px 2px; }}
QLabel#pageDesc, QLabel#hint {{ color: {P['muted']}; font-size: 12px; }}
QLabel#cardTitle {{ font-size: 13px; font-weight: bold; color: {P['text']}; }}
QLabel#value {{ color: {P['primary_dark']}; font-size: 12px; font-weight: bold; }}
QFrame#card {{
    background-color: {P['surface']};
    border: 1px solid {P['border']};
    border-radius: 14px;
}}
QLabel#prompter {{
    background-color: {P['primary_soft']}; color: {P['primary_dark']};
    border-radius: 12px; padding: 12px; font-size: 13px; font-weight: bold;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background-color: {P['surface_alt']}; color: {P['text']};
    border: 1px solid {P['border']}; border-radius: 10px;
    padding: 7px 16px; font-size: 13px;
}}
QPushButton:hover {{ background-color: {P['primary_soft']}; border-color: {P['primary']}; }}
QPushButton:pressed {{ background-color: #FFD3E5; }}
QPushButton:disabled {{ color: {P['muted']}; background-color: #F6F1F4; border-color: #EEE6EA; }}
QPushButton[primary="true"], QDialogButtonBox QPushButton:default {{
    background-color: {P['primary']}; color: white; border: none; font-weight: bold;
}}
QPushButton[primary="true"]:hover, QDialogButtonBox QPushButton:default:hover {{ background-color: {P['primary_dark']}; }}
QPushButton[recording="true"] {{ background-color: {P['listening']}; color: white; border: none; font-weight: bold; }}

/* ---------- 输入 ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background-color: {P['surface']}; color: {P['text']};
    border: 1px solid {P['border']}; border-radius: 10px;
    padding: 6px 10px; font-size: 13px;
    selection-background-color: {P['primary_soft']}; selection-color: {P['text']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {P['primary']};
}}
QTextEdit#code, QPlainTextEdit#code {{ font-family: {MONO_FAMILY}; font-size: 12px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({ICON_DIR}/chevron.svg); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background-color: {P['surface']}; border: 1px solid {P['border']}; border-radius: 8px;
    selection-background-color: {P['primary_soft']}; selection-color: {P['primary_dark']}; outline: none;
}}

/* ---------- 滑块 / 勾选 ---------- */
QSlider::groove:horizontal {{ height: 6px; background: {P['primary_soft']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {P['primary']}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: white; border: 2px solid {P['primary']};
    width: 14px; height: 14px; margin: -6px 0; border-radius: 9px;
}}
QCheckBox {{ color: {P['text']}; spacing: 8px; font-size: 13px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {P['border']}; background: white; }}
QCheckBox::indicator:checked {{ background: {P['primary']}; border-color: {P['primary']}; image: url({ICON_DIR}/check.svg); }}

/* ---------- 设置窗口的侧边栏 ---------- */
QListWidget#sidebar {{ background: transparent; border: none; outline: none; font-size: 13px; }}
QListWidget#sidebar::item {{ color: {P['text']}; padding: 10px 14px; margin: 2px 0; border-radius: 10px; }}
QListWidget#sidebar::item:hover {{ background-color: {P['surface_alt']}; }}
QListWidget#sidebar::item:selected {{ background-color: {P['primary_soft']}; color: {P['primary_dark']}; font-weight: bold; }}

/* ---------- 菜单 (右键、托盘) ---------- */
QMenu {{
    background-color: {P['surface']}; color: {P['text']};
    border: 1px solid {P['border']}; border-radius: 12px; padding: 6px;
    font-size: 13px;
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 8px; }}
QMenu::item:selected {{ background-color: {P['primary_soft']}; color: {P['primary_dark']}; }}
QMenu::separator {{ height: 1px; background: {P['border']}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {P['border']}; background: white; margin-left: 6px; }}
QMenu::indicator:checked {{ background: {P['primary']}; border-color: {P['primary']}; image: url({ICON_DIR}/check.svg); }}

/* ---------- 提示 / 滚动条 ---------- */
QToolTip {{
    background-color: {P['text']}; color: white; border: none;
    border-radius: 6px; padding: 4px 8px; font-size: 12px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {P['primary_soft']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #FFC4DC; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; height: 0; }}
"""

_applied = False


def apply(app):
    """整个程序启动时调用一次：统一字体和全局样式 (输入框、消息框、菜单都会跟着变)"""
    global _applied
    if app is None or _applied:
        return
    app.setFont(font(10))
    app.setStyleSheet(APP_QSS)
    # 消息框、输入框里 Qt 自带的按钮用中文 ("确定 / 取消" 而不是 "OK / Cancel")
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
        app._eureka_translator = translator  # 留个引用，别被回收
    _applied = True
