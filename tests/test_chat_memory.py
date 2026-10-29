"""短期对话记忆：按人分开存，QQ 上两个人同时聊天不会串台"""
import json
import time
from types import SimpleNamespace

import ai_brain


def _reset(tmp_path, monkeypatch):
    """每个测试用一份临时聊天记录，不碰真实的 chat_history.json"""
    monkeypatch.setattr(ai_brain, "CHAT_FILE", str(tmp_path / "chat_history.json"))
    monkeypatch.setattr(ai_brain, "chat_histories", {})
    monkeypatch.setattr(ai_brain, "chat_summaries", {})
    monkeypatch.setattr(ai_brain, "chat_updated", {})


def _wait(predicate, timeout=1.0):
    end = time.time() + timeout
    while time.time() < end and not predicate():
        time.sleep(0.01)


def test_short_term_history_is_isolated_per_user(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    ai_brain.remember_exchange("我下周三要去看牙", "记下啦", "小明")
    ai_brain.remember_exchange("我养了一只猫", "猫猫好可爱", "小红")

    ming = ai_brain.history_context(6, "小明")
    hong = ai_brain.history_context(6, "小红")
    assert "我下周三要去看牙" in ming
    assert "我养了一只猫" not in ming
    assert "我养了一只猫" in hong
    assert "我下周三要去看牙" not in hong
    assert ai_brain.history_context(6, "小刚") == "（还没聊过）"


def test_history_is_saved_per_user(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    ai_brain.remember_exchange("我下周三要去看牙", "记下啦", "小明")
    ai_brain.remember_exchange("我养了一只猫", "猫猫好可爱", "小红")

    with open(ai_brain.CHAT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert set(data["histories"]) == {"小明", "小红"}
    assert data["histories"]["小明"][0]["content"] == "我下周三要去看牙"
    assert data["histories"]["小红"][0]["content"] == "我养了一只猫"
    assert data["updated"]["小明"]


def test_old_global_history_migrates_to_the_active_user(tmp_path, monkeypatch):
    path = tmp_path / "chat_history.json"
    path.write_text(json.dumps({
        "history": [{"role": "user", "content": "旧的话"},
                    {"role": "assistant", "content": "旧回复"}],
        "summary": "旧摘要",
        "updated_at": "2026-10-01 10:00",
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai_brain, "CHAT_FILE", str(path))
    monkeypatch.setattr(ai_brain, "get_last_active_user", lambda: "莱克斯")

    histories, summaries, updated = ai_brain._load_chat()

    assert histories["莱克斯"][0]["content"] == "旧的话"
    assert summaries["莱克斯"] == "旧摘要"
    assert updated["莱克斯"] == "2026-10-01 10:00"


def test_summary_is_written_per_user(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_brain, "chat_summaries",
                        {"小明": "小明旧摘要", "小红": "小红旧摘要"})
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="小明新摘要"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply)))
    monkeypatch.setattr(ai_brain, "client", client)

    ai_brain._summarize("小明", [{"role": "user", "content": "聊了很多"}])

    assert ai_brain.chat_summaries["小明"] == "小明新摘要"
    assert ai_brain.chat_summaries["小红"] == "小红旧摘要"


def test_overflow_keeps_ten_rounds_and_summarizes_the_right_user(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(ai_brain, "_summarize",
                        lambda user, messages: calls.append((user, [m["content"] for m in messages])))

    for i in range(11):
        ai_brain.remember_exchange(f"小明第{i}句", "嗯", "小明")

    _wait(lambda: calls)
    assert calls == [("小明", ["小明第0句", "嗯"])]
    assert len(ai_brain.chat_histories["小明"]) == ai_brain.MAX_SHORT_TERM_MEMORY * 2


def test_update_memory_writes_to_the_right_user(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    ai_brain.update_memory("帮我搜了猫咪视频", "记住了", "小红")

    assert "帮我搜了猫咪视频" in ai_brain.history_context(2, "小红")
    assert ai_brain.history_context(2, "小明") == "（还没聊过）"


def test_qq_reply_uses_the_speakers_own_history(monkeypatch):
    import main

    calls = {}

    def fake_history(last_n=6, user=None):
        calls["history"] = user
        return "（还没聊过）"

    def fake_update(user_text, reply, user=None):
        calls["memory"] = user

    monkeypatch.setattr(main.ai_brain, "history_context", fake_history)
    monkeypatch.setattr(main.ai_brain, "get_agent_system_prompt", lambda text, user=None: "SYS")
    monkeypatch.setattr(main.ai_brain, "update_memory", fake_update)
    monkeypatch.setattr(main.ai_brain, "analyze_intent",
                        lambda messages, tools=None: {"role": "assistant", "content": "我在呢"})
    monkeypatch.setattr(main.memory_store, "add_turn_async", lambda *args: calls.setdefault("turn", args))
    monkeypatch.setattr(main, "note_interaction", lambda *args: None)

    assert main.reply_remote("小明", "在吗") == "我在呢"
    assert calls["history"] == "小明"
    assert calls["memory"] == "小明"
    assert calls["turn"][0] == "小明"
