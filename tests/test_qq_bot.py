"""QQ 机器人：收语音、回语音条的流程。全部离线，网络和合成都被替身接住"""
import base64
import os
import sys
import time
import wave
from types import SimpleNamespace

import qq_bot


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = ""

    def json(self):
        return self._payload


class FakeSession:
    """只记下请求，不真的发出去"""

    def __init__(self, upload=None, send=None):
        self.calls = []
        self.upload = upload or FakeResponse(payload={"file_info": "FILE_INFO"})
        self.send = send or FakeResponse()
        self.download = None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.upload if url.endswith("/files") else self.send

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.download


def _wav(tmp_path, name="voice.wav", seconds=0.5, rate=8000):
    path = tmp_path / name
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _bot(answer="我在呢", allowed=True):
    seen = []
    bot = qq_bot.QQBot(lambda name, text: seen.append((name, text)) or answer)
    bot.seen = seen
    bot.allowed = {"OPENID": "莱克斯"} if allowed else {}
    bot.voice_reply = "auto"      # 不让本机 .env 里的设置影响测试
    bot.voice_stt = "auto"
    bot.voice_max_chars = 200
    bot.voice_engine = "realtime"
    bot.sent = []
    bot.voices = []
    bot.real_reply_voice = qq_bot.QQBot.reply_voice.__get__(bot)
    bot.real_synthesize = qq_bot.QQBot._synthesize.__get__(bot)
    bot.reply = lambda openid, text, msg_id, seq=1: bot.sent.append((text, seq)) or True
    bot.reply_voice = lambda openid, path, msg_id, seq=1: bot.voices.append((path, seq)) or True
    bot._synthesize = lambda text: None  # 默认不真的去调百炼；需要语音的测试自己换掉
    bot._token, bot._token_expire = "TEST_TOKEN", time.time() + 3600  # 不真的去换 token
    return bot


def _voice_message(asr="你在干嘛呀", content=""):
    return {
        "id": "MSG1",
        "author": {"user_openid": "OPENID", "username": "莱克斯"},
        "content": content,
        "attachments": [{
            "content_type": "voice",
            "url": "https://example.test/a.silk",
            "voice_wav_url": "https://example.test/a.wav",
            "asr_refer_text": asr,
        }],
    }


def _text_message(content="在吗"):
    return {"id": "MSG2", "author": {"user_openid": "OPENID"}, "content": content}


def test_voice_message_is_transcribed_and_answered_with_voice(tmp_path):
    bot = _bot()
    bot._synthesize = lambda text: str(_wav(tmp_path))

    bot._on_c2c(_voice_message())

    assert bot.seen == [("莱克斯", "你在干嘛呀")]
    assert len(bot.voices) == 1 and bot.voices[0][1] == 1
    assert bot.sent == []                       # 语音回成功了就不用再发文字
    assert not os.path.exists(bot.voices[0][0])  # 合成出来的临时文件用完就删


def test_text_message_gets_a_text_reply(tmp_path):
    bot = _bot(answer="收到啦")
    bot._synthesize = lambda text: str(_wav(tmp_path))

    bot._on_c2c(_text_message())

    assert bot.seen == [("莱克斯", "在吗")]
    assert bot.sent == [("收到啦", 1)]
    assert bot.voices == []


def test_voice_reply_falls_back_to_text_when_tts_fails(tmp_path):
    bot = _bot(answer="我在听呢")
    bot._synthesize = lambda text: None

    bot._on_c2c(_voice_message())

    assert bot.voices == []
    assert bot.sent == [("我在听呢", 1)]


def test_voice_reply_falls_back_to_text_when_upload_fails(tmp_path):
    bot = _bot(answer="我在听呢")
    bot._synthesize = lambda text: str(_wav(tmp_path))
    bot.reply_voice = bot.real_reply_voice
    bot.http = FakeSession(upload=FakeResponse(status_code=400, payload={}))

    bot._on_c2c(_voice_message())

    # 语音那条已经占掉 seq 1，文字从 2 开始，免得同 seq 被 QQ 去重
    assert bot.sent == [("我在听呢", 2)]


def test_long_answer_sends_voice_then_the_rest_as_text(tmp_path):
    bot = _bot(answer="第一句话说完了。后面还有很多话要接着说")
    bot.voice_max_chars = 10
    bot._synthesize = lambda text: str(_wav(tmp_path))

    bot._on_c2c(_voice_message())

    assert bot.voices[0][1] == 1
    assert bot.sent == [("后面还有很多话要接着说", 2)]


def test_voice_mode_replies_with_voice_even_to_text(tmp_path):
    bot = _bot(answer="好呀")
    bot.voice_reply = "voice"
    bot._synthesize = lambda text: str(_wav(tmp_path))

    bot._on_c2c(_text_message())

    assert len(bot.voices) == 1 and bot.sent == []


def test_text_mode_never_sends_voice(tmp_path):
    bot = _bot(answer="好呀")
    bot.voice_reply = "text"
    bot._synthesize = lambda text: str(_wav(tmp_path))

    bot._on_c2c(_voice_message())

    assert bot.voices == [] and bot.sent == [("好呀", 1)]


def test_voice_placeholder_text_still_uses_the_attachment():
    bot = _bot()

    bot._on_c2c(_voice_message(content="[语音]"))

    assert bot.seen == [("莱克斯", "你在干嘛呀")]


def test_voice_stt_modes():
    bot = _bot()
    bot._whisper = lambda voice: "本地识别"

    assert bot._voice_text({"asr": "平台识别"}) == "平台识别"      # auto 先信 QQ
    bot.voice_stt = "qq"
    assert bot._voice_text({"asr": ""}) == ""                      # 只信 QQ，不加载本地模型
    bot.voice_stt = "whisper"
    assert bot._voice_text({"asr": "平台识别"}) == "本地识别"      # 总是用本地模型
    bot._whisper = lambda voice: ""
    assert bot._voice_text({"asr": "平台识别"}) == "平台识别"      # 本地识别失败就退回 QQ


def test_unreadable_voice_asks_to_repeat():
    bot = _bot()
    bot._voice_text = lambda voice: ""
    bot._on_c2c(_voice_message(asr=""))

    assert bot.seen == []
    assert len(bot.sent) == 1 and "没听清" in bot.sent[0][0]


def test_upload_and_send_voice_use_the_media_api(tmp_path):
    bot = _bot()
    path = _wav(tmp_path)
    session = FakeSession()
    bot.http = session

    assert bot.real_reply_voice("OPENID", str(path), "MSG1", 2)

    upload_url, upload_call = session.calls[0]
    assert upload_url == f"{qq_bot.API_BASE}/v2/users/OPENID/files"
    upload = upload_call["json"]
    assert upload["file_type"] == 3
    assert upload["srv_send_msg"] is False
    assert upload["file_name"] == path.name
    assert base64.b64decode(upload["file_data"]) == path.read_bytes()

    send_url, send_call = session.calls[1]
    assert send_url == f"{qq_bot.API_BASE}/v2/users/OPENID/messages"
    assert send_call["json"] == {"msg_type": 7, "media": {"file_info": "FILE_INFO"},
                                "msg_id": "MSG1", "msg_seq": 2}


def test_voice_upload_failure_is_reported_not_raised(tmp_path):
    bot = _bot()
    path = _wav(tmp_path)
    bot.http = FakeSession(upload=FakeResponse(status_code=400))

    assert bot.upload_voice("OPENID", str(path)) is None
    assert bot.real_reply_voice("OPENID", str(path), "MSG1") is False


def test_send_answer_keeps_within_four_passive_replies():
    bot = _bot()

    bot.send_answer("OPENID", "字" * 2200, "MSG1", as_voice=False)

    assert [seq for _, seq in bot.sent] == [1, 2, 3, 4]
    assert sum(len(text) for text, _ in bot.sent) == qq_bot.MAX_REPLY_LEN * 4


def test_qq_voice_prefers_the_realtime_engine(tmp_path, monkeypatch):
    bot = _bot()
    wav = _wav(tmp_path)
    calls = []

    fake_realtime = SimpleNamespace(synthesize=lambda text: calls.append(("realtime", text)) or str(wav))
    fake_tts = SimpleNamespace(_speakable=lambda text: text,
                               synthesize=lambda text: calls.append(("tts", text)) or str(wav))
    monkeypatch.setitem(sys.modules, "realtime", fake_realtime)
    monkeypatch.setitem(sys.modules, "tts", fake_tts)

    assert bot.real_synthesize("你好呀") == str(wav)
    assert calls == [("realtime", "你好呀")]


def test_qq_voice_falls_back_to_tts_when_realtime_is_empty(tmp_path, monkeypatch):
    bot = _bot()
    wav = _wav(tmp_path)
    calls = []

    fake_realtime = SimpleNamespace(synthesize=lambda text: None)
    fake_tts = SimpleNamespace(_speakable=lambda text: text,
                               synthesize=lambda text: calls.append(text) or str(wav))
    monkeypatch.setitem(sys.modules, "realtime", fake_realtime)
    monkeypatch.setitem(sys.modules, "tts", fake_tts)

    assert bot.real_synthesize("你好呀") == str(wav)
    assert calls == ["你好呀"]


def test_qq_voice_can_be_forced_back_to_tts(tmp_path, monkeypatch):
    bot = _bot()
    bot.voice_engine = "tts"
    wav = _wav(tmp_path)
    calls = []

    fake_realtime = SimpleNamespace(synthesize=lambda text: calls.append("realtime") or None)
    fake_tts = SimpleNamespace(_speakable=lambda text: text,
                               synthesize=lambda text: calls.append("tts") or str(wav))
    monkeypatch.setitem(sys.modules, "realtime", fake_realtime)
    monkeypatch.setitem(sys.modules, "tts", fake_tts)

    assert bot.real_synthesize("你好呀") == str(wav)
    assert calls == ["tts"]
