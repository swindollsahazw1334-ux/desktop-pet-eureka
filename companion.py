"""
陪伴感：让尤里卡在合适的时候主动开口

    1. 记得追问：聊天里提到的计划 ("明天面试") 带日期记下来，当天给你打气、过后问你怎么样
    2. 作息问候：每天第一次用电脑说早安；离开一阵回来说 "你回来啦"；深夜提醒睡觉
    3. 陪伴专注：说 "陪我学习 25 分钟"，她安静陪着、显示倒计时，结束时夸你并提醒休息
    4. 任务进度：下午轻轻提醒还剩哪些没做；傍晚收工回顾今天做了什么、在电脑上忙了多久
    5. 她自己的生活和你们的关系：偶尔分享她今天在忙什么；关系变近了会开心；
       认识第 7/30/100 天这种日子会提；偶尔聊起一周前的一件事；好几天没见会说想你

不打扰的规矩：
    - 免打扰开关打开时不主动开口 (专注结束这种你自己要的提醒除外)
    - 全屏 (游戏、视频、开会) 时先憋着，退出全屏再说
    - 两次主动开口至少隔 20 分钟；专注期间不闲聊

这里只决定 "什么时候、因为什么" 开口；说什么由大模型根据人设和记忆现编。
主循环在等唤醒词时调用 poll()，拿到一条就念出来，念完直接接着听你回话。
"""
import ctypes
import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta

import events
import random
import tasks
import activity
import inner_life
import relationship


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


STATE_FILE = os.path.join(get_app_path(), "companion_state.json")

AWAY_SECONDS = 15 * 60          # 这么久没碰键盘鼠标算 "离开了"
MIN_GAP_SECONDS = 20 * 60       # 两次主动开口的最小间隔
MORNING_HOUR = 5                # 这个点之后第一次用电脑算 "早上"
NIGHT_TIME = (23, 30)           # 这个点之后还在用电脑就提醒睡觉
NIGHT_END_HOUR = 4
BREAK_MINUTES = 5
TASK_NUDGE_HOURS = (15, 18)     # 下午这段时间里提醒一次还剩的任务
REVIEW_TIME = (18, 30)          # 这个点之后做收工回顾 (你说 "下班了" 也会做)
REVIEW_MIN_WORK_MINUTES = 60    # 没列任务时，今天至少工作这么久才值得回顾


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds():
    """距离上次碰键盘/鼠标过了多少秒 (Windows)"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    except Exception:
        return 0.0


def foreground_is_fullscreen():
    """前台窗口是不是全屏 (游戏、全屏视频、演示)"""
    try:
        import win32gui
        import win32api
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd))["Monitor"]
        return (left, top, right, bottom) == tuple(monitor)
    except Exception:
        return False


class Companion:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = self._load()
        self.do_not_disturb = False
        self._away_since = None
        self._returned = False
        self.focus = None          # {"end": 时间戳, "minutes": n, "task": "..."}
        self.break_end = None

    # ---------------- 状态存取 ----------------
    def _load(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
        state.setdefault("plans", [])
        state.setdefault("last_morning", "")
        state.setdefault("last_night", "")
        state.setdefault("last_proactive", 0)
        state.setdefault("focus_log", {})
        state.setdefault("last_task_nudge", "")
        state.setdefault("last_review", "")
        state.setdefault("share_day", "")
        state.setdefault("share_hour", 0)
        state.setdefault("last_share", "")
        return state

    def _save(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"   ⚠️ 保存陪伴状态失败: {e}")

    # ---------------- 计划 (记得追问) ----------------
    def add_plans(self, user_name, plans):
        """记忆整理时提取出的带日期计划：[{"event": "面试", "date": "2026-10-29"}]"""
        with self._lock:
            for p in plans:
                event, day = str(p.get("event", "")).strip(), str(p.get("date", "")).strip()
                try:
                    date.fromisoformat(day)
                except ValueError:
                    continue
                if not event or any(x["event"] == event and x["date"] == day and x["user"] == user_name
                                    for x in self.state["plans"]):
                    continue
                self.state["plans"].append({"user": user_name, "event": event, "date": day,
                                            "cheered": False, "followed_up": False})
                print(f"   📅 记下计划：{day} {event}")
            # 太久以前的计划就不留了
            cutoff = (date.today() - timedelta(days=14)).isoformat()
            self.state["plans"] = [x for x in self.state["plans"] if x["date"] >= cutoff]
            self._save()

    def _due_plan(self, user_name, now):
        today = now.date().isoformat()
        for plan in self.state["plans"]:
            if plan["user"] != user_name:
                continue
            # 当天下午 6 点前：打气；当天晚上 6 点后或之后几天：问结果
            if plan["date"] == today and now.hour < 18 and not plan["cheered"]:
                return plan, "cheer"
            if not plan["followed_up"] and (plan["date"] < today or (plan["date"] == today and now.hour >= 18)):
                return plan, "follow_up"
        return None, None

    # ---------------- 专注 ----------------
    def start_focus(self, minutes, task=""):
        minutes = max(1, min(int(minutes or 25), 180))
        self.focus = {"end": time.time() + minutes * 60, "minutes": minutes, "task": task or ""}
        self.break_end = None
        events.emit("focus", end=self.focus["end"], task=self.focus["task"], mode="focus")
        print(f"   📚 开始专注 {minutes} 分钟：{task}")
        return minutes

    def stop_focus(self):
        was = self.focus
        self.focus = None
        self.break_end = None
        events.emit("focus_end")
        return was

    # ---------------- 主循环来问 ----------------
    def quiet_reason(self):
        if self.do_not_disturb:
            return "免打扰"
        if self.focus:
            return "专注中"
        if foreground_is_fullscreen():
            return "全屏"
        return None

    def poll(self, user_name):
        """
        在等唤醒词时反复调用 (很便宜，不联网)。该开口了就返回
        {"kind": ..., "detail": ...}，否则 None。返回后就算 "已经说过" 了
        """
        now = datetime.now()
        idle = idle_seconds()

        # 专注 / 休息结束：你自己要的提醒，免打扰也照说
        if self.focus and time.time() >= self.focus["end"]:
            done, self.focus = self.focus, None
            today_key = now.date().isoformat()
            self.state["focus_log"] = {today_key: self.state["focus_log"].get(today_key, 0) + 1}
            self.break_end = time.time() + BREAK_MINUTES * 60
            events.emit("focus", end=self.break_end, task="休息一下", mode="break")
            return self._fire({"kind": "focus_done", "detail": done})
        if self.break_end and time.time() >= self.break_end:
            self.break_end = None
            events.emit("focus_end")
            return self._fire({"kind": "break_over", "detail": {}})

        # 判断 "离开了又回来"
        if idle >= AWAY_SECONDS:
            if self._away_since is None:
                self._away_since = time.time() - idle
            return None
        if self._away_since is not None and idle < 5:
            away_minutes = int((time.time() - self._away_since) / 60)
            self._returned_days_apart = inner_life.life.days_apart()
            self._away_since = None
            self._returned = away_minutes
        if idle > 60:
            return None  # 人不在电脑前，说了也白说

        if self.quiet_reason():
            return None
        if time.time() - self.state["last_proactive"] < MIN_GAP_SECONDS:
            return None

        today = now.date().isoformat()

        # 早安：每天第一次 (5 点以后)
        if now.hour >= MORNING_HOUR and self.state["last_morning"] != today:
            self.state["last_morning"] = today
            self._returned = False
            plan, stage = self._due_plan(user_name, now)
            if plan and stage == "cheer":
                plan["cheered"] = True  # 早安里顺便打过气了
            # 今天还没列任务、昨天有没做完的，就顺便问问要不要挪过来
            yesterday = tasks.board.yesterday_unfinished(user_name) if not tasks.board.items(user_name) else []
            return self._fire({"kind": "morning", "detail": {"today_plan": plan["event"] if stage == "cheer" else "",
                                                             "yesterday_unfinished": yesterday,
                                                             "days_apart": inner_life.life.days_apart()}})

        # 认识第 7/30/100 天、周年
        days = relationship.bond.due_milestone(user_name, now.date())
        if days:
            return self._fire({"kind": "milestone", "detail": {"days": days}})

        # 关系刚变近
        level = relationship.bond.take_level_up(user_name)
        if level:
            return self._fire({"kind": "level_up", "detail": {"level": level}})

        # 计划：打气 / 追问
        plan, stage = self._due_plan(user_name, now)
        if plan:
            plan["cheered"] = True
            if stage == "follow_up":
                plan["followed_up"] = True
            return self._fire({"kind": stage, "detail": dict(plan)})

        # 收工回顾 (傍晚，一天一次)
        if (now.hour, now.minute) >= REVIEW_TIME and self.state["last_review"] != today:
            done, total = tasks.board.progress(user_name)
            if total or activity.tracker.work_minutes_today() >= REVIEW_MIN_WORK_MINUTES:
                self.state["last_review"] = today
                return self._fire({"kind": "day_review", "detail": self.review_detail(user_name)})

        # 下午提醒一次还剩的任务
        if TASK_NUDGE_HOURS[0] <= now.hour < TASK_NUDGE_HOURS[1] and self.state["last_task_nudge"] != today:
            done, total = tasks.board.progress(user_name)
            if total and done < total:
                self.state["last_task_nudge"] = today
                return self._fire({"kind": "task_nudge", "detail": {"done": done, "total": total,
                                                                    "remaining": tasks.board.unfinished(user_name)}})

        # 晚上偶尔聊起一周多前的一件事 (好朋友以上，一周最多一次)
        if 19 <= now.hour < 22 and relationship.bond.memory_lane_due(user_name, now.date()):
            memory = self._pick_memory(user_name)
            if memory:
                relationship.bond.mark_memory_lane(user_name, now.date())
                return self._fire({"kind": "memory_lane", "detail": {"memory": memory[0], "days_ago": memory[1]}})

        # 每天在随机的某个时间，分享一下她自己在忙什么 (熟悉以上)
        if self.state["share_day"] != today:
            self.state["share_day"], self.state["share_hour"] = today, random.randint(10, 21)
        if (self.state["last_share"] != today and now.hour >= self.state["share_hour"] and now.hour < 22
                and relationship.bond.state["users"].get(user_name, {}).get("level", 0) >= 1):
            self.state["last_share"] = today
            return self._fire({"kind": "share_life", "detail": {"doing": inner_life.life.doing_now(now)}})

        # 深夜还在用电脑
        night = now.hour < NIGHT_END_HOUR or (now.hour, now.minute) >= NIGHT_TIME
        night_key = (now - timedelta(hours=NIGHT_END_HOUR + 1)).date().isoformat()
        if night and self.state["last_night"] != night_key:
            self.state["last_night"] = night_key
            return self._fire({"kind": "late_night", "detail": {"time": now.strftime("%H:%M")}})

        # 离开一阵子回来了
        if self._returned:
            minutes, self._returned = self._returned, False
            return self._fire({"kind": "welcome_back", "detail": {"away_minutes": minutes,
                                                                  "days_apart": getattr(self, "_returned_days_apart", 0)}})
        return None

    def _pick_memory(self, user_name):
        """从一周多前的记忆和做完的任务里挑一件来回忆"""
        import memory_store
        candidates = memory_store.store.old_facts(user_name, 7) + tasks.board.past_done(user_name, 7)
        return random.choice(candidates) if candidates else None

    def review_detail(self, user_name):
        """收工回顾用的数据：任务完成情况 + 电脑使用情况 + 专注轮数"""
        done, total = tasks.board.progress(user_name)
        return {"done": done, "total": total, "unfinished": tasks.board.unfinished(user_name),
                "activity": activity.tracker.describe_today(),
                "focus_count": self.state["focus_log"].get(date.today().isoformat(), 0)}

    def mark_reviewed(self):
        """你主动说 "下班了/今天干了啥" 时已经回顾过，傍晚就不再自动回顾"""
        self.state["last_review"] = date.today().isoformat()
        self._save()

    def note_proactive(self):
        """被动观察 (摸鱼/熬夜提醒) 也算一次主动开口，一起遵守间隔"""
        self.state["last_proactive"] = time.time()
        self._save()

    def allow_observer_nudge(self):
        return not self.quiet_reason() and time.time() - self.state["last_proactive"] >= MIN_GAP_SECONDS

    def _fire(self, item):
        self.state["last_proactive"] = time.time()
        self._save()
        return item


companion = Companion()
