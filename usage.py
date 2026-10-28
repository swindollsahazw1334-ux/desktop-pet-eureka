"""
用量统计：每天记一下用了多少云端服务，免得月底账单吓一跳

    omni_seconds   实时语音聊了多久 (按音频计费，最贵的那一项)
    llm_calls      调大模型的次数 (聊天、主动开口、记忆整理……)
    llm_tokens     大模型用掉的 token (接口有返回时才算得上)
    speak_chars    念出来的字数
    vision_calls   看屏幕的次数

实时语音当天超过 settings.json 的 daily_omni_minutes (默认 60 分钟) 时提醒一次。
具体花了多少钱以百炼控制台为准，这里只记用量。存在 usage.json，保留 60 天。
"""
import json
import os
import sys
import threading
from datetime import date, timedelta

import notify


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


USAGE_FILE = os.path.join(get_app_path(), "usage.json")
SETTINGS_FILE = os.path.join(get_app_path(), "settings.json")
KEEP_DAYS = 60
DEFAULT_OMNI_MINUTES = 60

_lock = threading.Lock()


def _load():
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_data = _load()


def _save():
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    for day in [d for d in _data if d < cutoff]:
        del _data[day]
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _omni_limit_minutes():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return float(json.load(f).get("daily_omni_minutes", DEFAULT_OMNI_MINUTES))
    except Exception:
        return DEFAULT_OMNI_MINUTES


def add(key, amount=1, day=None):
    day = (day or date.today()).isoformat()
    with _lock:
        today = _data.setdefault(day, {})
        today[key] = today.get(key, 0) + amount
        _save()
        omni_minutes = today.get("omni_seconds", 0) / 60
        warned = today.get("omni_warned", False)
    limit = _omni_limit_minutes()
    if key == "omni_seconds" and limit > 0 and omni_minutes >= limit and not warned:
        with _lock:
            _data[day]["omni_warned"] = True
            _save()
        notify.notice(f"今天实时聊天已经超过 {int(limit)} 分钟啦，实时语音按时长收费，留意一下用量哦~", key="omni_limit")


def today(day=None):
    return dict(_data.get((day or date.today()).isoformat(), {}))


def describe_today():
    t = today()
    parts = []
    if t.get("omni_seconds"):
        parts.append(f"实时语音 {round(t['omni_seconds'] / 60)} 分钟")
    if t.get("llm_calls"):
        parts.append(f"对话 {t['llm_calls']} 次" + (f" ({t['llm_tokens'] // 1000}k tokens)" if t.get("llm_tokens", 0) >= 1000 else ""))
    if t.get("speak_chars"):
        parts.append(f"朗读 {t['speak_chars']} 字")
    if t.get("vision_calls"):
        parts.append(f"看屏幕 {t['vision_calls']} 次")
    return "、".join(parts) or "今天还没用到云端服务"


class _TrackedCompletions:
    def __init__(self, inner):
        self._inner = inner

    def create(self, **kwargs):
        add("llm_calls")
        response = self._inner.create(**kwargs)
        tokens = getattr(getattr(response, "usage", None), "total_tokens", None)
        if tokens and not kwargs.get("stream"):
            add("llm_tokens", tokens)
        return response


class _TrackedChat:
    def __init__(self, inner):
        self.completions = _TrackedCompletions(inner.completions)


class TrackedClient:
    """包一层 OpenAI 客户端：每次调大模型顺手记一笔，其他用法不变"""
    def __init__(self, client):
        self._client = client
        self.chat = _TrackedChat(client.chat)

    def __getattr__(self, name):
        return getattr(self._client, name)
