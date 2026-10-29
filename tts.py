"""
尤里卡的嘴巴：所有不在实时对话里说的话 (打字聊天的回复、生日祝福、早报、主动搭话、倒计时提醒……)
都用千问 Omni 念出来，和实时对话是同一个音色 (.env 的 OMNI_VOICE)，不会一个人两种声音。
Omni 连不上时只冒气泡、不出声，不会换成别的声音。
"""
import base64
import os
import re
import sys
import time
import wave
import queue
import threading
import itertools
import numpy as np
import openai
import pygame # 放心用，现在它是无敌的 pygame-ce 了
from openai import OpenAI
import events
import realtime
import inner_life
import notify
import usage

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_env = realtime._env  # .env 已在 realtime 里加载；空值和纯注释都当没填

# ===== 嘴巴配置 (.env) =====
# 非实时的 Omni 负责"把一段文字念出来"；音色和实时对话共用 OMNI_VOICE
# (Tina / Momo / Roya 等两边都有的音色才能统一，Cici 只有实时模型有)
SPEAK_MODEL = _env("OMNI_SPEAK_MODEL", "qwen3.5-omni-flash")
SPEAK_BASE_URL = _env("OMNI_SPEAK_BASE_URL") or _env("VOLC_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
SPEAK_API_KEY = realtime.OMNI_API_KEY
SPEAK_RATE = 24000  # Omni 输出 24kHz 16bit 单声道 PCM
FRAME_MS = 50  # 嘴型包络的帧长

# 表情 -> 说话语气，大模型挑的表情顺带决定她怎么说
BASE_INSTRUCTION = "你是一个元气满满、阳光开朗的少女主播，说话轻快爱笑，自然口语化；语速从容一点，别像赶时间，标点只当停顿，不要念出符号的名字。"
MOOD_INSTRUCTIONS = {
    None: "用开朗明快、带着笑意的语气说。",
    "3clever": "用开心得意、笑嘻嘻的语气说。",
    "4OAO": "用惊讶的语气说，语调上扬。",
    "5QAQ": "用有点委屈、可怜兮兮但不消沉的语气说。",
    "6i gi a ri": "用鼓起脸假装生气、但忍不住要笑出来的语气说。",
    "8punch": "用兴奋、元气满满的语气说。",
    "1desk": "用认真思考、带点好奇的语气，稍微慢一点说。",
    "2mic": "用轻快愉悦、像在哼歌一样的语气说。",
    "7keyboard": "用认真干练的语气说。",
    "9": "用神秘兮兮的语气说。",
}
_mood = None


def _on_event(kind, data):
    """跟着表情换语气；回到待机/开始听新的一句话时恢复默认语气"""
    global _mood
    if kind == "expression":
        _mood = data.get("name")
    elif kind == "status" and data.get("state") in ("idle", "listening"):
        _mood = None

events.subscribe(_on_event)

_stop_event = threading.Event()
_file_counter = itertools.count()

# (伸了个懒腰) 这类动作描写、[表情:xx] 标签只给气泡看，不念出来
_UNSPOKEN = re.compile(r"[（(][^（()）]*[)）]|\[[^\]]*\]")
# markdown 符号只该给眼睛看，念出来会变成"星号""井号"
_MARKDOWN = re.compile(r"[*_`#>|]+")
# 句末标点，用来把流式文本切成一句一句
_SENTENCE_END = re.compile(r"[。！？!?…；;\n]+")
_MIN_SENTENCE_LEN = 8  # 太短的句子先攒着，避免一个字一个字地合成


def _speakable(text):
    """
    把一段回复整理成适合朗读的文字：去掉动作描写、表情标签、markdown 和横杠。

    模型有时会输出 "- 第一点" 或 "——"，直接念会变成"横杠"，很出戏。
    日期/范围里的横杠换成空格，负号保留 (温度 -5 度不会被念反)。
    """
    dashes = r"\-–—－‐‑‒―−"
    text = _UNSPOKEN.sub("", text or "")
    text = re.sub(rf"(?<=[0-9A-Za-z])[{dashes}]+(?=[0-9A-Za-z])", " ", text)  # GPT-4 / 3-5 之间的
    text = re.sub(rf"[—–－‐‑‒―−]+", "，", text)                       # 破折号当停顿，别念成符号
    text = re.sub(r"(?<![0-9A-Za-z])-+(?![0-9A-Za-z])", " ", text)   # 当标点用的 ASCII 横杠
    text = re.sub(r"[~～]+", "，", text)                             # 波浪号当停顿，别念出来
    text = re.sub(r"…+", "，", text)                                # 省略号也当停顿
    text = _MARKDOWN.sub("", text)
    for word in ("横杠", "破折号", "波浪号", "下划线", "省略号"):
        text = text.replace(word, "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip("，,、 \t\n")


def ensure_mixer():
    if not pygame.mixer.get_init():
        pygame.mixer.init()


def stop():
    """立即闭嘴，并丢弃还没播的句子"""
    _stop_event.set()
    if pygame.mixer.get_init():
        pygame.mixer.stop()
        pygame.mixer.music.stop()


def reset():
    """新一轮对话开始前调用，解除 stop() 的静音状态"""
    _stop_event.clear()


_client = None
_speak_disabled = False  # Key/模型/音色配错时，本次运行只冒气泡，不再反复尝试


def _synth(text, respect_stop=True):
    """把一句话念成语音，返回音频文件路径；没东西可念或失败返回 None (只冒气泡)"""
    global _client, _speak_disabled
    spoken = _speakable(text)
    if not spoken or _speak_disabled or not SPEAK_API_KEY:
        return None
    print(f"   [TTS] 正在合成语音: {spoken[:10]}...")
    if _client is None:
        _client = usage.TrackedClient(OpenAI(api_key=SPEAK_API_KEY, base_url=SPEAK_BASE_URL))

    # 有表情就按表情的语气；没有就跟着她当下的状态 (困了软软的、委屈了蔫蔫的)
    mood = MOOD_INSTRUCTIONS.get(_mood) if _mood else (inner_life.life.voice_hint() or MOOD_INSTRUCTIONS[None])
    try:
        stream = _client.chat.completions.create(
            model=SPEAK_MODEL,
            messages=[
                {"role": "system", "content": f"{BASE_INSTRUCTION}你现在只负责朗读下面这段话：内容不要改，"
                                              f"不要回答、不要补充、不要加开场白。标点和符号只当停顿，"
                                              f"绝对不要念出符号本身。{mood}"
                                              f"不管什么情绪，语速都从容一点，句尾留一点停顿，不要着急。"},
                {"role": "user", "content": spoken},
            ],
            modalities=["text", "audio"],
            audio={"voice": realtime.OMNI_VOICE, "format": "wav"},
            stream=True,
            stream_options={"include_usage": True},
        )
        pcm = bytearray()
        for chunk in stream:
            if respect_stop and _stop_event.is_set():
                return None
            if not chunk.choices:
                continue
            audio = getattr(chunk.choices[0].delta, "audio", None)
            data = audio.get("data") if isinstance(audio, dict) else getattr(audio, "data", None)
            if data:
                pcm += base64.b64decode(data)
    except openai.APIStatusError as e:
        if 400 <= e.status_code < 500:
            _speak_disabled = True
            print(f"❌ Omni 朗读配置有误，本次只冒气泡不出声: {e.status_code} {str(e)[:200]}")
            notify.report(e, "朗读")
        else:
            print(f"⚠️ Omni 朗读失败，这句只冒气泡: {e}")
        return None
    except Exception as e:
        notify.report(e, "朗读")
        return None
    if not pcm:
        print("⚠️ Omni 没有返回语音，这句只冒气泡")
        return None

    output_file = os.path.join(get_app_path(), f"reply_{int(time.time() * 1000)}_{next(_file_counter)}.wav")
    with wave.open(output_file, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SPEAK_RATE)
        wf.writeframes(bytes(pcm))
    usage.add("speak_chars", len(spoken))
    return output_file


def _envelope(sound):
    """算出每 FRAME_MS 一帧的音量 (0~1)，让嘴型跟着声音动"""
    samples = pygame.sndarray.array(sound).astype(np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    hop = max(1, int(pygame.mixer.get_init()[0] * FRAME_MS / 1000))
    frames = len(samples) // hop
    if frames == 0:
        return []
    rms = np.sqrt(np.mean(samples[:frames * hop].reshape(frames, hop) ** 2, axis=1))
    peak = np.percentile(rms, 95) or 1.0
    return [round(float(v), 2) for v in np.clip(rms / peak, 0, 1) ** 0.8]


def _play(path, display_text):
    """播放一段已合成的语音 (阻塞到播完或被打断)"""
    try:
        ensure_mixer()
        sound = pygame.mixer.Sound(path)
    except Exception as e:
        print(f"❌ Pygame 播放失败: {e}")
        return
    finally:
        # Sound 已整个读进内存，文件可以马上删
        try:
            os.remove(path)
        except Exception:
            pass

    if _stop_event.is_set():
        return

    print(f"   [TTS] 正在播放...")
    events.say(display_text)
    events.emit("lipsync", envelope=_envelope(sound), frame_ms=FRAME_MS)
    channel = sound.play()
    while channel and channel.get_busy():
        if _stop_event.is_set():
            sound.stop()
            break
        time.sleep(0.02)
    events.emit("speak_end")


def speak(text):
    """合成并播放一整段话 (阻塞)"""
    if not text or _stop_event.is_set():
        return
    try:
        path = _synth(text)
        if path:
            _play(path, text)
        else:
            events.say(text)
    except Exception as e:
        print(f"❌ 说话模块出错: {e}")


def synthesize(text):
    """
    只合成不播放：给手机 QQ 发语音条用，返回 wav 文件路径 (用完记得删)，失败返回 None。

    这里不看 _stop_event：桌面上按了"闭嘴"不代表 QQ 上的消息也不能回语音。
    """
    if not text or not text.strip():
        return None
    try:
        return _synth(text, respect_stop=False)
    except Exception as e:
        print(f"❌ 语音合成出错: {e}")
        return None


class SpeechStream:
    """
    边收文字边说话：大模型吐出一句就合成一句，
    合成下一句的同时播放上一句，不用等整段回复写完。
    """
    def __init__(self):
        self.full_text = ""
        self._buffer = ""
        self._text_queue = queue.Queue()
        self._audio_queue = queue.Queue()
        self._synth_thread = threading.Thread(target=self._synth_loop, daemon=True)
        self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def feed(self, delta):
        self.full_text += delta
        self._buffer += delta
        while True:
            cut = None
            for m in _SENTENCE_END.finditer(self._buffer):
                if m.end() >= _MIN_SENTENCE_LEN or "\n" in m.group():
                    cut = m.end()
                    break
            if cut is None:
                break
            self._push(self._buffer[:cut])
            self._buffer = self._buffer[cut:]

    def finish(self):
        """文字收完了：念完剩下的部分，阻塞到全部播完"""
        self._push(self._buffer)
        self._buffer = ""
        self._text_queue.put(None)
        self._play_thread.join()
        return self.full_text

    def _push(self, sentence):
        sentence = sentence.strip()
        if sentence:
            self._text_queue.put(sentence)

    def _synth_loop(self):
        while True:
            sentence = self._text_queue.get()
            if sentence is None:
                self._audio_queue.put(None)
                return
            if _stop_event.is_set():
                continue
            self._audio_queue.put((_synth(sentence), sentence))

    def _play_loop(self):
        while True:
            item = self._audio_queue.get()
            if item is None:
                return
            path, sentence = item
            if path:
                _play(path, sentence)
            elif not _stop_event.is_set():
                events.say(sentence)


if __name__ == "__main__":
    speak("测试声音，如果不报错说明游击战术成功！")
