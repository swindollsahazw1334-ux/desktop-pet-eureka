"""
首次启动引导 + 设置里的 "账号与模型"、"隐私" 两页

    AccountForm   填百炼 Key、模型名、音色，能一键测试连接；保存到 .env
    PrivacyForm   观察我 / 电脑使用统计 / 看屏幕 三个开关，并说明哪些数据留在本机、哪些发到云端
    SetupWizard   第一次打开时的 5 步引导 (欢迎 → 连接大脑 → 隐私 → 形象 → 完成)
"""
import json
import os
import sys
import threading

from dotenv import load_dotenv, set_key
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

import character


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


ENV_FILE = os.path.join(get_app_path(), ".env")
SETTINGS_FILE = os.path.join(get_app_path(), "settings.json")
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OMNI_VOICES = ["Tina", "Momo", "Roya", "Cici", "Ono Anna", "Qiao", "Angel", "Serena"]


# ---------------- 读写配置 ----------------
def env_value(name, default=""):
    load_dotenv(ENV_FILE, override=True)
    value = (os.getenv(name) or "").strip()
    return default if not value or value.startswith("#") else value


def save_env(values):
    if not os.path.exists(ENV_FILE):
        open(ENV_FILE, "w", encoding="utf-8").close()
    for key, value in values.items():
        if value is not None:
            set_key(ENV_FILE, key, value, quote_mode="never")


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(updates):
    settings = load_settings()
    settings.update(updates)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)


def needs_setup():
    """第一次打开、或者还没填 Key 时需要引导"""
    return not load_settings().get("setup_done") and not env_value("VOLC_API_KEY")


# ---------------- 连接测试 (后台线程跑，不卡界面) ----------------
def test_brain(key, base_url, model):
    import notify
    from openai import OpenAI
    try:
        client = OpenAI(api_key=key, base_url=base_url or DASHSCOPE_URL, timeout=15)
        client.chat.completions.create(model=model, messages=[{"role": "user", "content": "你好"}], max_tokens=5)
        return True, f"大脑连上了 ✓ ({model})"
    except Exception as e:
        _, message = notify.classify(e)
        return False, message or f"连接失败：{str(e)[:120]}"


def test_omni(key, url, model):
    import websocket
    import notify
    url = url or "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    try:
        ws = websocket.create_connection(f"{url}?model={model}", header=[f"Authorization: Bearer {key}"], timeout=10)
        first = json.loads(ws.recv())
        ws.close()
        if first.get("type") == "session.created":
            return True, "实时语音连上了 ✓"
        return False, f"实时语音没建立会话：{str(first)[:120]}"
    except Exception as e:
        _, message = notify.classify(e)
        return False, message or f"实时语音连接失败：{str(e)[:120]}"


def _join_results(*messages):
    """两项测试的结果合成一段：同样的话只说一次，去掉 "右键 → 系统配置" 这种在这里用不上的指引"""
    lines = []
    for m in messages:
        if "✓" not in m:
            m = m.split("…右键")[0]
        if m not in lines:
            lines.append(m)
    return "\n".join(lines)


class _Relay(QObject):
    done = Signal(str, bool)


# ---------------- 小部件 ----------------
def _card(title, desc=""):
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


def _row(label, widget):
    row = QHBoxLayout()
    name = QLabel(label)
    name.setMinimumWidth(88)
    row.addWidget(name)
    row.addWidget(widget, 1)
    return row


class AccountForm(QWidget):
    """百炼 Key、模型和音色；测试连接；保存进 .env"""
    def __init__(self, compact=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card, box = _card("百炼 API Key", "在阿里云百炼控制台「API-KEY 管理」里创建一个，复制过来。只保存在本机的 .env 文件里。")
        key_row = QHBoxLayout()
        self.key = QLineEdit(env_value("VOLC_API_KEY"))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-...")
        show = QPushButton("显示")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("隐藏" if on else "显示")))
        key_row.addWidget(self.key, 1)
        key_row.addWidget(show)
        box.addLayout(key_row)
        layout.addWidget(card)

        card, box = _card("模型", "默认全部用千问。脑子负责聊天和调用工具，眼睛负责看屏幕，实时语音负责连续聊天和说话。")
        self.chat_model = QLineEdit(env_value("VOLC_MODEL_NAME", "qwen-plus"))
        self.vision_model = QLineEdit(env_value("VOLC_VISION_MODEL_NAME", "qwen-vl-max"))
        self.omni_model = QLineEdit(env_value("OMNI_MODEL", "qwen3.8-omni-flash-realtime"))
        self.voice = QComboBox()
        self.voice.setEditable(True)
        self.voice.addItems(OMNI_VOICES)
        self.voice.setCurrentText(env_value("OMNI_VOICE", "Tina"))
        box.addLayout(_row("脑子", self.chat_model))
        box.addLayout(_row("眼睛", self.vision_model))
        box.addLayout(_row("实时语音", self.omni_model))
        box.addLayout(_row("音色", self.voice))
        voice_hint = QLabel("音色要选实时和非实时模型都有的 (Tina / Momo / Roya)，才能全程一个声音。")
        voice_hint.setObjectName("hint")
        voice_hint.setWordWrap(True)
        box.addWidget(voice_hint)
        layout.addWidget(card)

        if not compact:
            card, box = _card("高级", "一般不用改。实时语音连不上时，可以换成带工作空间 ID 的地址。")
            self.base_url = QLineEdit(env_value("VOLC_BASE_URL", DASHSCOPE_URL))
            self.omni_url = QLineEdit(env_value("OMNI_URL", ""))
            self.omni_url.setPlaceholderText("wss://你的工作空间ID.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime")
            self.omni_limit = QSpinBox()
            self.omni_limit.setRange(0, 1440)
            self.omni_limit.setSuffix(" 分钟/天")
            self.omni_limit.setValue(int(load_settings().get("daily_omni_minutes", 60)))
            box.addLayout(_row("接口地址", self.base_url))
            box.addLayout(_row("实时地址", self.omni_url))
            box.addLayout(_row("用量提醒", self.omni_limit))
            limit_hint = QLabel("实时语音按时长收费，当天聊天超过这个时长会提醒一次；填 0 不提醒。")
            limit_hint.setObjectName("hint")
            box.addWidget(limit_hint)
            layout.addWidget(card)
        else:
            self.base_url = self.omni_url = self.omni_limit = None

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.run_test)
        self.result = QLabel("")
        self.result.setObjectName("hint")
        self.result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.result, 1)
        layout.addLayout(test_row)

        self._relay = _Relay()
        self._relay.done.connect(self._show_result)

    def run_test(self):
        key = self.key.text().strip()
        if not key:
            self._show_result("先填上 API Key 哦", False)
            return
        self.test_btn.setEnabled(False)
        self.result.setText("测试中…")
        base = self.base_url.text().strip() if self.base_url else env_value("VOLC_BASE_URL", DASHSCOPE_URL)
        omni_url = self.omni_url.text().strip() if self.omni_url else env_value("OMNI_URL", "")

        def work():
            ok1, msg1 = test_brain(key, base, self.chat_model.text().strip())
            ok2, msg2 = test_omni(key, omni_url, self.omni_model.text().strip())
            self._relay.done.emit(_join_results(msg1, msg2), ok1 and ok2)
        threading.Thread(target=work, daemon=True).start()

    def _show_result(self, text, ok):
        self.test_btn.setEnabled(True)
        color = "#2EB67D" if ok else "#E2558F"
        self.result.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.result.setText(text)

    def save(self):
        values = {
            "VOLC_API_KEY": self.key.text().strip(),
            "VOLC_MODEL_NAME": self.chat_model.text().strip() or "qwen-plus",
            "VOLC_VISION_MODEL_NAME": self.vision_model.text().strip() or "qwen-vl-max",
            "OMNI_MODEL": self.omni_model.text().strip() or "qwen3.8-omni-flash-realtime",
            "OMNI_VOICE": self.voice.currentText().strip() or "Tina",
            "VOLC_BASE_URL": (self.base_url.text().strip() if self.base_url else "") or env_value("VOLC_BASE_URL", DASHSCOPE_URL),
        }
        if self.omni_url is not None:
            values["OMNI_URL"] = self.omni_url.text().strip() or None
        save_env({k: v for k, v in values.items() if v})
        if self.omni_limit is not None:
            save_settings({"daily_omni_minutes": self.omni_limit.value()})


class PrivacyForm(QWidget):
    """三个隐私开关 + 数据去向说明"""
    def __init__(self):
        super().__init__()
        settings = load_settings()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card, box = _card("她能看到什么", "都可以随时在这里关掉。")
        self.activity = QCheckBox("统计电脑使用时长 (每 5 秒看一眼当前窗口的程序名和标题，不截屏)")
        self.activity.setChecked(settings.get("enable_activity", True))
        self.observer = QCheckBox("观察我：根据你在做什么主动提醒 (摸鱼、熬夜、太累)")
        self.observer.setChecked(settings.get("enable_observer", True))
        self.screen = QCheckBox("允许「看看屏幕」：你让她看时，把当前屏幕截图发给云端看图模型，看完立刻删掉")
        self.screen.setChecked(settings.get("allow_screen", True))
        for cb in (self.activity, self.observer, self.screen):
            box.addWidget(cb)
        self.activity.toggled.connect(lambda on: (self.observer.setEnabled(on), on or self.observer.setChecked(False)))
        self.observer.setEnabled(self.activity.isChecked())
        layout.addWidget(card)

        card, box = _card("数据去哪了")
        for line in (
            "🏠 只在本机：记忆库、聊天记录、任务清单、电脑使用统计、心情和关系、声纹、API Key",
            "☁️ 发到阿里云百炼：你说的话和她的回复 (用来思考和说话)、实时语音的音频、你主动让她看的屏幕截图",
            "🚫 不会做：不会偷偷截屏、不会上传你的文件、不会把数据发给除百炼以外的地方",
        ):
            label = QLabel(line)
            label.setObjectName("hint")
            label.setWordWrap(True)
            box.addWidget(label)
        folder = QPushButton("打开数据文件夹")
        folder.clicked.connect(lambda: os.startfile(get_app_path()))
        box.addWidget(folder, 0, Qt.AlignLeft)
        layout.addWidget(card)

    def save(self):
        save_settings({"enable_activity": self.activity.isChecked(),
                       "enable_observer": self.observer.isChecked() and self.activity.isChecked(),
                       "allow_screen": self.screen.isChecked()})


class SetupWizard(QDialog):
    """第一次打开时的引导"""
    def __init__(self):
        super().__init__()
        name = character.name()
        self.setWindowTitle(f"{name} · 欢迎")
        self.resize(640, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        self.steps = QStackedWidget()
        self.titles = []

        # 1. 欢迎
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        for text, obj in ((f"你好呀，我是{name}~", "pageTitle"),
                          ("我会住在你的桌面角落：陪你聊天、记住你说过的事、提醒你休息、陪你专注工作。\n"
                           "接下来花一分钟做几个设置就好。", "pageDesc")):
            label = QLabel(text)
            label.setObjectName(obj)
            label.setWordWrap(True)
            box.addWidget(label)
        card, cbox = _card("开始之前",
                           "我的大脑和声音用的是阿里云百炼 (千问) 的服务，需要你自己的 API Key，会按用量收费。"
                           "记忆、任务这些都只存在你的电脑上。下一步之后可以选择我能看到哪些东西。")
        box.addWidget(card)
        box.addStretch()
        self._add(page, "欢迎")

        # 2. 连接大脑
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.account = AccountForm(compact=True)
        box.addWidget(self.account)
        box.addStretch()
        self._add(page, "连接大脑")

        # 3. 隐私
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.privacy = PrivacyForm()
        box.addWidget(self.privacy)
        box.addStretch()
        self._add(page, "隐私")

        # 4. 形象
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        card, cbox = _card("Live2D 形象", "选一个 .model3.json 文件 (请使用你有权使用的模型)。不选也行，之后在 设置 → 外观与角色 里再选。")
        row = QHBoxLayout()
        self.model = QLineEdit(character.current.get("live2d_model", ""))
        self.model.setPlaceholderText(character.model_path() or "还没有选模型")
        browse = QPushButton("选择…")
        browse.clicked.connect(self._choose_model)
        row.addWidget(self.model, 1)
        row.addWidget(browse)
        cbox.addLayout(row)
        box.addWidget(card)
        box.addStretch()
        self._add(page, "形象")

        # 5. 完成
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        card, cbox = _card("都好啦！", "")
        for line in (f"🎤 喊「{' / '.join(character.wake_word_names())}」或者双击我，就能跟我说话",
                     "✦ 点我脚边的小按钮，能看到我会的所有事",
                     "🖱️ 拖动可以把我挪到别处；右键有更多设置",
                     "点「开始」后我会重启一下，让设置生效~"):
            label = QLabel(line)
            label.setWordWrap(True)
            cbox.addWidget(label)
        box.addWidget(card)
        box.addStretch()
        self._add(page, "完成")

        self.header = QLabel("")
        self.header.setObjectName("hint")
        root.addWidget(self.header)
        root.addWidget(self.steps, 1)
        nav = QHBoxLayout()
        self.skip = QPushButton("以后再说")
        self.skip.clicked.connect(self.reject)
        self.back = QPushButton("上一步")
        self.back.clicked.connect(lambda: self._go(-1))
        self.next = QPushButton("下一步")
        self.next.setProperty("primary", True)
        self.next.clicked.connect(lambda: self._go(1))
        nav.addWidget(self.skip)
        nav.addStretch()
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        root.addLayout(nav)
        self._go(0)

    def _add(self, page, title):
        self.steps.addWidget(page)
        self.titles.append(title)

    def _choose_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型", get_app_path(), "Live2D 模型 (*.model3.json)")
        if path:
            self.model.setText(path)

    def _go(self, delta):
        index = self.steps.currentIndex() + delta
        if index >= self.steps.count():
            self.finish()
            return
        self.steps.setCurrentIndex(max(0, index))
        index = self.steps.currentIndex()
        self.header.setText("  →  ".join(f"【{t}】" if i == index else t for i, t in enumerate(self.titles)))
        self.back.setEnabled(index > 0)
        self.next.setText("开始" if index == self.steps.count() - 1 else "下一步")

    def finish(self):
        self.account.save()
        self.privacy.save()
        if self.model.text().strip() != character.current.get("live2d_model", ""):
            character.update(live2d_model=self.model.text().strip())
        save_settings({"setup_done": True})
        self.accept()
