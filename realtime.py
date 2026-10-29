"""
千问 Omni 实时语音对话 (qwen3.8-omni-flash-realtime)

唤醒后开一个实时会话：她直接听你的声音、自己判断你说完了、直接用 Omni 的音色回答，
可以连续聊好几轮不用再喊名字；一段时间没人说话就结束会话，回到待机等唤醒词。

配置 (.env)：
    OMNI_MODEL   默认 qwen3.8-omni-flash-realtime
    OMNI_VOICE   默认 Tina (甜甜：甜美温暖)，实时对话和平时朗读共用这个音色；
                 要选实时和非实时模型都有的音色 (Tina / Momo / Roya 等)，Cici 只有实时模型有
    OMNI_URL     默认 wss://dashscope.aliyuncs.com/api-ws/v1/realtime
                 (连不上就换成 wss://你的工作空间ID.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime)
    OMNI_IDLE_SECONDS  她说完后等你接话的时间 (默认 12 秒)，超时就结束实时对话
    Key 和脑子共用 VOLC_API_KEY (可用 OMNI_API_KEY 单独指定)
"""
import base64
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import wave

import numpy as np
import pyaudio
import websocket
from dotenv import load_dotenv

import character
import events
import usage


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(get_app_path(), ".env"))


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return default if not value or value.startswith("#") else value


def _env_float(name, default):
    try:
        return float(_env(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


OMNI_MODEL = _env("OMNI_MODEL", "qwen3.8-omni-flash-realtime")
OMNI_VOICE = _env("OMNI_VOICE", "Tina")
OMNI_URL = _env("OMNI_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
OMNI_API_KEY = _env("OMNI_API_KEY") or _env("VOLC_API_KEY")

IN_RATE = 16000           # 麦克风采样率 (Omni 要求 16kHz 单声道 PCM)
OUT_RATE = 24000          # Omni 回来的语音
CHUNK = 1600              # 每次发 0.1 秒
LIPSYNC_FRAME_MS = 50
CONNECT_TIMEOUT = _env_float("OMNI_CONNECT_TIMEOUT", 15)  # 连实时服务的超时 (秒)
CONNECT_ATTEMPTS = 2       # 超时就再试一次，网络抖动时不至于直接放弃
IDLE_SECONDS = _env_float("OMNI_IDLE_SECONDS", 12)  # 她说完后这么久没人接话就结束会话
RESPONSE_TIMEOUT = 60      # 一次回复最多等这么久，服务端卡住时别让界面一直“正在思考”

# 回复里出现这些词就换对应表情 (Omni 直接说话，没法再让它写 [表情:xx] 标签)
_EXPRESSION_WORDS = [
    ("5QAQ", ["呜呜", "委屈", "抱歉", "对不起", "难过", "伤心"]),
    ("4OAO", ["哇", "真的吗", "居然", "天哪", "好厉害"]),
    ("6i gi a ri", ["生气", "哼", "不理你"]),
    ("2mic", ["唱歌", "音乐", "歌单", "直播", "开播"]),
    ("7keyboard", ["代码", "编程", "写程序"]),
    ("1desk", ["想想", "让我想", "思考"]),
    ("3clever", ["嘿嘿", "交给我", "搞定", "没问题", "开心", "哈哈"]),
]


class OmniUnavailable(Exception):
    """连不上 / Key 不对 / 模型不可用，调用方应退回经典模式"""


def guess_expression(text):
    for expression, words in _EXPRESSION_WORDS:
        if any(w in text for w in words):
            return expression
    return None


def tools_for_omni(tools):
    """Omni 自己会边做边说，工具里的 "ack" (执行前口语回应) 参数就去掉"""
    result = []
    for tool in tools:
        fn = json.loads(json.dumps(tool["function"]))
        props = fn.get("parameters", {}).get("properties", {})
        props.pop("ack", None)
        if "required" in fn.get("parameters", {}):
            fn["parameters"]["required"] = [r for r in fn["parameters"]["required"] if r != "ack"]
        result.append({"type": "function", "function": fn})
    return result


LEGACY_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
_working_url = None  # 连上过的地址，之后直接用它


def _describe_bad_status(e):
    """把握手失败的服务端原因 (状态码 + 返回内容) 整理成一句话"""
    body = e.resp_body
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    detail = (body or "").strip()
    try:
        data = json.loads(detail)
        detail = data.get("message") or data.get("error", {}).get("message") or detail
        code = data.get("code") or data.get("error", {}).get("code")
        if code:
            detail = f"{code}: {detail}"
    except Exception:
        pass
    return f"HTTP {e.status_code} {detail[:300]}".strip()


def connect():
    """
    连接实时语音服务。先试 .env 里的 OMNI_URL，被拒绝再试另一种地址 (带工作空间 ID 的 / 旧的通用地址)；
    都不行就把服务端给的原因一起报出来
    """
    global _working_url
    urls = [u for u in dict.fromkeys([_working_url, OMNI_URL, LEGACY_URL]) if u]
    reasons = []
    for url in urls:
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                ws = websocket.create_connection(f"{url}?model={OMNI_MODEL}",
                                                 header=[f"Authorization: Bearer {OMNI_API_KEY}"],
                                                 timeout=CONNECT_TIMEOUT)
                if url != OMNI_URL:
                    print(f"   ℹ️ OMNI_URL 连不上，改用 {url} 连上了")
                _working_url = url
                return ws
            except websocket.WebSocketBadStatusException as e:
                # 认证/地址不对，重试也没用
                reasons.append(f"{url} → {_describe_bad_status(e)}")
                break
            except Exception as e:
                if attempt == CONNECT_ATTEMPTS:
                    reasons.append(f"{url} → {e}")
                else:
                    print(f"   ⚠️ 实时语音连接超时，1.5 秒后重试 ({attempt}/{CONNECT_ATTEMPTS})")
                    time.sleep(1.5)
    raise OmniUnavailable("连接被拒绝：\n      " + "\n      ".join(reasons))


def check():
    """自检：python realtime.py --check，看看实时语音能不能连上、会话能不能建立"""
    print(f"模型: {OMNI_MODEL}  音色: {OMNI_VOICE}\nOMNI_URL: {OMNI_URL}\nKey: {'已配置' if OMNI_API_KEY else '没有找到!'}")
    if not OMNI_API_KEY:
        return
    try:
        ws = connect()
    except OmniUnavailable as e:
        print(f"❌ {e}")
        return
    print(f"✅ 连接成功 ({_working_url})，正在建立会话...")
    ws.settimeout(10)
    try:
        first = json.loads(ws.recv())
        print(f"   服务端: {first.get('type')}")
        ws.send(json.dumps({"type": "session.update", "session": {
            "modalities": ["text", "audio"], "voice": OMNI_VOICE,
            "audio": {"input": {"format": {"type": "pcm", "sample_rate": IN_RATE}},
                      "output": {"format": {"type": "pcm", "sample_rate": OUT_RATE}, "voice": OMNI_VOICE}}}}))
        reply = json.loads(ws.recv())
        if reply.get("type") == "session.updated":
            print(f"✅ 会话建立成功，音色 {OMNI_VOICE} 可用。实时语音可以用了！")
        else:
            print(f"❌ 会话设置被拒绝: {json.dumps(reply, ensure_ascii=False)[:500]}")
    except Exception as e:
        print(f"❌ 建立会话时出错: {e}")
    finally:
        ws.close()


def synthesize(text, instructions=None, timeout=45):
    """
    用实时模型把一段文字说/唱出来 (给手机 QQ 的语音条用)，返回 wav 路径；失败返回 None。

    和 tts.py 的朗读不同：文字是喂给实时模型的输入，音频由模型直接生成，
    所以停顿、情绪更像电脑前聊天；内容本身是歌词时，也可以带旋律唱出来。
    """
    text = (text or "").strip()
    if not text or not OMNI_API_KEY:
        return None
    ws = None
    try:
        ws = connect()
        ws.settimeout(30)
        first = json.loads(ws.recv())
        if first.get("type") == "error":
            print(f"   ⚠️ 实时合成被拒绝: {first}")
            return None
        instruction = instructions or (
            f"你是{character.name()}，一个元气满满的少女。现在要把下面这段话用语音说给TA听："
            "语气自然、有情绪，像真的在说话；不要改内容，不要加开场白或解释。"
            "如果这段话本身是歌词，就带着旋律唱出来。")
        ws.send(json.dumps({"type": "session.update", "session": {
            "modalities": ["text", "audio"],
            "voice": OMNI_VOICE,
            "instructions": instruction,
            "audio": {"input": {"format": {"type": "pcm", "sample_rate": IN_RATE}},
                      "output": {"format": {"type": "pcm", "sample_rate": OUT_RATE}, "voice": OMNI_VOICE}},
            "turn_detection": None,
        }}))
        ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text",
                         "text": f"请用你的声音、带情绪地把下面这句话原样说出来，不要回答它、不要加开场白：\n「{text}」"}],
        }}))
        ws.send(json.dumps({"type": "response.create"}))

        pcm = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                event = json.loads(ws.recv())
            except Exception as e:
                print(f"   ⚠️ 实时合成中断: {e}")
                break
            kind = event.get("type", "")
            if kind == "response.audio.delta":
                pcm += base64.b64decode(event.get("delta", ""))
            elif kind == "error":
                print(f"   ⚠️ 实时合成出错: {event.get('error')}")
                return None
            elif kind == "response.done":
                break
        if not pcm:
            return None

        fd, path = tempfile.mkstemp(prefix="qq_voice_", suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(OUT_RATE)
            wf.writeframes(bytes(pcm))
        usage.add("omni_seconds", max(1, int(len(pcm) / 2 / OUT_RATE)))
        return path
    except Exception as e:
        print(f"   ⚠️ 实时合成失败: {e}")
        return None
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


class _Player:
    """边收边播 Omni 的语音，并把每一小段的音量发给界面驱动嘴型"""
    def __init__(self):
        self.queue = queue.Queue()
        self.playing = False
        self.last_audio_time = 0.0
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(format=pyaudio.paInt16, channels=1, rate=OUT_RATE, output=True)
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def push(self, pcm_bytes):
        self.playing = True
        self.queue.put(pcm_bytes)

    def flush(self):
        """被打断：丢掉还没播的部分"""
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def close(self):
        self._stop = True
        self.flush()
        self.queue.put(None)
        self._thread.join(timeout=2)
        try:
            self._stream.stop_stream()
            self._stream.close()
            self._pa.terminate()
        except Exception:
            pass

    def _loop(self):
        while not self._stop:
            try:
                pcm = self.queue.get(timeout=0.3)
            except queue.Empty:
                if self.playing:
                    self.playing = False
                    self.last_audio_time = time.time()
                    events.emit("speak_end")
                continue
            if pcm is None:
                return
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
            hop = OUT_RATE * LIPSYNC_FRAME_MS // 1000
            frames = max(1, len(samples) // hop)
            rms = np.sqrt(np.mean(samples[:frames * hop].reshape(frames, -1) ** 2, axis=1)) if len(samples) >= hop else np.array([0.0])
            envelope = [round(float(v), 2) for v in np.clip(rms / 6000.0, 0, 1) ** 0.8]
            events.emit("lipsync", envelope=envelope, frame_ms=LIPSYNC_FRAME_MS)
            self._stream.write(pcm)
            self.last_audio_time = time.time()


class OmniSession:
    """
    一次实时对话会话。run() 阻塞到会话结束 (空闲超时 / 被要求停止)。
    run_tool(name, args) -> str      执行工具，返回给模型看的结果
    should_stop() -> bool            为 True 时结束会话 (比如用户改成打字)
    on_turn(user_text, reply_text)   每轮对话结束后回调 (用来存记忆)
    """
    def __init__(self, instructions, tools, run_tool, should_stop=None, on_turn=None, allow_barge_in=False):
        self.instructions = instructions
        self.tools = tools_for_omni(tools)
        self.run_tool = run_tool
        self.should_stop = should_stop or (lambda: False)
        self.on_turn = on_turn
        self.allow_barge_in = allow_barge_in

        self.ws = None
        self._send_lock = threading.Lock()
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._session_ok = False  # 收到 session.updated 才算会话真正建立
        self._error = None
        self.player = None

        self.last_activity = time.time()
        self.user_speaking = False
        self.responding = False
        self.responding_since = 0.0
        self._pending_calls = []
        self._user_text = ""
        self._reply_text = ""
        self._tool_notes = []
        self._sentence_buf = ""

    # ---------------- 连接 ----------------
    def _send(self, event):
        with self._send_lock:
            if self.ws is not None and not self._closed.is_set():
                self.ws.send(json.dumps(event, ensure_ascii=False))

    def _connect(self):
        if not OMNI_API_KEY:
            raise OmniUnavailable("没有配置百炼 Key")
        self.ws = connect()
        self.ws.settimeout(None)

    def _session_update(self):
        self._send({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": OMNI_VOICE,
                "instructions": self.instructions,
                "audio": {
                    "input": {"format": {"type": "pcm", "sample_rate": IN_RATE}},
                    "output": {"format": {"type": "pcm", "sample_rate": OUT_RATE}, "voice": OMNI_VOICE},
                },
                "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
                "turn_detection": {"type": "server_vad", "threshold": 0.5, "silence_duration_ms": 700},
                "tools": self.tools,
            },
        })

    # ---------------- 主流程 ----------------
    def run(self):
        self._connect()
        self._started_at = None
        recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        recv_thread.start()
        if not self._ready.wait(timeout=10):
            self.close()
            raise OmniUnavailable(self._error or "实时会话没有建立 (超时)")
        if self._error or not self._session_ok:
            self.close()
            raise OmniUnavailable(self._error or "服务端关闭了连接，没有建立会话 (检查 Key / 模型名)")

        self.player = _Player()
        self._started_at = time.time()
        events.status("💬 实时对话中，直接说吧~", "listening")
        print(f"   🎙️ 实时对话已开始 ({OMNI_MODEL} / 音色 {OMNI_VOICE})")

        pa = pyaudio.PyAudio()
        mic = pa.open(format=pyaudio.paInt16, channels=1, rate=IN_RATE, input=True, frames_per_buffer=CHUNK)
        try:
            while not self._closed.is_set():
                pcm = mic.read(CHUNK, exception_on_overflow=False)
                if self.should_stop():
                    print("   ⏹️ 实时对话被要求结束")
                    break

                if self.responding and self.responding_since and time.time() - self.responding_since > RESPONSE_TIMEOUT:
                    print("   ⚠️ 实时回复超时，结束这次会话")
                    break

                busy = self.responding or self.player.playing or self.user_speaking or self._pending_calls
                if busy:
                    self.last_activity = time.time()
                elif time.time() - self.last_activity > IDLE_SECONDS:
                    print("   💤 一阵子没人说话，结束实时对话")
                    break

                # 外放时她自己的声音会被麦克风录到，没开"允许插话"就先不发，免得自己打断自己
                if self.player.playing and not self.allow_barge_in:
                    continue
                self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})
        finally:
            try:
                mic.stop_stream()
                mic.close()
                pa.terminate()
            except Exception:
                pass
            self.close()

    def interrupt(self):
        """双击打断：停掉正在说的话"""
        if self.player:
            self.player.flush()
        if self.responding:
            self._send({"type": "response.cancel"})

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if getattr(self, "_started_at", None):
            usage.add("omni_seconds", int(time.time() - self._started_at))  # 实时语音按时长计费
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.player:
            self.player.close()
        events.emit("speak_end")

    # ---------------- 服务端事件 ----------------
    def _recv_loop(self):
        try:
            while not self._closed.is_set():
                raw = self.ws.recv()
                if not raw:
                    break
                self._handle(json.loads(raw))
        except Exception as e:
            if not self._closed.is_set():
                print(f"   ⚠️ 实时连接断开: {e}")
                self._error = self._error or str(e)
        finally:
            self._ready.set()
            self._closed.set()

    def _handle(self, event):
        kind = event.get("type", "")

        if kind == "session.created":
            self._session_update()
        elif kind == "session.updated":
            self._session_ok = True
            self._ready.set()

        elif kind == "error":
            err = event.get("error", {})
            msg = f"{err.get('code')}: {err.get('message')}"
            print(f"   ❌ 实时语音出错 {msg}")
            if not self._ready.is_set():
                self._error = msg
                self._ready.set()
            else:
                # 会话中途出错 (比如模型服务端 500)：直接结束这次会话，
                # 不然 responding 一直为 True，界面会卡在“正在思考”
                self._error = msg
                self.responding = False
                self.close()

        elif kind == "input_audio_buffer.speech_started":
            self.user_speaking = True
            self.last_activity = time.time()
            if self.allow_barge_in and self.player and self.player.playing:
                print("   ✋ 被插话打断")
                self.player.flush()
            events.status("👂 在听...", "listening")

        elif kind == "input_audio_buffer.speech_stopped":
            self.user_speaking = False
            self.last_activity = time.time()
            events.status("🧠 正在思考...", "thinking")

        elif kind == "conversation.item.input_audio_transcription.completed":
            self._user_text = event.get("transcript", "")
            if self._user_text:
                print(f"\n🗣️ 用户说: {self._user_text}")

        elif kind == "response.created":
            self.responding = True
            self.responding_since = time.time()

        elif kind == "response.audio.delta":
            if self.player:
                self.player.push(base64.b64decode(event.get("delta", "")))

        elif kind == "response.audio_transcript.delta":
            delta = event.get("delta", "")
            self._reply_text += delta
            self._sentence_buf += delta
            # 一句话说完就冒个气泡
            m = re.search(r"[。！？!?~…]+", self._sentence_buf)
            if m:
                events.say(self._sentence_buf[:m.end()].strip())
                self._sentence_buf = self._sentence_buf[m.end():]

        elif kind == "response.audio_transcript.done":
            if self._sentence_buf.strip():
                events.say(self._sentence_buf.strip())
            self._sentence_buf = ""
            expression = guess_expression(event.get("transcript", "") or self._reply_text)
            if expression:
                events.expression(expression)

        elif kind == "response.function_call_arguments.done":
            self._pending_calls.append(event)

        elif kind == "response.done":
            self.responding = False
            self.responding_since = 0.0
            self.last_activity = time.time()
            if self._pending_calls:
                calls, self._pending_calls = self._pending_calls, []
                # 工具可能要跑好几秒 (联网搜索等)，放到后台线程，别卡住收消息
                threading.Thread(target=self._run_calls, args=(calls,), daemon=True).start()
            else:
                self._finish_turn()

    def _run_calls(self, calls):
        self._pending_calls = calls  # 执行期间不算空闲
        for call in calls:
            name = call.get("name", "")
            try:
                args = json.loads(call.get("arguments") or "{}")
            except Exception:
                args = {}
            events.status(f"🚀 执行: {name}", "acting")
            try:
                output = self.run_tool(name, args)
            except Exception as e:
                output = f"{name} 执行出错: {e}"
            print(f"      👀 观察结果: {output}")
            self._tool_notes.append(f"[{name}: {output}]")
            self._send({"type": "conversation.item.create",
                        "item": {"type": "function_call_output", "call_id": call.get("call_id"), "output": str(output)}})
        self._pending_calls = []
        events.status("🧠 正在思考...", "thinking")
        self._send({"type": "response.create"})

    def _finish_turn(self):
        user_text, reply = self._user_text, self._reply_text.strip()
        memory = " ".join(self._tool_notes + [reply]).strip()  # 记忆里连工具结果一起存
        self._user_text, self._reply_text, self._tool_notes = "", "", []
        if reply:
            print(f"<<< 🏁 {character.name()}: {reply}")
        events.status("💬 还在听哦，接着说吧~", "listening")
        if self.on_turn and (user_text or memory):
            threading.Thread(target=self.on_turn, args=(user_text, memory), daemon=True).start()


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        print("用法：python realtime.py --check   检查实时语音能不能连上")
