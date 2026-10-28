"""
行为观察：根据工作统计 (activity.py) 判断要不要提醒摸鱼、熬夜、太累、玩太久

只看窗口归类和时长，不截屏。数据由 activity.tracker 在后台采样
(人不在电脑前的时间不算)，这里每 10 秒看一次有没有值得提醒的事。
"""
import datetime
import time

import activity


class AmbientObserver:
    CHECK_INTERVAL = 10

    def __init__(self):
        self.tracker = activity.tracker
        self.last_check_timestamp = 0

    def check_environment(self):
        """返回 heartbeat (含 events)，还没到检查时间返回 None"""
        if time.time() - self.last_check_timestamp < self.CHECK_INTERVAL:
            return None
        self.last_check_timestamp = time.time()
        if self.tracker._thread is None:  # 隐私设置里关掉了电脑使用统计，就什么都不看
            return None

        t = self.tracker
        current = t.current or "away"
        return {
            "timestamp": time.time(),
            "current_activity": current,
            "duration": t.current_minutes(),
            "window_title": t.current_title,
            "metrics": {
                "total_coding_2h": t.recent_minutes("coding", 2),
                "total_gaming_2h": t.recent_minutes("gaming", 2),
            },
            "events": self._scan_for_events(current, t.current_minutes()),
        }

    def _scan_for_events(self, activity_name, duration):
        t = self.tracker
        events = []
        hour = datetime.datetime.now().hour

        # 1. 高强度疲劳：2 小时里写代码超过 100 分钟
        coding_2h = t.recent_minutes("coding", 2)
        if coding_2h > 100:
            events.append({"type": "fatigue", "value": coding_2h})

        # 2. 深夜修仙：凌晨 1~5 点连续写代码超过 30 分钟
        if activity_name == "coding" and 1 <= hour <= 5 and duration > 30:
            events.append({"type": "late_night_coding", "time": hour})

        # 3. 摸鱼：写代码时切出去看视频 / 放下代码直接看视频
        video_recent = t.recent_minutes("video", 0.5)
        coding_recent = t.recent_minutes("coding", 0.5)
        if activity_name == "coding" and video_recent > 5.0:
            events.append({"type": "distraction_video", "duration": video_recent,
                           "desc": f"写代码期间频繁看视频(累计{video_recent:.1f}分钟)"})
        elif activity_name == "video" and coding_recent > 1.0:
            events.append({"type": "distraction_video", "duration": duration,
                           "desc": f"放下代码就开始看视频(已看{duration:.1f}分钟)"})

        # 4. 游戏玩太久：2 小时里超过 90 分钟
        gaming_2h = t.recent_minutes("gaming", 2)
        if gaming_2h > 90:
            events.append({"type": "gaming_addiction", "value": gaming_2h})

        # 5. 注意力碎片化：2 分钟内在代码和视频/聊天之间来回切 3 次以上
        now = time.time()
        recent = [s for s in t.switches if now - s[0] < 120]
        if len(recent) >= 3:
            has_coding = any("coding" in (a, b) for _, a, b in recent)
            has_distraction = any(c in ("video", "social") for _, a, b in recent for c in (a, b))
            if has_coding and has_distraction:
                events.append({"type": "attention_fragmented", "count": len(recent),
                               "desc": f"注意力在代码和视频间切换了{len(recent)}次"})
        return events


# 全局单例
observer = AmbientObserver()
