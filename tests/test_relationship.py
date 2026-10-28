from datetime import date

import relationship


def make(tmp_path, monkeypatch):
    monkeypatch.setattr(relationship, "STATE_FILE", str(tmp_path / "rel.json"))
    monkeypatch.setattr(relationship, "get_app_path", lambda: str(tmp_path))  # 没有旧档案 = 今天刚认识
    return relationship.Relationship()


def test_new_friend_starts_at_first_level(tmp_path, monkeypatch):
    bond = make(tmp_path, monkeypatch)
    assert bond.level_name("小明") == relationship.LEVELS[0][1]
    assert bond.days_known("小明") == 1


def test_daily_cap_limits_points(tmp_path, monkeypatch):
    bond = make(tmp_path, monkeypatch)
    gain, cap = relationship.POINTS["pat"]
    for _ in range(cap + 5):
        bond.add("小明", "pat", now_ts=1767225600, today=date(2026, 1, 1))
    assert bond.state["users"]["小明"]["points"] == gain * cap


def test_level_up_is_reported_once(tmp_path, monkeypatch):
    bond = make(tmp_path, monkeypatch)
    _, cap = relationship.POINTS["chat"]
    leveled, day = None, 1
    while not leveled:
        for _ in range(cap):
            leveled = bond.add("小明", "chat", now_ts=1767225600 + day * 3600, today=date(2026, 1, day)) or leveled
        day += 1
        assert day < 28  # 防止死循环
    assert leveled == relationship.LEVELS[1][1]
    assert bond.take_level_up("小明") == leveled
    assert bond.take_level_up("小明") is None


def test_unknown_kind_is_ignored(tmp_path, monkeypatch):
    assert make(tmp_path, monkeypatch).add("小明", "not-a-kind") is None
