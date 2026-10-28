import events
import notify
import usage


def test_classify_common_errors():
    cases = {
        "Error code: 401 - Incorrect API key provided": "auth",
        "Arrearage: account in arrears": "billing",
        "429 Too Many Requests": "rate",
        "model_not_found: qwen-xx": "model",
        "HTTPSConnectionPool: Read timed out": "network",
        "[Errno -9996] Invalid input device": "mic",
        "something odd": "other",
    }
    for text, kind in cases.items():
        assert notify.classify(Exception(text))[0] == kind, text


def test_report_dedupes(monkeypatch):
    shown = []
    monkeypatch.setattr(events, "emit", lambda kind, **data: shown.append(data))
    monkeypatch.setattr(notify, "_last_shown", {})
    notify.report(Exception("401 unauthorized"))
    notify.report(Exception("401 unauthorized"))
    assert len(shown) == 1 and shown[0]["category"] == "auth"


def test_omni_limit_warns_once(tmp_path, monkeypatch):
    warned = []
    monkeypatch.setattr(usage, "USAGE_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setattr(usage, "_data", {})
    monkeypatch.setattr(usage, "_omni_limit_minutes", lambda: 1)
    monkeypatch.setattr(notify, "notice", lambda text, key=None: warned.append(text))
    usage.add("omni_seconds", 30)
    assert warned == []
    usage.add("omni_seconds", 40)
    usage.add("omni_seconds", 40)
    assert len(warned) == 1
    assert usage.today()["omni_seconds"] == 110
