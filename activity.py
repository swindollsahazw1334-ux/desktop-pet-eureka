"""
工作统计：尤里卡在后台默默记下你今天在电脑上都干了什么、干了多久

    - 每 5 秒看一眼前台窗口：程序名 (Code.exe / chrome.exe…) + 窗口标题，归成几类
    - 超过 3 分钟没碰键盘鼠标就算 "不在"，不计入任何一类 (挂机不算工作)
    - 按天汇总存到 activity_log.json，重启也不丢；最近 2 小时的明细留在内存里给摸鱼/疲劳提醒用
    - 只记程序名、窗口标题对应的类别和时长，不截屏、不上传

想让某个程序/网站归到别的类，改下面的 PROCESS_RULES / TITLE_RULES 就行。
"""
import json
import os
import sys
import threading
import time
from datetime import date, timedelta


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


LOG_FILE = os.path.join(get_app_path(), "activity_log.json")
SAMPLE_SECONDS = 5
AWAY_SECONDS = 180          # 这么久没碰键盘鼠标就算人不在
KEEP_DAYS = 30
RECENT_HOURS = 2

CATEGORY_NAMES = {
    "coding": "写代码",
    "working": "办公写文档",
    "learning": "查资料学习",
    "social": "聊天沟通",
    "video": "看视频",
    "gaming": "玩游戏",
    "other": "其他",
}
WORK_CATEGORIES = ("coding", "working", "learning")

# 程序名 (小写) → 类别，优先级最高
PROCESS_RULES = {
    "coding": ["code.exe", "cursor.exe", "pycharm64.exe", "idea64.exe", "devenv.exe", "clion64.exe",
               "webstorm64.exe", "goland64.exe", "sublime_text.exe", "windowsterminal.exe", "wt.exe",
               "powershell.exe", "pwsh.exe", "cmd.exe", "notepad++.exe", "rider64.exe", "androidstudio64.exe",
               "studio64.exe", "trae.exe", "windsurf.exe", "claude.exe"],
    "working": ["winword.exe", "excel.exe", "powerpnt.exe", "wps.exe", "et.exe", "wpp.exe", "onenote.exe",
                "outlook.exe", "feishu.exe", "lark.exe", "dingtalk.exe", "notion.exe", "obsidian.exe",
                "typora.exe", "acrord32.exe", "acrobat.exe", "figma.exe", "photoshop.exe", "wxwork.exe"],
    "social": ["wechat.exe", "weixin.exe", "qq.exe", "discord.exe", "telegram.exe", "tim.exe"],
    "video": ["potplayer.exe", "potplayermini64.exe", "vlc.exe", "mpv.exe", "bilibili.exe", "qqlive.exe",
              "iqiyi.exe", "cloudmusic.exe", "qqmusic.exe", "spotify.exe"],
    "gaming": ["steam.exe", "steamwebhelper.exe", "yuanshen.exe", "genshinimpact.exe", "starrail.exe",
               "league of legends.exe", "minecraft.exe", "javaw.exe", "epicgameslauncher.exe", "wegame.exe"],
}
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "360se.exe", "qqbrowser.exe", "brave.exe", "opera.exe"}

# 浏览器和没认出来的程序，再看窗口标题 (小写) 里的关键词
TITLE_RULES = {
    "video": ["bilibili", "哔哩哔哩", "youtube", "爱奇艺", "优酷", "腾讯视频", "抖音", "douyin", "netflix", "直播", "twitch"],
    "gaming": ["steam", "原神", "崩坏", "英雄联盟", "minecraft", "王者荣耀"],
    "social": ["微信", "wechat", "qq邮箱", "discord", "微博", "小红书"],
    "coding": ["github", "gitlab", "localhost", "127.0.0.1", "visual studio code", "pycharm", "jupyter", "leetcode"],
    "learning": ["stack overflow", "stackoverflow", "csdn", "掘金", "知乎", "文档", "docs", "documentation", "教程",
                 "tutorial", "wikipedia", "维基", "mdn", "菜鸟教程", "论文", "arxiv", "coursera", "慕课", "网课",
                 "chatgpt", "claude", "通义", "千问", "百炼", "kimi", "deepseek"],
    "working": ["飞书", "钉钉", "腾讯文档", "石墨", "语雀", "notion", "google docs", "outlook", "邮箱", "jira", "confluence"],
}
OWN_WINDOW_WORDS = ("eurekaai",)


def _foreground():
    """(程序名, 窗口标题)"""
    try:
        import win32gui
        import win32process
        import psutil
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid).name() if pid else ""
        return process, title
    except Exception:
        return "", ""


def classify(process, title):
    process, lowered = (process or "").lower(), (title or "").lower()
    import character
    if any(w in lowered for w in OWN_WINDOW_WORDS + (character.name().lower(),)):
        return None  # 尤里卡自己的窗口不算
    if process not in BROWSERS:
        for category, names in PROCESS_RULES.items():
            if process in names:
                return category
    for category, words in TITLE_RULES.items():
        if any(w in lowered for w in words):
            return category
    return "other"


def fmt_minutes(minutes):
    minutes = int(round(minutes))
    if minutes < 60:
        return f"{minutes}分钟"
    return f"{minutes // 60}小时{minutes % 60}分钟" if minutes % 60 else f"{minutes // 60}小时"


class ActivityTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.log = self._load()
        self.segments = []            # 最近 2 小时：[{"category", "start", "end", "title"}]
        self.switches = []            # 类别切换时间点，看注意力碎片化
        self.current = None           # 当前类别 (人不在时为 None)
        self.current_title = ""
        self.current_since = time.time()
        self._last_flush = time.time()
        self._thread = None

    # ---------------- 存取 ----------------
    def _load(self):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _flush(self):
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        self.log = {d: v for d, v in self.log.items() if d >= cutoff}
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.log, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"   ⚠️ 保存工作统计失败: {e}")
        self._last_flush = time.time()

    # ---------------- 采样 ----------------
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self):
        import companion  # 只用它的键鼠空闲检测
        while True:
            try:
                away = companion.idle_seconds() >= AWAY_SECONDS
                process, title = ("", "") if away else _foreground()
                self.record(None if away else classify(process, title), process, title)
            except Exception as e:
                print(f"   ⚠️ 工作统计采样出错: {e}")
            time.sleep(SAMPLE_SECONDS)

    def record(self, category, process="", title="", seconds=SAMPLE_SECONDS, now=None):
        """记一次采样：category 为 None 表示人不在 / 尤里卡自己的窗口"""
        now = now or time.time()
        with self._lock:
            if category != self.current:
                if category and self.current:
                    self.switches.append((now, self.current, category))
                self.current, self.current_since = category, now
            self.current_title = title
            if category:
                day = date.fromtimestamp(now).isoformat()
                stats = self.log.setdefault(day, {"categories": {}, "apps": {}})
                stats["categories"][category] = stats["categories"].get(category, 0) + seconds
                if process:
                    stats["apps"][process] = stats["apps"].get(process, 0) + seconds
                last = self.segments[-1] if self.segments else None
                if last and last["category"] == category and now - last["end"] <= seconds * 2:
                    last["end"] = now
                else:
                    self.segments.append({"category": category, "start": now - seconds, "end": now})
            cutoff = now - RECENT_HOURS * 3600
            self.segments = [s for s in self.segments if s["end"] > cutoff]
            self.switches = [s for s in self.switches if now - s[0] < 600]
            if now - self._last_flush > 60:
                self._flush()

    # ---------------- 查询 ----------------
    def today_minutes(self, day=None):
        stats = self.log.get(day or date.today().isoformat(), {}).get("categories", {})
        return {c: s / 60 for c, s in stats.items()}

    def recent_minutes(self, category, hours, now=None):
        now = now or time.time()
        cutoff = now - hours * 3600
        return sum(s["end"] - max(s["start"], cutoff) for s in self.segments
                   if s["category"] == category and s["end"] > cutoff) / 60

    def current_minutes(self, now=None):
        """当前这件事连续做了多久"""
        return ((now or time.time()) - self.current_since) / 60 if self.current else 0

    def describe_today(self, day=None):
        """给提示词和收工回顾用的一句话，比如 "工作 3小时20分钟 (写代码 2小时…)；看视频 40分钟" """
        if self._thread is None and not self.log:
            return "（没有开启电脑使用统计）"
        minutes = self.today_minutes(day)
        if not minutes or sum(minutes.values()) < 1:
            return "今天还没怎么用电脑"
        work = sum(minutes.get(c, 0) for c in WORK_CATEGORIES)
        parts = []
        if work >= 1:
            detail = "、".join(f"{CATEGORY_NAMES[c]} {fmt_minutes(minutes[c])}" for c in WORK_CATEGORIES if minutes.get(c, 0) >= 1)
            parts.append(f"工作 {fmt_minutes(work)}（{detail}）")
        for c in ("social", "video", "gaming", "other"):
            if minutes.get(c, 0) >= 5:
                parts.append(f"{CATEGORY_NAMES[c]} {fmt_minutes(minutes[c])}")
        return "；".join(parts)

    def work_minutes_today(self):
        minutes = self.today_minutes()
        return sum(minutes.get(c, 0) for c in WORK_CATEGORIES)


tracker = ActivityTracker()
