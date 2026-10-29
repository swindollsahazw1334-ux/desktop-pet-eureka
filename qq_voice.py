"""
QQ 上的语音：收语音、发语音条要用到的小工具 (纯函数，不联网、不碰麦克风，方便测试)

QQ 官方接口的约定 (2026-10 文档)：
    - 收到的语音是 content_type="voice" 的附件，同时带 voice_wav_url (SILK 转好的 WAV)、
      url (原始 SILK) 和 asr_refer_text (QQ 自己的识别结果)
    - 发语音条要先上传 file_type=3 的文件拿到 file_info，再用 msg_type=7 发出去；
      语音条支持 silk / mp3 / wav / ogg，直接传 WAV 就行
    - 被动回复一条消息最多 4 次，二进制直传单个文件有大小限制

这里只管格式和切分，真正的下载 / 上传 / 合成在 qq_bot.py 和 tts.py 里。
"""
import os
import re
import wave

# 一条语音最多念多久、多大：QQ 客户端录音是 60 秒，二进制直传 5MB 以内最稳
MAX_VOICE_BYTES = 3 * 1024 * 1024
MAX_VOICE_SECONDS = 60.0

# QQ_VOICE_REPLY 的三种取值：auto 跟着对方来 (对方发语音就回语音)
VOICE_REPLY_MODES = ("auto", "voice", "text")
# QQ_VOICE_STT 的三种取值：auto 先 QQ 再本地，qq 只信 QQ，whisper 只用本地模型
STT_MODES = ("auto", "qq", "whisper")

_SENTENCE_END = re.compile(r"[。！？!?~…；;\n]+")
_CLAUSE_END = re.compile(r"[，,、：:]+")


def parse_choice(raw, choices, default):
    """从 .env 读一个枚举值，写错了就当没写，不让一个拼写错误把语音功能弄坏"""
    value = (raw or "").strip().lower()
    return value if value in choices else default


def wants_voice_reply(mode, incoming_voice):
    """这条回复要不要发成语音条：auto 只跟着对方的消息类型走"""
    return mode == "voice" or (mode == "auto" and bool(incoming_voice))


def pick_voice(attachments):
    """
    从 C2C_MESSAGE_CREATE 的 attachments 里挑出语音附件。

    返回 {"url": 下载地址, "is_wav": QQ 是否已经转好 WAV, "asr": QQ 的识别结果}；
    没有语音就返回 None。优先用转好的 WAV，本地识别不用再解码 SILK。
    """
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        if (attachment.get("content_type") or "").strip().lower() != "voice":
            continue
        wav_url = (attachment.get("voice_wav_url") or "").strip()
        url = wav_url or (attachment.get("url") or "").strip()
        if not url:
            continue
        return {
            "url": url,
            "is_wav": bool(wav_url),
            "asr": (attachment.get("asr_refer_text") or "").strip(),
        }
    return None


def placeholder_text(text):
    """QQ 有时会给纯语音消息塞一个 "[语音]" 之类的占位文字，别把它当内容回"""
    return (text or "").strip() in ("[语音]", "[语音消息]", "[Voice]", "[voice]")


def split_text(text, limit=500, max_parts=4):
    """按 QQ 单条消息的字数上限切开，最多 max_parts 条 (被动回复一共只能发 4 次)"""
    text = text or ""
    if limit <= 0 or max_parts <= 0:
        return []
    return [text[i:i + limit] for i in range(0, len(text), limit)][:max_parts]


def split_voice_reply(text, limit):
    """
    长回复切成 (念出来的部分, 剩下的用文字发)。

    尽量在句末断开；没有句号就找逗号；再没有才硬切，免得语音条念到一半就停了。
    """
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text, ""

    head = text[:limit]
    ends = [match.end() for match in _SENTENCE_END.finditer(head)]
    if not ends:
        ends = [match.end() for match in _CLAUSE_END.finditer(head)]
    cut = ends[-1] if ends else limit
    return text[:cut].strip(), text[cut:].strip()


def wav_seconds(path):
    """WAV 有多长 (秒)；读不了就当 0，交给大小检查兜底"""
    try:
        with wave.open(path, "rb") as wav:
            rate = wav.getframerate() or 1
            return wav.getnframes() / rate
    except Exception:
        return 0.0


def voice_file_ok(path, max_bytes=MAX_VOICE_BYTES, max_seconds=MAX_VOICE_SECONDS):
    """
    发之前先量一下：太大或太长就不发语音条、改发文字，
    免得上传半天被 QQ 拒掉，对方还什么都收不到。
    """
    try:
        if os.path.getsize(path) > max_bytes:
            return False
    except OSError:
        return False
    seconds = wav_seconds(path)
    return not seconds or seconds <= max_seconds
