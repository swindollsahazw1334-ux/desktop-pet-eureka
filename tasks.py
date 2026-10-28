"""
今日任务清单：你口头告诉尤里卡今天要做什么，她帮你记着、打勾、提醒

    "今天要写周报、改登录页 bug、回客户邮件"  → 记成 3 条
    "周报写完了"                            → 打勾，进度 1/3
    没做完的，收工时问要不要挪到明天；第二天早安时也会提一下

每个成员一份，按天存到 tasks.json (只在本机)。
"""
import difflib
import json
import os
import sys
import threading
import time
from datetime import date, timedelta

import events


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


TASKS_FILE = os.path.join(get_app_path(), "tasks.json")
KEEP_DAYS = 30


class TaskBoard:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()   # {"2026-10-28": {"小明": [{"text", "done", "done_at"}]}}

    def _load(self):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        self.data = {d: v for d, v in self.data.items() if d >= cutoff}
        try:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"   ⚠️ 保存任务清单失败: {e}")

    def _list(self, user, day=None):
        return self.data.setdefault(day or date.today().isoformat(), {}).setdefault(user, [])

    def _notify(self, user):
        events.emit("tasks", user=user, items=[dict(t) for t in self.items(user)])

    # ---------------- 查询 ----------------
    def items(self, user, day=None):
        return list(self.data.get(day or date.today().isoformat(), {}).get(user, []))

    def progress(self, user):
        items = self.items(user)
        return sum(t["done"] for t in items), len(items)

    def unfinished(self, user, day=None):
        return [t["text"] for t in self.items(user, day) if not t["done"]]

    def yesterday_unfinished(self, user):
        return self.unfinished(user, (date.today() - timedelta(days=1)).isoformat())

    def past_done(self, user, min_age_days=7):
        """一段时间以前做完的任务 [(任务, 几天前)]，给 "还记得吗" 的回忆用"""
        today = date.today()
        result = []
        for day, users in self.data.items():
            age = (today - date.fromisoformat(day)).days
            if age >= min_age_days:
                result += [(t["text"], age) for t in users.get(user, []) if t["done"]]
        return result

    def describe(self, user):
        """给提示词用：今天的任务和进度"""
        items = self.items(user)
        if not items:
            return "今天还没列任务"
        done, total = self.progress(user)
        listing = "；".join(f"{'✓' if t['done'] else '○'} {t['text']}" for t in items)
        return f"完成 {done}/{total}：{listing}"

    # ---------------- 修改 ----------------
    def _match(self, user, target, want_done=None):
        """按名字模糊找任务 (说 "周报" 也能找到 "写周报")"""
        items = self._list(user)
        candidates = [t for t in items if want_done is None or t["done"] == want_done]
        target = (target or "").strip()
        if not target or not candidates:
            return None
        for t in candidates:
            if target in t["text"] or t["text"] in target:
                return t
        best = difflib.get_close_matches(target, [t["text"] for t in candidates], n=1, cutoff=0.4)
        return next((t for t in candidates if best and t["text"] == best[0]), None)

    def add(self, user, texts):
        with self._lock:
            items = self._list(user)
            added = []
            for text in texts:
                text = (text or "").strip()
                if text and not any(t["text"] == text for t in items):
                    items.append({"text": text, "done": False, "done_at": None})
                    added.append(text)
            self._save()
        self._notify(user)
        return added

    def complete(self, user, target):
        with self._lock:
            task = self._match(user, target, want_done=False)
            if task:
                task["done"], task["done_at"] = True, time.strftime("%H:%M")
                self._save()
        if task:
            self._notify(user)
        return task

    def undo(self, user, target):
        with self._lock:
            task = self._match(user, target, want_done=True)
            if task:
                task["done"], task["done_at"] = False, None
                self._save()
        if task:
            self._notify(user)
        return task

    def remove(self, user, target):
        with self._lock:
            task = self._match(user, target)
            if task:
                self._list(user).remove(task)
                self._save()
        if task:
            self._notify(user)
        return task

    def carry_over(self, user):
        """把昨天没做完的挪到今天"""
        moved = self.yesterday_unfinished(user)
        return self.add(user, moved) if moved else []

    def refresh(self, user):
        """启动时 / 换用户时，让界面显示当前用户今天的进度"""
        self._notify(user)


board = TaskBoard()
