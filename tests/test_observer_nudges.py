import activity
import nudges
import observer


class FakeTracker:
    def __init__(self, minutes):
        self.minutes = minutes
        self.switches = []

    def recent_minutes(self, category, hours):
        return self.minutes.get(category, 0)


def scan(minutes, current="coding", duration=10):
    obs = observer.AmbientObserver()
    obs.tracker = FakeTracker(minutes)
    return [e["type"] for e in obs._scan_for_events(current, duration)]


def test_fatigue_and_gaming_events():
    assert "fatigue" in scan({"coding": 110})
    assert "gaming_addiction" in scan({"gaming": 95}, current="gaming")
    assert scan({"coding": 30}) == []


def test_manager_picks_most_urgent_and_cools_down():
    manager = nudges.InterventionManager()
    hb = {"events": [{"type": "fatigue", "value": 120}, {"type": "distraction_video", "duration": 6}]}
    ok, event = manager.should_interrupt(hb, "neutral")
    assert ok and event["type"] == "distraction_video"
    assert manager.should_interrupt(hb, "neutral") == (False, None)
    # 深夜写代码不受冷却限制
    ok, event = manager.should_interrupt({"events": [{"type": "late_night_coding", "time": 2}]}, "neutral")
    assert ok and event["type"] == "late_night_coding"


def test_activity_classify():
    assert activity.classify("code.exe", "main.py - Visual Studio Code") == "coding"
    assert activity.classify("chrome.exe", "游戏实况 - 哔哩哔哩") == "video"
    assert activity.fmt_minutes(125) == "2小时5分钟"
