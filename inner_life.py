"""
尤里卡自己的生活：她不是只围着你转，她也有自己的一天、自己的心情

    - 日程：每天按时间段过自己的日子 (写直播稿、练歌、看粉丝留言……)，每天随机组合，不重样
    - 心情和精力：精力跟着一天的时间走 (早上元气、下午犯困、深夜困)；
      心情跟着你们的互动走 (聊天、摸头会开心，好几天不理她会有点委屈)，慢慢回到平常
    - 固定的喜好和口头禅：说过喜欢什么就一直喜欢，不会前后矛盾

这些会写进提示词，让她说话时自然地流露出来 (不是每次都提)。状态存在 eureka_life.json。
"""
import json
import os
import random
import sys
import threading
import time
from datetime import date, datetime

import character


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


STATE_FILE = os.path.join(get_app_path(), "eureka_life.json")


# 一天的时间段 → 这段时间她可能在做的事 (每天每段随机挑一件)
SCHEDULE_BLOCKS = [
    ("07:00", "09:30", ["刚起床，边吃早饭边刷粉丝留言", "在阳台给多肉“小绿”浇水", "对着镜子练直播开场白", "在做早操，还没完全睡醒"]),
    ("09:30", "12:00", ["在写今晚直播的稿子", "在剪昨天的直播切片", "在研究下次直播玩什么游戏", "在回粉丝的私信"]),
    ("12:00", "13:30", ["在吃午饭，今天点了麻辣烫", "吃完饭有点犯困，在午休", "在试做草莓牛奶布丁"]),
    ("13:30", "17:30", ["在练一首新歌，嗓子有点哑", "在学画直播用的表情包", "在看别的主播找灵感", "在整理粉丝来信，看到好几封感动的", "在给直播间换新背景"]),
    ("17:30", "19:30", ["在吃晚饭", "出门散了会儿步，看到了很好看的晚霞", "在敷面膜准备晚上直播"]),
    ("19:30", "23:00", ["在准备晚上的直播", "在看新番，笑得停不下来", "在练游戏技术，被虐得有点惨", "直播刚下播，有点累但很开心"]),
    ("23:00", "07:00", ["困得不行，窝在被窝里刷手机", "在整理今天的直播回放", "本来要睡了，又忍不住看了会儿漫画"]),
]

BASE_MOOD = 65                 # 平常的心情
MOOD_EFFECTS = {"chat": 3, "pat": 2, "poke": -1, "focus_done": 2, "task_done": 2, "welcome_back": 3}


def _in_block(now_hm, start, end):
    return start <= now_hm < end if start < end else (now_hm >= start or now_hm < end)


class InnerLife:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = self._load()

    def _load(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
        state.setdefault("date", "")
        state.setdefault("schedule", [])
        state.setdefault("mood", BASE_MOOD)
        state.setdefault("mood_updated", time.time())
        state.setdefault("last_interaction", time.time())
        return state

    def _save(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"   ⚠️ 保存尤里卡的状态失败: {e}")

    # ---------------- 日程 ----------------
    def _ensure_today(self, today=None):
        today = (today or date.today()).isoformat()
        if self.state["date"] != today:
            rng = random.Random(today)  # 同一天怎么重启都是同一份日程
            self.state["date"] = today
            self.state["schedule"] = [{"from": s, "to": e, "doing": rng.choice(options)}
                                      for s, e, options in SCHEDULE_BLOCKS]
            self._save()

    def doing_now(self, now=None):
        now = now or datetime.now()
        self._ensure_today(now.date())
        hm = now.strftime("%H:%M")
        for block in self.state["schedule"]:
            if _in_block(hm, block["from"], block["to"]):
                return block["doing"]
        return "在发呆"

    # ---------------- 心情 / 精力 ----------------
    def _decay(self, now_ts=None):
        """心情慢慢回到平常 (每小时回 4 点)；好几天没人理会有点委屈"""
        now_ts = now_ts or time.time()
        hours = (now_ts - self.state["mood_updated"]) / 3600
        mood = self.state["mood"]
        step = 4 * hours
        mood = max(BASE_MOOD, mood - step) if mood > BASE_MOOD else min(BASE_MOOD, mood + step)
        days_alone = (now_ts - self.state["last_interaction"]) / 86400
        if days_alone > 2:
            mood = min(mood, BASE_MOOD - 8 * min(days_alone - 2, 4))  # 最多委屈到 33
        self.state["mood"], self.state["mood_updated"] = mood, now_ts

    def on_event(self, kind, now_ts=None):
        """互动会影响心情：聊天、摸头、一起专注完、完成任务都让她开心"""
        with self._lock:
            self._decay(now_ts)
            self.state["mood"] = max(0, min(100, self.state["mood"] + MOOD_EFFECTS.get(kind, 0)))
            if kind != "poke":
                self.state["last_interaction"] = now_ts or time.time()
            self._save()

    def mood(self, now_ts=None):
        with self._lock:
            self._decay(now_ts)
            return self.state["mood"]

    def energy(self, now=None):
        """精力跟着时间走：早上和傍晚好，午后犯困，深夜很困"""
        hour = (now or datetime.now()).hour + (now or datetime.now()).minute / 60
        curve = [(0, 25), (6, 30), (8, 70), (10, 90), (12, 75), (14, 55), (16, 70), (19, 85), (22, 60), (24, 25)]
        for (h1, e1), (h2, e2) in zip(curve, curve[1:]):
            if h1 <= hour < h2:
                return e1 + (e2 - e1) * (hour - h1) / (h2 - h1)
        return 50

    def mood_label(self, now_ts=None):
        m = self.mood(now_ts)
        if m >= 85:
            return "超开心"
        if m >= 70:
            return "开心"
        if m >= 55:
            return "平静"
        if m >= 40:
            return "有点闷闷的"
        return "有点委屈，好久没人陪了"

    def energy_label(self, now=None):
        e = self.energy(now)
        return "元气满满" if e >= 80 else "精神不错" if e >= 60 else "有点犯困" if e >= 40 else "困得睁不开眼"

    def days_apart(self, now_ts=None):
        return int(((now_ts or time.time()) - self.state["last_interaction"]) / 86400)

    def voice_hint(self):
        """没有指定表情时，说话语气跟着她当下的状态走"""
        if self.energy() < 40:
            return "用有点困、软软的、慢悠悠的语气说。"
        if self.mood() < 45:
            return "用有点委屈但见到对方很高兴的语气说。"
        return None

    def describe(self):
        """给提示词用：她此刻的状态"""
        return (f"【你自己的生活】：你自己的喜好：{character.self_profile()}\n"
                f"    【你此刻的状态】：你正{self.doing_now()}；心情{self.mood_label()}；{self.energy_label()}。"
                "（你有自己的生活，可以自然地提到自己在忙什么、心情怎么样，但不要每次都说，也不要喧宾夺主）")


life = InnerLife()
