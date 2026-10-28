import ai_brain
import tools


def feed_all(chunks):
    seen = []
    f = ai_brain.EmotionTagFilter(seen.append)
    text = "".join(f.feed(c) for c in chunks) + f.flush()
    return text, seen


def test_emotion_tag_split_across_chunks():
    text, seen = feed_all(["[表", "情:得意]", "嘿嘿", "，交给我吧"])
    assert text == "嘿嘿，交给我吧"
    assert seen == ["3clever"]


def test_text_without_tag_passes_through():
    text, seen = feed_all(["你好呀", "~"])
    assert text == "你好呀~" and seen == []


def test_screen_tool_hidden_when_not_allowed(monkeypatch):
    monkeypatch.setattr(tools, "_screen_allowed", lambda: False)
    names = [t["function"]["name"] for t in tools.get_eureka_tools()]
    assert "screen" not in names and "tasks" in names


def test_every_tool_asks_for_ack():
    for t in tools.get_eureka_tools():
        assert "ack" in t["function"]["parameters"]["properties"], t["function"]["name"]
