"""
你们的关系：会随着相处慢慢变近

    - 认识天数：从第一次见面算起；第 7 / 30 / 100 / 200 天、每个周年都会开心地提一下
    - 亲密度：聊天、摸头、一起专注、完成任务都会加一点 (每天有上限，刷不出来)；
      好几天不理她会慢慢掉，但不会掉出已经到达的阶段
    - 阶段：初识 → 熟悉 → 好朋友 → 亲密 → 心有灵犀，越往后说话越放松、越亲近

每个成员各算各的，存在 eureka_relationship.json。
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


STATE_FILE = os.path.join(get_app_path(), "eureka_relationship.json")

LEVELS = [
    (0, "初识", "你们还在互相熟悉：热情有礼貌，叫TA的名字，少开过分的玩笑，多了解TA。"),
    (50, "熟悉", "你们已经挺熟了：语气轻松，可以开点小玩笑，会分享自己的小事。"),
    (150, "好朋友", "你们是好朋友了：说话随意自然，会吐槽也会撒娇，记得你们之间的小梗。"),
    (350, "亲密", "你们关系很亲密：会自然地表达想念和在乎，偶尔用只属于你们的亲昵称呼。"),
    (700, "心有灵犀", "你们像认识很久的知己：默契十足，一句话就懂TA，会主动照顾TA的情绪。"),
]
# 每种互动加多少、每天最多加多少次
POINTS = {"chat": (2, 15), "pat": (1, 5), "focus_done": (3, 4), "task_done": (1, 8), "welcome_back": (1, 2)}
MILESTONE_DAYS = (7, 30, 100, 200, 365)
DECAY_AFTER_DAYS = 3
DECAY_PER_DAY = 3


def level_of(points):
    index = 0
    for i, (threshold, _, _) in enumerate(LEVELS):
        if points >= threshold:
            index = i
    return index


class Relationship:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = self._load()

    def _load(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
        state.setdefault("users", {})
        return state

    def _save(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"   ⚠️ 保存关系状态失败: {e}")

    def _user(self, name):
        users = self.state["users"]
        if name not in users:
            first_met = self._guess_first_met()
            # 已经认识一个月以上的老朋友，起步就算 "熟悉"，不从陌生人开始
            known_long = (date.today() - date.fromisoformat(first_met)).days >= 30
            points = LEVELS[1][0] if known_long else 0
            users[name] = {"first_met": first_met, "points": points, "level": level_of(points),
                           "daily": {"date": "", "counts": {}}, "last_interaction": time.time(),
                           "milestones_done": [], "pending_level_up": None, "last_memory_lane": ""}
        return users[name]

    def _guess_first_met(self):
        """老用户第一次用上这个功能时，用档案文件的创建日期当作认识的那天"""
        try:
            created = os.path.getctime(os.path.join(get_app_path(), "memory.json"))
            return min(date.fromtimestamp(created), date.today()).isoformat()
        except Exception:
            return date.today().isoformat()

    def _apply_decay(self, u, now_ts):
        days_idle = (now_ts - u["last_interaction"]) / 86400
        if days_idle > DECAY_AFTER_DAYS:
            floor = LEVELS[u["level"]][0]  # 不会掉出已经到达的阶段
            u["points"] = max(floor, u["points"] - DECAY_PER_DAY * int(days_idle - DECAY_AFTER_DAYS))

    # ---------------- 互动 ----------------
    def add(self, name, kind, now_ts=None, today=None):
        """记一次互动；跨进新阶段时返回阶段名"""
        if not name or kind not in POINTS:
            return None
        now_ts, today = now_ts or time.time(), (today or date.today()).isoformat()
        gain, daily_cap = POINTS[kind]
        with self._lock:
            u = self._user(name)
            self._apply_decay(u, now_ts)
            if u["daily"]["date"] != today:
                u["daily"] = {"date": today, "counts": {}}
            count = u["daily"]["counts"].get(kind, 0)
            u["last_interaction"] = now_ts
            if count >= daily_cap:
                self._save()
                return None
            u["daily"]["counts"][kind] = count + 1
            u["points"] += gain
            new_level = level_of(u["points"])
            leveled = None
            if new_level > u["level"]:
                u["level"] = new_level
                leveled = u["pending_level_up"] = LEVELS[new_level][1]
                print(f"   💗 和{name}的关系变近了：{leveled}")
            self._save()
            return leveled

    # ---------------- 查询 ----------------
    def days_known(self, name, today=None):
        u = self._user(name)
        return ((today or date.today()) - date.fromisoformat(u["first_met"])).days + 1

    def level_name(self, name):
        return LEVELS[self._user(name)["level"]][1]

    def take_level_up(self, name):
        with self._lock:
            u = self._user(name)
            level, u["pending_level_up"] = u["pending_level_up"], None
            if level:
                self._save()
            return level

    def due_milestone(self, name, today=None):
        """今天是不是值得纪念的日子 (第 7/30/100/200 天、周年)"""
        with self._lock:
            u = self._user(name)
            days = self.days_known(name, today)
            special = days in MILESTONE_DAYS or (days > 365 and (days - 1) % 365 == 0)
            if special and days not in u["milestones_done"]:
                u["milestones_done"].append(days)
                self._save()
                return days
        return None

    def memory_lane_due(self, name, today=None):
        u = self._user(name)
        last = u.get("last_memory_lane") or "2000-01-01"
        return u["level"] >= 2 and (today or date.today()) - date.fromisoformat(last) >= timedelta(days=7)

    def mark_memory_lane(self, name, today=None):
        with self._lock:
            self._user(name)["last_memory_lane"] = (today or date.today()).isoformat()
            self._save()

    def summary(self, name):
        """给 "我们的关系" 菜单看的一句话"""
        u = self._user(name)
        level = u["level"]
        text = f"认识第 {self.days_known(name)} 天 · {LEVELS[level][1]}"
        if level + 1 < len(LEVELS):
            need = LEVELS[level + 1][0] - u["points"]
            text += f" (再相处一阵就是「{LEVELS[level + 1][1]}」啦，还差 {need} 点)"
        return text

    def describe(self, name):
        """给提示词用"""
        u = self._user(name)
        return (f"【你们的关系】：你们认识第 {self.days_known(name)} 天，现在是「{LEVELS[u['level']][1]}」。"
                f"{LEVELS[u['level']][2]}（不要提'等级''亲密度'这些词，只体现在说话方式上）")


bond = Relationship()
