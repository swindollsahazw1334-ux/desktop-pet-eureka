import sys
import os
import json
import math
import threading
import shutil
import random
import re
import time

class RotatingLog:
    """
    eureka.log：超过 5MB 就改名成 eureka.log.1 (最多留 2 份旧的) 重新写，不会越积越大
    """
    MAX_BYTES = 5 * 1024 * 1024
    BACKUPS = 2

    def __init__(self, path):
        self.path = path
        self._writes = 0
        self._open()

    def _open(self):
        if os.path.exists(self.path) and os.path.getsize(self.path) > self.MAX_BYTES:
            self._rotate_files()
        self.file = open(self.path, "a", encoding="utf-8", buffering=1)

    def _rotate_files(self):
        for i in range(self.BACKUPS, 0, -1):
            older = f"{self.path}.{i}"
            newer = f"{self.path}.{i - 1}" if i > 1 else self.path
            try:
                if os.path.exists(older):
                    os.remove(older)
                if os.path.exists(newer):
                    os.rename(newer, older)
            except OSError:
                pass

    def write(self, text):
        self.file.write(text)
        self._writes += 1
        if self._writes % 200 == 0 and self.file.tell() > self.MAX_BYTES:
            self.file.close()
            self._rotate_files()
            self.file = open(self.path, "a", encoding="utf-8", buffering=1)

    def flush(self):
        self.file.flush()


# 用 pythonw 启动时没有控制台，把输出和报错写进 eureka.log，出问题时可以翻
if sys.stdout is None or sys.stderr is None:
    _log_file = RotatingLog(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "eureka.log"))
    sys.stdout = sys.stdout or _log_file
    sys.stderr = sys.stderr or _log_file
# 开机自启时工作目录是 System32，先切回程序所在的文件夹，相对路径的文件才找得到
os.chdir(os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)))
# 1. 窗口与控件
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit, 
    QPushButton, QDialog, QTabWidget, QMessageBox, QHBoxLayout, 
    QSlider, QGroupBox, QMainWindow, QLineEdit, QFormLayout, QComboBox, QCheckBox,
    QListWidget, QStackedWidget, QMenu, QSystemTrayIcon, QInputDialog, QGridLayout,
    QScrollArea, QFrame, QFileDialog
)

# 2. 核心功能 (多线程、信号槽)
from PySide6.QtCore import (
    QUrl, Slot, QObject, Qt, Signal, QThread, QTimer, QPoint, QSettings, QEvent, QRectF, QPointF
)

# 3. 绘图与字体 (这次报错就是缺了这里面的 QFont)
from PySide6.QtGui import (
    QIcon, QTextCursor, QFont, QAction, QColor, QCursor, QPainter, QPainterPath, QPen
)

# 4. 浏览器组件 (显示 Live2D 用的)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

# 导入你的核心逻辑
import main 
import events
import theme
import character
import setup_ui
import autostart
import version

def get_resource_path(relative_path):
    """打包进程序的文件 (图标、网页等)：打包后在 _internal (sys._MEIPASS) 里"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(main.get_app_path(), relative_path)

# ==========================================
# 0. 输出重定向 (把 print 变成信号)
# ==========================================
class StreamRedirector(QObject):
    text_written = Signal(str)

    def __init__(self):
        super().__init__()
        self.original = sys.stdout  # 同时写一份到控制台 / eureka.log，方便排查

    def write(self, text):
        self.text_written.emit(str(text))
        try:
            self.original.write(text)
            self.original.flush()
        except Exception:
            pass
    
    def flush(self):
        pass

# ==========================================
# 1. 配置编辑器窗口 (新功能核心)
# ==========================================
class ConfigDialog(QDialog):
    """设置窗口：左边分类，右边一张张卡片，底部保存"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{character.name()} · 设置")
        self.resize(820, 620)
        self.current_settings = main.load_settings()

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        body = QHBoxLayout()
        body.setSpacing(18)
        side = QVBoxLayout()
        side.setSpacing(8)
        title = QLabel("⚙️ 设置")
        title.setObjectName("pageTitle")
        side.addWidget(title)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(170)
        side.addWidget(self.sidebar)
        body.addLayout(side)

        self.stacked_widget = QStackedWidget()
        pages = [
            ("🔑  账号与模型", self.init_account_tab()),
            ("💬  对话与听觉", self.init_audio_tab()),
            ("🔒  隐私", self.init_privacy_tab()),
            ("📰  每日早报", self.init_news_tab()),
            ("📱  软件路径", self.init_apps_tab()),
            ("🧠  记忆库", self.init_memory_tab()),
            ("🎨  外观与角色", self.init_look_tab()),
        ]
        for name, page in pages:
            self.sidebar.addItem(name)
            self.stacked_widget.addWidget(page)
        self.sidebar.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        body.addWidget(self.stacked_widget, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        note = QLabel("账号、模型、对话模式等设置重启后生效")
        note.setObjectName("hint")
        bottom.addWidget(note)
        bottom.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("保存")
        self.btn_save.setProperty("primary", True)
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.save_all_configs)
        bottom.addWidget(cancel)
        bottom.addWidget(self.btn_save)
        root.addLayout(bottom)

    # ---------------- 页面和卡片 ----------------
    def _page(self, title, desc):
        """一页：标题 + 说明 + 可滚动的卡片区"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("pageBody")
        scroll.setStyleSheet("QScrollArea, QWidget#pageBody { background: transparent; }")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        if desc:
            hint = QLabel(desc)
            hint.setObjectName("pageDesc")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        scroll.setWidget(inner)
        return scroll, layout

    def _card(self, title, desc=""):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        if desc:
            hint = QLabel(desc)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        return card, layout

    def _slider_row(self, slider, value_label):
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        value_label.setObjectName("value")
        value_label.setMinimumWidth(48)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(value_label)
        return row

    def _json_editor(self, filename, pretty):
        editor = QTextEdit()
        editor.setObjectName("code")
        editor.setAcceptRichText(False)
        try:
            path = os.path.join(main.get_app_path(), filename)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = json.dumps(json.load(f), indent=4, ensure_ascii=False) if pretty else f.read()
            else:
                content = "{}"
        except Exception as e:
            content = f"Error loading: {e}"
        editor.setPlainText(content)
        return editor

    # ---------------- 各页 ----------------
    def init_audio_tab(self):
        page, layout = self._page("对话与听觉", "她怎么听你说话、怎么判断你在叫她。")

        card, box = self._card("对话模式", "实时语音：唤醒后可以连着聊，不用每句都喊名字。经典：每句都要先唤醒。实时语音连不上时会自动用经典模式。")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("实时语音 (千问 Omni)", "omni")
        self.mode_combo.addItem("经典", "classic")
        self.mode_combo.setCurrentIndex(0 if self.current_settings.get("voice_mode", "omni") == "omni" else 1)
        box.addWidget(self.mode_combo)
        layout.addWidget(card)

        card, box = self._card("名字唤醒灵敏度", f"数值越大越难唤醒、越不容易被别的声音误唤醒；叫不醒就调小一点。唤醒词：{' / '.join(character.wake_word_names())}")
        self.wake_slider = QSlider(Qt.Horizontal)
        self.wake_slider.setRange(0, 100)
        current_sens = self.current_settings.get("wake_sensitivity", 0.5)
        self.wake_slider.setValue(int(current_sens * 100))
        self.wake_value_label = QLabel(f"{current_sens:.2f}")
        self.wake_slider.valueChanged.connect(lambda v: self.wake_value_label.setText(f"{v / 100:.2f}"))
        box.addLayout(self._slider_row(self.wake_slider, self.wake_value_label))
        layout.addWidget(card)

        card, box = self._card("说话检测灵敏度", "经典模式录音用：数值越小越灵敏 (容易被噪音误触)，越大越迟钝。推荐 300 (安静) ~ 1000 (嘈杂)。")
        self.vad_slider = QSlider(Qt.Horizontal)
        self.vad_slider.setRange(100, 2000)
        self.vad_slider.setValue(self.current_settings.get("vad_threshold", 500))
        self.vad_value_label = QLabel(str(self.vad_slider.value()))
        self.vad_slider.valueChanged.connect(lambda v: self.vad_value_label.setText(str(v)))
        box.addLayout(self._slider_row(self.vad_slider, self.vad_value_label))
        layout.addWidget(card)

        card, box = self._card("语音识别模型", "经典模式用。模型越大越准，但越吃内存、启动越慢，常驻桌面推荐 small；新模型首次使用会自动下载。")
        self.model_combo = QComboBox()
        self.model_combo.addItems(["base", "small", "medium", "large-v3-turbo"])
        self.model_combo.setCurrentText(self.current_settings.get("whisper_model", "small"))
        box.addWidget(self.model_combo)
        layout.addWidget(card)

        layout.addStretch()
        return page

    def init_account_tab(self):
        page, layout = self._page("账号与模型", "她的大脑和声音用的云端服务。改了之后要重启才生效。")
        self.account_form = setup_ui.AccountForm()
        layout.addWidget(self.account_form)
        layout.addStretch()
        return page

    def init_privacy_tab(self):
        page, layout = self._page("隐私", "她能看到什么、你的数据存在哪里。")
        self.privacy_form = setup_ui.PrivacyForm()
        layout.addWidget(self.privacy_form)
        layout.addStretch()
        return page

    def init_look_tab(self):
        page, layout = self._page("外观与角色", "她长什么样、叫什么名字、什么性格。")

        card, box = self._card("Live2D 形象", "选一个 .model3.json 文件。请使用你自己有权使用的模型，程序本身不附带任何模型。换了之后重启生效。")
        row = QHBoxLayout()
        self.model_input = QLineEdit(character.current.get("live2d_model", ""))
        self.model_input.setPlaceholderText(character.model_path() or "还没有选模型")
        browse = QPushButton("选择…")
        browse.clicked.connect(self.choose_model)
        row.addWidget(self.model_input, 1)
        row.addWidget(browse)
        box.addLayout(row)
        hint = QLabel("留空会自动使用 live2d_resources 文件夹里的第一个模型。表情名不一样的话，在角色设定文件的 expression_map 里对应一下。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        box.addWidget(hint)
        layout.addWidget(card)

        card, box = self._card("角色设定", f"名字、人设、喜好、唤醒词都在 character.json 里，可以改成你自己的角色。现在的角色：{character.name()}")
        open_btn = QPushButton("打开角色设定文件")
        open_btn.clicked.connect(lambda: os.startfile(character.CHARACTER_FILE))
        box.addWidget(open_btn, 0, Qt.AlignLeft)
        layout.addWidget(card)

        card, box = self._card("启动与关于", f"版本 {version.__version__}")
        self.checkbox_autostart = QCheckBox("开机时自动启动")
        self.checkbox_autostart.setChecked(autostart.is_enabled())
        box.addWidget(self.checkbox_autostart)
        row = QHBoxLayout()
        for text, name in (("更新记录", "CHANGELOG.md"), ("使用说明", "README.md"), ("许可协议", "LICENSE")):
            btn = QPushButton(text)
            path = os.path.join(main.get_app_path(), name)
            btn.setEnabled(os.path.exists(path))
            btn.clicked.connect(lambda _=False, p=path: os.startfile(p))
            row.addWidget(btn)
        row.addStretch()
        box.addLayout(row)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def choose_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型", main.get_app_path(), "Live2D 模型 (*.model3.json)")
        if path:
            self.model_input.setText(path)

    def init_news_tab(self):
        page, layout = self._page("每日早报", "每天第一次启动时，她会查天气、搜你关心的话题，给你播一段早报。")
        card, box = self._card("早报")
        self.checkbox_broadcast = QCheckBox("开机自动播报早报")
        self.checkbox_broadcast.setChecked(self.current_settings.get("enable_daily_broadcast", True))
        box.addWidget(self.checkbox_broadcast)
        topic_label = QLabel("关注的话题")
        topic_label.setObjectName("cardTitle")
        box.addSpacing(6)
        box.addWidget(topic_label)
        self.news_input = QLineEdit()
        self.news_input.setPlaceholderText("例如：人工智能最新进展、NBA 昨日战况、今日财经大盘")
        self.news_input.setText(self.current_settings.get("news_topic", "今日科技社会热点新闻"))
        box.addWidget(self.news_input)
        hint = QLabel("不填就默认搜「今日科技社会热点新闻」。")
        hint.setObjectName("hint")
        box.addWidget(hint)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def init_apps_tab(self):
        page, layout = self._page("软件路径", "说「打开 xx」时她去这里找程序。格式：{\"软件名\": \"程序完整路径\"}")
        self.editor_apps = self._json_editor("apps.json", pretty=False)
        self.editor_apps.setMinimumHeight(380)
        layout.addWidget(self.editor_apps, 1)
        return page

    def init_memory_tab(self):
        page, layout = self._page("记忆库", "家庭成员的档案 (生日、喜好、对她的称呼等)。聊天里自动记下的事在长期记忆库里，不在这里。")
        self.editor_memory = self._json_editor("memory.json", pretty=True)
        self.editor_memory.setMinimumHeight(380)
        layout.addWidget(self.editor_memory, 1)
        return page

    # ---------------- 保存 ----------------
    def save_all_configs(self):
        # 0. 账号、隐私
        self.account_form.save()
        self.privacy_form.save()
        main.set_observer_enabled(self.privacy_form.observer.isChecked() and self.privacy_form.activity.isChecked())

        # 1. 保存 Apps
        try:
            new_apps = json.loads(self.editor_apps.toPlainText())
            with open(os.path.join(main.get_app_path(), "apps.json"), 'w', encoding='utf-8') as f:
                json.dump(new_apps, f, ensure_ascii=False, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"软件路径格式错误：\n{e}")
            return

        # 2. 保存 Memory
        try:
            new_memory = json.loads(self.editor_memory.toPlainText())
            with open(os.path.join(main.get_app_path(), "memory.json"), 'w', encoding='utf-8') as f:
                json.dump(new_memory, f, ensure_ascii=False, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"记忆库格式错误：\n{e}")
            return

        # 3. 保存 Settings (听觉 + 早报)
        topic = self.news_input.text().strip()
        if not topic: topic = "今日科技社会热点新闻"

        new_settings = {
            "vad_threshold": self.vad_slider.value(),
            "wake_sensitivity": self.wake_slider.value() / 100.0,
            "news_topic": topic,
            "enable_daily_broadcast": self.checkbox_broadcast.isChecked(),
            "whisper_model": self.model_combo.currentText(),
            "voice_mode": self.mode_combo.currentData(),
        }

        try:
            # 只覆盖这几项，"观察我"等其他设置保持不变
            main.save_settings(new_settings)
            model = self.model_input.text().strip()
            if model != character.current.get("live2d_model", ""):
                character.update(live2d_model=model)
            if self.checkbox_autostart.isChecked() != autostart.is_enabled():
                autostart.set_enabled(self.checkbox_autostart.isChecked())
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"设置保存错误：\n{e}")
            return

        QMessageBox.information(self, "已保存", "设置已保存~\n账号、模型、对话模式、电脑使用统计重启后生效。")
        self.accept()

   
# ==========================================
# 2. 后台工作线程
# ==========================================
class AssistantThread(QThread):
    def run(self):
        main.run_eureka()


class EventBridge(QObject):
    """把后台线程发来的 events 转成 Qt 信号，回到界面线程里处理"""
    event = Signal(str, object)

    def __init__(self):
        super().__init__()
        events.subscribe(lambda kind, data: self.event.emit(kind, data))


class Bridge(QObject):
    def __init__(self):
        super().__init__()

    @Slot(str)
    def log_to_py(self, text):
        # 这里接收网页发来的日志，比如 "模型加载成功"
        # 实际打印逻辑在 MainWindow 里处理，这里留空防止报错即可，或者简单的 print
        # print(f"[JS]: {text}") 
        pass

# 2. Live2D 窗口组件：显示二次元老婆的核心
class Live2DWidget(QWebEngineView):
    def __init__(self):
        super().__init__()
        
        # --- 透明背景设置 (关键) ---
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.page().setBackgroundColor(Qt.transparent)
        
        # 禁用右键菜单 (防止误触)
        self.setContextMenuPolicy(Qt.NoContextMenu)

        # --- 建立通信通道 ---
        self.channel = QWebChannel()
        self.bridge = Bridge()
        self.channel.registerObject("pyBridge", self.bridge)
        self.page().setWebChannel(self.channel)

        # --- 加载网页 ---
        # 🛠️ 路径修复：优先查找打包后的 _internal 目录
        if hasattr(sys, '_MEIPASS'):
            # 如果是打包环境，资源在 _internal (sys._MEIPASS) 里
            html_path = os.path.join(sys._MEIPASS, "web_face.html")
        else:
            # 如果是开发环境，资源在当前目录
            html_path = os.path.join(main.get_app_path(), "web_face.html")
        
        # 调试打印 (可选，方便你看路径对不对)
        print(f"🌍 Live2D 网页路径: {html_path}")
        
        if not os.path.exists(html_path):
            print("❌ 严重错误: 找不到 web_face.html！")
            
        url = QUrl.fromLocalFile(html_path)
        model = character.model_path()
        self.has_model = bool(model)
        if model:
            url.setQuery(f"model={QUrl.fromLocalFile(model).toString(QUrl.FullyEncoded)}"
                         f"&idle={QUrl.toPercentEncoding(character.idle_expression()).data().decode()}")
        else:
            print("⚠️ 没有找到 Live2D 模型：右键 → 系统配置 → 外观 里选一个 .model3.json")
        self.setUrl(url)
# ==========================================
# 3. 前台主界面
# ==========================================
class LogWindow(QWidget):
    """日志窗口：默认隐藏，右键菜单 / 功能面板里可以打开"""
    def __init__(self):
        super().__init__()
        self.setObjectName("window")
        self.setWindowTitle(f"{character.name()} · 运行日志")
        self.resize(560, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("📜 运行日志")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        clear = QPushButton("清空")
        clear.clicked.connect(lambda: self.text_area.clear())
        header.addWidget(clear)
        layout.addLayout(header)
        hint = QLabel("她在后台忙的事都记在这里，出问题时把相关的几行发给开发者就行。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.text_area = QTextEdit()
        self.text_area.setObjectName("code")
        self.text_area.setReadOnly(True)
        layout.addWidget(self.text_area, 1)

    def append_text(self, text):
        self.text_area.moveCursor(QTextCursor.MoveOperation.End)
        self.text_area.insertPlainText(text)
        if not text.endswith('\n'):
            self.text_area.insertPlainText('\n')
        self.text_area.moveCursor(QTextCursor.MoveOperation.End)


class SpeechBubble(QWidget):
    """她头顶的对话气泡：圆角卡片 + 指向她的小尾巴；内心独白是淡紫色的思考泡泡"""
    TAIL = 9
    PAD_X, PAD_Y = 14, 9

    def __init__(self, parent):
        super().__init__(parent)
        self.thought = False
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)  # 点气泡本身就能关掉
        theme.add_shadow(self, blur=16, alpha=45, dy=2)

    def text(self):
        return self.label.text()

    def set_message(self, text, thought=False, max_width=300):
        self.thought = thought
        self.label.setFont(theme.font(10, italic=thought))
        color = theme.P["thought_text"] if thought else theme.P["text"]
        self.label.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")
        self.label.setText(text)
        metrics = self.label.fontMetrics()
        longest = max((metrics.horizontalAdvance(line) for line in text.split("\n")), default=0)
        width = min(max_width, longest + self.PAD_X * 2 + 6)
        label_w = width - self.PAD_X * 2
        label_h = self.label.heightForWidth(label_w)
        self.label.setGeometry(self.PAD_X, self.PAD_Y, label_w, label_h)
        self.resize(width, label_h + self.PAD_Y * 2 + self.TAIL)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QRectF(1, 1, self.width() - 2, self.height() - self.TAIL - 2)
        cx = self.width() / 2
        if self.thought:
            fill, border = QColor(theme.P["thought_bg"]), QColor("#DCD2F5")
        else:
            fill, border = QColor(theme.P["surface"]), QColor(theme.P["border"])
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(fill)

        path = QPainterPath()
        path.addRoundedRect(body, 14, 14)
        if not self.thought:
            tail = QPainterPath()
            tail.moveTo(cx - 8, body.bottom() - 1)
            tail.lineTo(cx, self.height() - 1.5)
            tail.lineTo(cx + 8, body.bottom() - 1)
            tail.closeSubpath()
            path = path.united(tail)
        painter.drawPath(path)
        if self.thought:  # 思考泡泡下面的两个小圆点
            painter.drawEllipse(QPointF(cx - 10, body.bottom() + 4), 3.5, 3.5)
            painter.drawEllipse(QPointF(cx - 16, body.bottom() + 8), 2, 2)


class FeaturePanel(QWidget):
    """
    点模型旁边的 ✦ 小按钮弹出来的功能面板：分组列出她会的事，点一下就执行。
    sections: [(分组标题, [(图标, 名字, 说明, 点击后执行的函数), ...]), ...]
    """
    def __init__(self, sections, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        P = theme.P

        frame = QWidget(self)
        frame.setObjectName("panel")
        frame.setStyleSheet(f"""
            QWidget#panel {{ background-color: {P['surface']}; border: 1px solid {P['border']}; border-radius: 16px; }}
            QLabel#panelTitle {{ color: {P['primary_dark']}; font-size: 14px; font-weight: bold; padding: 0 2px 2px 2px; }}
            QLabel#panelHint {{ color: {P['muted']}; font-size: 11px; padding: 0 2px 4px 2px; }}
            QLabel#section {{ color: {P['muted']}; font-size: 11px; font-weight: bold; padding: 8px 2px 2px 2px; }}
            QPushButton {{ background-color: {P['surface_alt']}; color: {P['text']}; border: 1px solid transparent;
                          border-radius: 10px; padding: 8px 10px; text-align: left; font-size: 12px; }}
            QPushButton:hover {{ background-color: {P['primary_soft']}; border-color: {P['primary']}; }}
            QPushButton:pressed {{ background-color: #FFD3E5; }}
        """)
        theme.add_shadow(frame, blur=24, alpha=50, dy=4)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 14)  # 给阴影留位置
        outer.addWidget(frame)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(2)
        title = QLabel(f"✦ {character.name()}能帮你做这些")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        hint = QLabel("点一下就执行，鼠标停一会儿能看说明")
        hint.setObjectName("panelHint")
        layout.addWidget(hint)

        for section, items in sections:
            header = QLabel(section)
            header.setObjectName("section")
            layout.addWidget(header)
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, (icon, name, desc, handler) in enumerate(items):
                button = QPushButton(f"{icon}  {name}")
                button.setToolTip(desc)
                button.setCursor(Qt.PointingHandCursor)
                button.setMinimumWidth(132)
                button.clicked.connect(lambda _=False, h=handler: self._run(h))
                grid.addWidget(button, i // 2, i % 2)
            layout.addLayout(grid)

    def _run(self, handler):
        self.close()
        # 等面板先关掉再执行 (有的会弹输入框)
        QTimer.singleShot(0, handler)

    def popup_near(self, anchor_rect):
        """在桌宠旁边弹出：右边放不下就放左边，上下不出屏幕"""
        self.adjustSize()
        screen = QApplication.screenAt(anchor_rect.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = anchor_rect.right() - 4
        if x + self.width() > area.right():
            x = anchor_rect.left() - self.width() + 4
        y = anchor_rect.top() + 60
        y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
        self.move(max(area.left() + 4, x), y)
        self.show()


class MainWindow(QWidget):
    """桌宠主体：透明无边框，只露出角色、气泡和状态小标签"""
    PET_W = 320
    PET_H = 506
    FOOTER_H = 36       # 模型脚下单独一行：任务进度、专注倒计时、✦ 按钮 (放在模型上面会被模型挡住)
    BUBBLE_H = 110      # 顶部留给气泡的高度
    HEAD_RATIO = 0.42   # 角色区域上面这部分算"头"，点了是摸头

    POKE_LINES = ["呀！直播事故！", "嘿嘿，好痒~", "别闹啦~", "嗯？找我有事吗？", "再戳我要假装生气咯！", "麦克风测试，戳一下~"]
    POKE_EXPRESSIONS = ["4OAO", "5QAQ", "6i gi a ri", "8punch"]
    PAT_LINES = ["嘿嘿~", "被摸头了，开心！", "头发要被揉乱啦！", "(眯起眼睛)", "今天也要元气满满哦~"]
    DRAG_START_LINES = ["哇！要带我去哪~", "飞起来啦~", "换个机位直播吗？"]
    DRAG_END_LINES = ["这里视野不错~", "新机位get！", "好，就在这儿开播吧！"]
    IDLE_LINES = [("哈啊~有点无聊…", "1desk"), ("你在忙什么呀？", "4OAO"), ("(伸了个懒腰)", "3clever"),
                  ("要不要休息一下眼睛？", "3clever"), ("记得喝口水哦~", "2mic")]
    LONELY_LINES = [("好久没人陪我聊天了…", "5QAQ"), ("你今天会理我吗？", "5QAQ"), ("(偷偷看你一眼)", "1desk")]
    NIGHT_LINES = [("好困…zzZ", "5QAQ"), ("都这么晚了，还不睡吗…", "5QAQ"), ("(揉眼睛)", "1desk")]

    STATUS_COLORS = {"listening": theme.P["listening"], "recognizing": theme.P["thinking"], "thinking": theme.P["thinking"],
                     "acting": theme.P["acting"], "speaking": theme.P["acting"], "busy": theme.P["focus"]}
    STATUS_EXPRESSIONS = {"listening": "2mic", "recognizing": "1desk", "thinking": "1desk"}

    def __init__(self):
        super().__init__()
        theme.apply(QApplication.instance())  # 统一字体和配色 (菜单、对话框、输入框都会跟着变)
        self.settings = QSettings("EurekaAI", "DesktopPet")
        self.log_window = LogWindow()
        self.init_ui()
        self.init_tray()

        # 平滑追踪用的变量
        self.current_x = 0.0
        self.current_y = 0.0

        # 拖动相关
        self.press_pos = None
        self.dragging = False

        # 当前状态
        self.state = "busy"
        self.talking = False
        self.last_active = time.time()
        self.next_idle_after = random.uniform(240, 480)

        self.mouse_timer = QTimer(self)
        self.mouse_timer.timeout.connect(self.track_global_mouse)
        self.mouse_timer.start(30)

        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.bubble.hide)

        # 闲着没事时，隔一阵冒个泡
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.idle_tick)
        self.idle_timer.start(30000)

        # 日志：print 的内容进日志窗口
        self.redirector = StreamRedirector()
        self.redirector.text_written.connect(self.log_window.append_text)
        sys.stdout = self.redirector

        # 后台事件：气泡、表情、嘴型、状态
        self.event_bridge = EventBridge()
        self.event_bridge.event.connect(self.handle_event)

        self.thread = AssistantThread()
        self.thread.start()

    def init_ui(self):
        self.setWindowTitle(character.name())
        # 放了自己的 assets/icon_custom.ico (比如角色头像) 就用它，不进仓库
        custom_icon = os.path.join(main.get_app_path(), "assets", "icon_custom.ico")
        icon = custom_icon if os.path.exists(custom_icon) else get_resource_path(os.path.join("assets", "icon.ico"))
        self.setWindowIcon(QIcon(icon))
        # 无边框 + 置顶 + 不占任务栏
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.PET_W, self.PET_H)

        # Live2D 角色
        self.live2d_view = Live2DWidget()
        self.live2d_view.setParent(self)
        self.live2d_view.setGeometry(0, self.BUBBLE_H, self.PET_W, self.PET_H - self.BUBBLE_H - self.FOOTER_H)
        # 网页渲染层创建好后才能拿到它来接管鼠标
        self.live2d_view.loadFinished.connect(self.hook_live2d_mouse)

        # 对话气泡 (她说的话 / 内心独白)
        self.bubble = SpeechBubble(self)
        self.bubble.setCursor(Qt.PointingHandCursor)
        self.bubble.installEventFilter(self)
        self.bubble.hide()

        # 状态小标签 (只在不是待机时出现)
        self.status_label = self._make_chip()

        # ✦ 功能按钮 (在她右肩旁边，点开功能面板)
        self.feature_button = QPushButton("✦", self)
        self.feature_button.setToolTip(f"{character.name()}能帮你做的事")
        self.feature_button.setCursor(Qt.PointingHandCursor)
        self.feature_button.setFixedSize(34, 34)
        self.feature_button.setStyleSheet(f"""
            QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFA3CB, stop:1 {theme.P['primary']});
                          color: white; border: 2px solid white; border-radius: 17px; padding: 0;
                          font-size: 15px; font-weight: bold; }}
            QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFB8D6, stop:1 #FF85B6); }}
            QPushButton:pressed {{ background: {theme.P['primary_dark']}; }}
        """)
        theme.add_shadow(self.feature_button, blur=12, alpha=60, dy=2)
        self.feature_button.move(self.PET_W - 34 - 10, self.PET_H - self.FOOTER_H + 1)
        self.feature_button.clicked.connect(self.open_feature_panel)
        self.feature_panel = None

        # 今日任务进度 (左下角小标签，点一下看清单)
        self.task_label = self._make_chip()
        self.task_label.setCursor(Qt.PointingHandCursor)
        self.task_label.setToolTip("点一下看今天的任务清单")
        self.task_label.installEventFilter(self)
        self.task_label.hide()
        self.task_items = []

        # 专注 / 休息倒计时 (脚下，一直显示到结束)
        self.focus_label = self._make_chip()
        self.focus_end = None
        self.focus_kind = "focus"
        self.focus_task = ""
        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.update_focus_label)

        # 右键菜单 (托盘也共用)
        self.menu = QMenu()
        self.menu.setWindowFlags(self.menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.menu.setAttribute(Qt.WA_TranslucentBackground)  # 让圆角干净，不露出方角
        self.menu.addAction("🎤 唤醒 / 打断", self.on_interrupt_click)
        self.menu.addAction("⌨️ 打字跟她说", self.on_type_click)
        self.menu.addSeparator()
        self.action_observe = QAction("👀 观察我 (根据窗口主动搭话)", self.menu, checkable=True)
        self.action_observe.setChecked(main.OBSERVER_ENABLED)
        self.action_observe.toggled.connect(main.set_observer_enabled)
        self.menu.addAction(self.action_observe)
        self.action_dnd = QAction("🔕 免打扰 (不主动搭话)", self.menu, checkable=True)
        self.action_dnd.setChecked(main.load_settings().get("do_not_disturb", False))
        self.action_dnd.toggled.connect(main.set_do_not_disturb)
        self.menu.addAction(self.action_dnd)
        self.action_barge_in = QAction("🎧 允许插话打断 (戴耳机时开)", self.menu, checkable=True)
        self.action_barge_in.setChecked(main.load_settings().get("allow_barge_in", False))
        self.action_barge_in.toggled.connect(main.set_barge_in)
        self.menu.addAction(self.action_barge_in)
        self.action_on_top = QAction("📌 总在最前", self.menu, checkable=True)
        self.action_on_top.setChecked(True)
        self.action_on_top.toggled.connect(self.toggle_on_top)
        self.menu.addAction(self.action_on_top)
        self.action_visible = QAction("🙈 藏起来", self.menu)
        self.action_visible.triggered.connect(self.toggle_visible)
        self.menu.addAction(self.action_visible)
        self.menu.addSeparator()
        self.menu.addAction("💗 我们的关系", lambda: self.show_bubble(main.relationship_summary(), 8000))
        self.menu.addAction("📜 查看日志", self.show_log_window)
        self.menu.addAction("⚙️ 系统配置", self.on_settings_click)
        self.menu.addAction("📝 注册成员", self.open_register_dialog)
        self.menu.addSeparator()
        self.menu.addAction("❌ 退出", self.quit_app)

        # 恢复上次位置，没有就放到屏幕右下角
        area = QApplication.primaryScreen().availableGeometry()
        saved = self.settings.value("pos")
        if isinstance(saved, QPoint) and QApplication.screenAt(saved + QPoint(self.PET_W // 2, self.PET_H // 2)):
            self.move(saved)
        else:
            self.move(area.right() - self.PET_W - 20, area.bottom() - self.PET_H)

    def init_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(character.name())
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    # ---------------- 后台事件 ----------------
    def handle_event(self, kind, data):
        if kind == "status":
            self.update_status(data["text"], data["state"])
        elif kind == "say":
            self.log_window.append_text(f"💬 {data['text']}")
            self.show_bubble(data["text"])
        elif kind == "thought":
            self.show_bubble(f"💭 {data['text']}", 5000, thought=True)
        elif kind == "expression":
            self.set_expression(data["name"])
        elif kind == "lipsync":
            self.talking = True
            self.status_label.hide()  # 开口说话了，"思考中"之类的标签就收起来
            self.run_js(f"window.playLipSync({json.dumps(data['envelope'])}, {data['frame_ms']});")
        elif kind == "speak_end":
            self.talking = False
            self.run_js("window.stopTalking();")
        elif kind == "problem":
            # 出错 / 用量提醒：她用一句人话说出来
            if data.get("category") != "notice":
                self.set_expression("5QAQ")
            self.show_bubble(data["text"], 9000)
        elif kind == "tasks":
            self.update_task_label(data.get("items") or [])
        elif kind == "focus":
            self.focus_end, self.focus_kind, self.focus_task = data["end"], data.get("mode", "focus"), data.get("task", "")
            self.update_focus_label()
            self.focus_timer.start(1000)
        elif kind == "focus_end":
            self.focus_end = None
            self.focus_timer.stop()
            self.focus_label.hide()

        if not (kind == "status" and data.get("state") == "idle"):
            self.last_active = time.time()

    def update_status(self, text, state):
        self.state = state
        if state == "idle":
            # 待机时不打扰，收起状态标签
            self.status_label.hide()
            return
        self.set_status_pill(text, self.STATUS_COLORS.get(state, theme.P["focus"]))
        if state in self.STATUS_EXPRESSIONS and not self.talking:
            self.set_expression(self.STATUS_EXPRESSIONS[state])

    def _make_chip(self):
        """桌宠身边的小标签：白底圆角 + 前面一个彩色小圆点"""
        chip = QLabel(self)
        chip.setTextFormat(Qt.RichText)
        chip.setAlignment(Qt.AlignCenter)
        chip.setFont(theme.font(9))
        chip.setStyleSheet(theme.chip_style())
        theme.add_shadow(chip, blur=10, alpha=35, dy=1)
        chip.hide()
        return chip

    def set_status_pill(self, text, color):
        # 状态文字前面原本带的表情符号去掉，用小圆点的颜色区分状态
        text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text).strip()
        self.status_label.setText(theme.chip_text(text, color))
        self.status_label.adjustSize()
        w = min(self.PET_W - 20, self.status_label.width())
        # 放在气泡区和角色之间，不挡住脚下的桌子
        self.status_label.setGeometry((self.PET_W - w) // 2, self.BUBBLE_H + 52, w, self.status_label.height())
        self.status_label.show()
        self.status_label.raise_()

    # ---------------- 鼠标交互 ----------------
    def hook_live2d_mouse(self, ok):
        if not self.live2d_view.has_model and not getattr(self, "_model_hint_shown", False):
            self._model_hint_shown = True
            self.show_bubble("还没有 Live2D 形象哦~\n右键 → 系统配置 → 外观与角色 里选一个模型吧", 12000)
        proxy = self.live2d_view.focusProxy()
        if proxy and not getattr(self, "_mouse_hooked", False):
            proxy.installEventFilter(self)
            self._mouse_hooked = True

    def eventFilter(self, obj, event):
        et = event.type()
        if obj is getattr(self, "task_label", None):  # 界面还没建完时也会进来
            if et == QEvent.MouseButtonRelease:
                self.show_task_list()
                return True
            return False

        if obj is self.bubble:
            if et == QEvent.MouseButtonRelease:
                self.bubble.hide()
                return True
            return False

        if et == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.press_pos = event.globalPosition().toPoint()
                self.press_local = event.position().toPoint()
                self.win_start = self.pos()
                self.dragging = False
            elif event.button() == Qt.RightButton:
                self.menu.popup(event.globalPosition().toPoint())
            return True

        if et == QEvent.MouseMove and self.press_pos is not None:
            delta = event.globalPosition().toPoint() - self.press_pos
            if not self.dragging and delta.manhattanLength() > 4:
                self.dragging = True
                self.react(random.choice(self.DRAG_START_LINES), "4OAO", 1500)
            if self.dragging:
                self.move(self.win_start + delta)
            return True

        if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self.dragging:
                self.settings.setValue("pos", self.pos())
                self.react(random.choice(self.DRAG_END_LINES), "3clever", 2000)
            elif self.press_pos is not None:
                if self.press_local.y() < self.live2d_view.height() * self.HEAD_RATIO:
                    self.react(random.choice(self.PAT_LINES), "3clever")
                    main.on_pet_touch("pat")
                else:
                    self.react(random.choice(self.POKE_LINES), random.choice(self.POKE_EXPRESSIONS))
                    main.on_pet_touch("poke")
            self.press_pos = None
            self.dragging = False
            return True

        if et == QEvent.MouseButtonDblClick:
            self.on_interrupt_click()
            return True

        if et in (QEvent.ContextMenu, QEvent.Wheel):
            return True
        return False

    def react(self, line, expression, duration=2500):
        """对摸头/戳/拖动的小反应；她正在说话时只换表情，不抢气泡"""
        self.last_active = time.time()
        self.set_expression(expression)
        if not self.talking:
            self.show_bubble(line, duration)

    def update_task_label(self, items):
        self.task_items = items
        if not items:
            self.task_label.hide()
            return
        done = sum(t["done"] for t in items)
        all_done = done == len(items)
        text = "任务全部完成 🎉" if all_done else f"任务 {done}/{len(items)}"
        color = theme.P["done"] if all_done else theme.P["tasks"]
        self.task_label.setText(theme.chip_text(text, color))
        self.task_label.adjustSize()
        self.task_label.move(10, self.PET_H - self.FOOTER_H + (self.FOOTER_H - self.task_label.height()) // 2)
        self.task_label.show()
        self.task_label.raise_()
        self.update_focus_label()  # 任务标签宽度变了，倒计时的位置也跟着挪

    def show_task_list(self):
        if not self.task_items:
            return
        lines = "\n".join(f"{'✅' if t['done'] else '⬜'} {t['text']}" for t in self.task_items)
        self.show_bubble(f"今天的任务：\n{lines}", 8000)

    def update_focus_label(self):
        if not self.focus_end:
            return
        left = max(0, int(self.focus_end - time.time()))
        # 绿点 = 专注 (有任务名就只显示任务名)，黄点 = 休息
        if self.focus_kind == "focus":
            name = (self.focus_task if len(self.focus_task) <= 6 else self.focus_task[:6] + "…") or "专注中"
        else:
            name = "休息中"
        color = theme.P["focus"] if self.focus_kind == "focus" else theme.P["break"]
        self.focus_label.setText(theme.chip_text(f"{name}&nbsp;<b>{left // 60:02d}:{left % 60:02d}</b>", color))
        self.focus_label.setToolTip(f"专注中：{self.focus_task}" if self.focus_kind == "focus" and self.focus_task else "")
        self.focus_label.adjustSize()
        # 放在脚下一行的中间：左边让开任务标签，右边让开 ✦ 按钮
        left = self.task_label.geometry().right() + 8 if self.task_label.isVisible() else 10
        right = self.feature_button.x() - 8
        w = min(right - left, self.focus_label.width())
        x = max(left, min((self.PET_W - w) // 2, right - w))
        self.focus_label.setGeometry(x, self.PET_H - self.FOOTER_H + (self.FOOTER_H - self.focus_label.height()) // 2,
                                     w, self.focus_label.height())
        self.focus_label.show()
        self.focus_label.raise_()

    def idle_tick(self):
        """闲着太久就自己找点事：打哈欠、提醒喝水，深夜犯困 (免打扰、专注时不吭声)"""
        if self.state != "idle" or self.talking or not self.isVisible():
            return
        if self.focus_end or main.companion.do_not_disturb:
            return
        if time.time() - self.last_active < self.next_idle_after:
            return
        # 跟着她当下的状态：困了打瞌睡，好久没人理就有点委屈，平时随便找点事
        mood, energy = main.life_state()
        hour = time.localtime().tm_hour
        if energy < 40 or hour >= 23 or hour < 6:
            pool = self.NIGHT_LINES
        elif mood < 45:
            pool = self.LONELY_LINES
        else:
            pool = self.IDLE_LINES
        line, expression = random.choice(pool)
        self.react(line, expression, 4000)
        self.next_idle_after = random.uniform(240, 480)

    # ---------------- 气泡 ----------------
    def show_bubble(self, text, duration=None, thought=False):
        # 根据文字多少自适应大小，小尾巴指着她的头 (模型上方本身有一截空白，往下压一点)
        self.bubble.set_message(text, thought, max_width=self.PET_W - 16)
        bottom = self.BUBBLE_H + 58
        self.bubble.move((self.PET_W - self.bubble.width()) // 2, max(0, bottom - self.bubble.height()))
        self.bubble.show()
        self.bubble.raise_()

        if duration is None:
            duration = min(15000, max(4000, len(text) * 250))
        self.bubble_timer.start(duration)

    # ---------------- 菜单动作 ----------------
    def on_interrupt_click(self):
        print(">>> 🔘 手动唤醒/中断...")
        main.force_stop_everything()

    # ---------------- 功能面板 ----------------
    def feature_sections(self):
        """功能面板里列出来的东西；想加功能，往这里加一行就行"""
        dnd = self.action_dnd.isChecked()
        return [
            ("💬 聊天", [
                ("🎤", "跟她说话", "唤醒她，直接开口说", self.on_interrupt_click),
                ("⌨️", "打字跟她说", "不方便说话时打字", self.on_type_click),
            ]),
            ("📋 任务和专注", [
                ("📋", "今日任务", "看看今天的任务清单", self.show_task_list_or_hint),
                ("➕", "添加任务", "把今天要做的事记进清单", self.feature_add_tasks),
                ("⏱️", "开始专注", "她安静陪着，脚下显示倒计时", self.feature_start_focus),
                ("⏹️", "结束专注", "提前结束这一轮专注", self.feature_stop_focus),
                ("📊", "收工回顾", "她帮你总结今天做了什么", lambda: self.ask_eureka("帮我做个今天的收工回顾吧")),
                ("💻", "今天干了啥", "今天的任务进度和电脑使用时长", lambda: self.show_bubble(main.today_summary(), 9000)),
            ]),
            ("🎵 生活和工具", [
                ("🎵", "放首歌", "让她给你放音乐", lambda: self.ask_eureka("随便放首歌给我听吧")),
                ("🌤️", "今天天气", "查一下今天的天气", lambda: self.ask_eureka("今天天气怎么样？")),
                ("👀", "看看屏幕", "让她看你的屏幕，帮你解释报错之类", self.feature_look_screen),
                ("🔍", "帮我搜一下", "联网搜索后讲给你听", self.feature_search),
                ("📝", "记个备忘", "记到桌面的 memo.txt", self.feature_note),
                ("⏰", "提醒我", "过一会儿提醒你一件事", self.feature_timer),
            ]),
            ("💗 我们", [
                ("💗", "我们的关系", "认识多少天、现在的关系、她此刻在干嘛", lambda: self.show_bubble(main.relationship_summary(), 8000)),
                ("🔕" if not dnd else "🔔", "关闭免打扰" if dnd else "开启免打扰", "开着时她不会主动搭话", self.feature_toggle_dnd),
                ("⚙️", "系统配置", "软件路径、记忆、听觉、早报等设置", self.on_settings_click),
                ("📜", "查看日志", "看看她后台在忙什么", self.show_log_window),
            ]),
        ]

    def open_feature_panel(self):
        self.feature_panel = FeaturePanel(self.feature_sections())
        self.feature_panel.popup_near(self.frameGeometry())

    def ask_eureka(self, text):
        """面板上需要她动脑子的功能：替你说一句话给她，和你自己开口说一样处理"""
        print(f">>> ✦ {text}")
        self.show_bubble("收到~", 1500)
        main.submit_text(text)

    def _ask_text(self, title, prompt, default=""):
        text, ok = QInputDialog.getText(self, title, prompt, text=default)
        return text.strip() if ok else ""

    def show_task_list_or_hint(self):
        if self.task_items:
            self.show_task_list()
        else:
            self.show_bubble("今天还没列任务哦~点「添加任务」告诉我吧", 4000)

    def feature_add_tasks(self):
        text = self._ask_text("添加任务", "今天要做什么？（多件事用顿号或逗号隔开）")
        items = [t.strip() for t in re.split(r"[、，,；;\n]+", text) if t.strip()]
        if items:
            added = main.add_tasks(items)
            self.react("记下啦！加油~" if added else "这些已经在清单里啦", "3clever", 2500)

    def feature_start_focus(self):
        minutes, ok = QInputDialog.getInt(self, "开始专注", "专注多少分钟？", 25, 1, 180)
        if not ok:
            return
        unfinished = [t["text"] for t in self.task_items if not t["done"]]
        task = self._ask_text("开始专注", "这轮要做哪件事？（可以不填）", unfinished[0] if unfinished else "")
        main.start_focus(minutes, task)
        self.react("好，我安静陪着你！", "1desk", 2500)

    def feature_stop_focus(self):
        if main.stop_focus():
            self.react("辛苦啦，先歇会儿吧~", "3clever", 2500)
        else:
            self.show_bubble("现在没有在专注哦", 2500)

    def feature_toggle_dnd(self):
        self.action_dnd.toggle()
        if self.action_dnd.isChecked():
            self.react("好~我先安静陪着，不打扰你", "1desk", 3000)
        else:
            self.react("我回来啦！有事随时叫我~", "3clever", 3000)

    def feature_look_screen(self):
        if not main.load_settings().get("allow_screen", True):
            self.show_bubble("「看看屏幕」在隐私设置里关掉啦~\n右键 → 系统配置 → 隐私 里可以打开", 5000)
            return
        question = self._ask_text("看看屏幕", "想让她看什么？", "看看我屏幕上是什么")
        if question:
            self.ask_eureka(f"看看我的屏幕：{question}")

    def feature_search(self):
        query = self._ask_text("帮我搜一下", "想搜什么？")
        if query:
            self.ask_eureka(f"帮我联网搜一下：{query}")

    def feature_note(self):
        note = self._ask_text("记个备忘", "要记什么？")
        if note:
            self.ask_eureka(f"帮我记一下备忘：{note}")

    def feature_timer(self):
        text = self._ask_text("提醒我", "多久后提醒你什么？", "10分钟后提醒我起来喝水")
        if text:
            self.ask_eureka(text)

    def on_type_click(self):
        text, ok = QInputDialog.getText(self, f"跟{character.name()}说", "想说点什么？")
        if ok and text.strip():
            print(f">>> ⌨️ {text.strip()}")
            main.submit_text(text)

    def on_settings_click(self):
        dialog = ConfigDialog(self)
        dialog.exec()

    def show_log_window(self):
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def toggle_on_top(self, on):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
            self.action_visible.setText("👀 出来吧")
        else:
            self.show()
            self.action_visible.setText("🙈 藏起来")

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visible()

    def quit_app(self):
        self.settings.setValue("pos", self.pos())
        self.tray.hide()
        sys.stdout = sys.__stdout__
        # 语音线程是阻塞循环，直接结束进程最干净
        os._exit(0)

    def closeEvent(self, event):
        self.quit_app()

    # ---------------- Live2D ----------------
    def run_js(self, code):
        self.live2d_view.page().runJavaScript(code)

    def track_global_mouse(self):
        """眼睛跟着鼠标转 (以桌宠头部为中心)"""
        try:
            screen = QApplication.primaryScreen().size()
            cursor_pos = QCursor.pos()

            head = self.mapToGlobal(QPoint(self.PET_W // 2, self.BUBBLE_H + 120))
            target_x = (cursor_pos.x() - head.x()) / (screen.width() / 2)
            target_y = -(cursor_pos.y() - head.y()) / (screen.height() / 2)

            # 灵敏度放大，再限制在 -1 ~ 1
            AMPLIFY = 1.5
            target_x = max(-1.0, min(1.0, target_x * AMPLIFY))
            target_y = max(-1.0, min(1.0, target_y * AMPLIFY))

            SMOOTH_FACTOR = 0.12
            self.current_x += (target_x - self.current_x) * SMOOTH_FACTOR
            self.current_y += (target_y - self.current_y) * SMOOTH_FACTOR

            self.run_js(f"if(window.updateFocus) window.updateFocus({self.current_x:.3f}, {self.current_y:.3f});")
        except Exception:
            pass

    def set_expression(self, exp_name):
        # 程序里的表情代号 → 当前模型里的表情名 (character.json 的 expression_map)
        self.run_js(f'window.setExpression({json.dumps(character.model_expression(exp_name))}, null, {json.dumps(exp_name)});')

    def open_register_dialog(self):
        dialog = RegisterUserDialog(self)
        dialog.exec()


class RegisterUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{character.name()} · 登记新成员")
        self.resize(460, 470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel("📝 登记新成员")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        intro = QLabel("填好资料、录一段声音，她就能听出是谁在跟她说话，并记住你的喜好。")
        intro.setObjectName("pageDesc")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        form_layout = QFormLayout(card)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # 1. 表单控件
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：张三")
        
        self.birthday_input = QLineEdit()
        self.birthday_input.setPlaceholderText("例如：05-20 (月-日)")
        
        self.pref_input = QLineEdit()
        self.pref_input.setPlaceholderText("例如：喜欢吃草莓，讨厌香菜")
        
        self.tone_combo = QComboBox()
        self.tone_combo.addItems(["温柔贴心", "傲娇毒舌", "高冷专业", "元气满满", "沙雕欢乐"])
        
        self.roast_checkbox = QCheckBox(f"允许{character.name()}偶尔开开玩笑吗？")
        self.roast_checkbox.setChecked(True)
        
        # 2. 组装表单
        form_layout.addRow("名字", self.name_input)
        form_layout.addRow("生日", self.birthday_input)
        form_layout.addRow("喜好与禁忌", self.pref_input)
        form_layout.addRow("对你的态度", self.tone_combo)
        form_layout.addRow("", self.roast_checkbox)

        layout.addWidget(card)
        
        # 👇👇👇 [新增] 一块专门用来显示台词的提词器屏幕
        self.script_label = QLabel("")
        self.script_label.setWordWrap(True) # 允许自动换行
        self.script_label.setObjectName("prompter")
        self.script_label.hide() # 刚打开窗口时先隐藏
        layout.addWidget(self.script_label)

        # 3. 核心按钮
        layout.addStretch()
        self.record_btn = QPushButton("🎤 填好了，开始录声音")
        self.record_btn.setProperty("primary", True)
        self.record_btn.setMinimumHeight(40)
        self.record_btn.clicked.connect(self.start_registration)
        layout.addWidget(self.record_btn)
        
    def _set_recording(self, on):
        """录音时按钮变红；换样式要让 Qt 重新套一次样式表"""
        self.record_btn.setProperty("recording", on)
        self.record_btn.setProperty("primary", not on)
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)

    def start_registration(self):
        name = self.name_input.text().strip()
        birthday = self.birthday_input.text().strip()
        pref = self.pref_input.text().strip()
        tone = self.tone_combo.currentText()
        allow_roast = self.roast_checkbox.isChecked()
        
        if not name:
            QMessageBox.warning(self, "提示", "必须先填写姓名哦！")
            return
            
        # 1. 为用户生成专属台词
        script_text = f"我现在正用平时最习惯的语速和音量在说话，请仔细分析这段音频里的声学特征，帮我建立好专属的个人档案。"
        
        # 2. 激活提词器，把台词贴在窗口上！
        self.script_label.setText(f"📜 请朗读：\n\n「{script_text}」")
        self.script_label.show()
        
        # 3. 弹窗提示准备（简化文案）
        QMessageBox.information(
            self, 
            "准备录音", 
            "准备好了吗？\n\n点【确定】后，请看着窗口上粉色框里的句子，用平时的语速大声读出来~"
        )
        
        # 4. 改变按钮状态
        self.record_btn.setText("● 正在录音…请读上面的句子")
        self._set_recording(True)
        self.record_btn.setEnabled(False)
        QApplication.processEvents() # 强制刷新 UI 避免卡死
        
        try:
            import recorder
            import main as main_logic
            import ai_brain
            from voiceprint import vp_manager
            
            # 1. 借用现有的录音模块（会存为 input.wav）
            success = recorder.record_audio(threshold=500) 
            
            if not success:
                QMessageBox.warning(self, "失败", "没听清你的声音，录入失败了，请重试。")
            else:
                # 2. 把刚录好的 input.wav 复制并重命名为 专属声纹特征音频
                base_wav_path = os.path.join(main_logic.get_app_path(), f"{name}_base.wav")
                shutil.copy(os.path.join(main_logic.get_app_path(), "input.wav"), base_wav_path)
                
                # 3. 提取声纹特征 (存入 voice_profiles 文件夹)
                vp_manager.enroll_user(name, base_wav_path)
                
                # 4. 写入记忆大模型档案库
                ai_brain.add_new_owner(name, birthday, pref, tone, allow_roast)
                
                QMessageBox.information(self, "🎉 注册成功", f"太棒了！{character.name()}已经记住了【{name}】的声音和喜好！\n下次你叫她，她就能听出是你啦！")
                self.accept() # 关闭窗口
                
        except Exception as e:
            QMessageBox.warning(self, "系统报错", f"发生错误：{str(e)}")
            
        finally:
            self.record_btn.setText("🎤 重新录一次")
            self._set_recording(False)
            self.record_btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 藏到托盘时不退出
    theme.apply(app)

    # 只允许开一个：两个会抢麦克风、互相覆盖记忆和状态文件
    from PySide6.QtCore import QLockFile, QDir
    instance_lock = QLockFile(QDir.temp().absoluteFilePath("eureka_desktop_pet.lock"))
    instance_lock.setStaleLockTime(0)  # 上次崩溃留下的锁会自动判断进程已不在
    if not instance_lock.tryLock(200):
        QMessageBox.information(None, character.name(), f"{character.name()}已经在桌面上啦~\n找不到的话看看右下角托盘图标。")
        sys.exit(0)

    # 第一次打开 (还没填 Key)：先走一遍引导，设置好后重启让配置生效
    if setup_ui.needs_setup():
        wizard = setup_ui.SetupWizard()
        if wizard.exec() == QDialog.Accepted:
            instance_lock.unlock()
            from PySide6.QtCore import QProcess
            QProcess.startDetached(sys.executable, sys.argv)
            sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())