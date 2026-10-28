"""
友好的出错提示：出问题时让她用一句人话告诉你怎么回事、该怎么办，而不是只写在日志里

    report(error, where)   在出错的地方调用；同一类问题 5 分钟内只提醒一次
    notice(text)           普通提醒 (比如用量超了)
"""
import time

import events

QUIET_SECONDS = 300
_last_shown = {}

# (判断关键词, 类别, 她说的话)
RULES = [
    (("401", "invalid api key", "invalidapikey", "incorrect api key", "authentication", "unauthorized", "无效的", "鉴权"),
     "auth", "我的 Key 好像不对，连不上大脑了…右键 → 系统配置 → 账号与模型 里检查一下吧"),
    (("arrearage", "insufficient", "quota", "欠费", "余额", "billing", "payment"),
     "billing", "我的账户好像没余额了…去百炼控制台看看是不是欠费啦"),
    (("429", "rate limit", "ratelimit", "too many requests", "throttl"),
     "rate", "刚刚说得太快啦，平台让我歇一下，过一会儿再找我哦"),
    (("model_not_found", "model not found", "does not exist", "not activated", "模型不存在"),
     "model", "我要用的模型好像没开通或者名字写错了…设置里的模型名检查一下吧"),
    (("timed out", "timeout", "connection", "connect", "network", "name resolution", "ssl", "10054", "10060", "unreachable"),
     "network", "网络好像断了，我连不上云端…检查一下网络或者代理吧"),
    (("errno -9996", "invalid input device", "-9999", "unanticipated host error", "device unavailable", "-9985", "-9998"),
     "mic", "麦克风好像被别的程序占着，或者没插好…我暂时听不见你说话"),
]


def classify(error):
    text = str(error).lower()
    for words, kind, message in RULES:
        if any(w in text for w in words):
            return kind, message
    return "other", None


def report(error, where=""):
    """出错时调用：认得出来的问题让她说出来，认不出来的只写日志"""
    kind, message = classify(error)
    print(f"   ⚠️ [{where or '出错'}] {error}")
    if not message:
        return
    now = time.time()
    if now - _last_shown.get(kind, 0) < QUIET_SECONDS:
        return
    _last_shown[kind] = now
    events.emit("problem", text=message, category=kind)


def notice(text, key=None):
    """普通提醒，同一个 key 5 分钟内只说一次"""
    key = key or text
    now = time.time()
    if now - _last_shown.get(key, 0) < QUIET_SECONDS:
        return
    _last_shown[key] = now
    events.emit("problem", text=text, category="notice")
