"""
QQ 官方机器人：不在电脑前也能在手机 QQ 上找尤里卡聊天

    - 走 QQ 开放平台的官方接口 (合规，不会封号)，用 WebSocket 长连接收消息，家里电脑不需要公网 IP
    - 只和白名单里的人聊 (QQ_ALLOWED_USERS)，陌生人只会收到一句 "我还不认识你" 和加白名单用的身份码
    - 同一个她：人设、记忆、任务清单、你们的关系都和电脑上通用
    - 远程只开放适合离开电脑时用的工具：任务清单、记事、备忘、查天气、联网搜索
    - 语音也听得懂、也能回：收到的语音用 QQ 自带识别结果，没有就跑本地 Whisper；
      回复可以合成成语音条发回去 (和电脑上是同一个音色)

注意：尤里卡运行在你的电脑上，电脑得开着她才能回你。
QQ 规定：收到你的消息后 60 分钟内、每条最多回复 4 次 (被动回复)。

状态：功能已预留，默认关闭。要用时在 .env 里加 QQ_BOT_ENABLED=true

配置 (.env)：
    QQ_BOT_ENABLED=true   打开这个功能 (不写就不启动，即使填了 AppID/Secret)
    QQ_BOT_APPID=机器人的 AppID
    QQ_BOT_SECRET=机器人的 AppSecret
    QQ_ALLOWED_USERS=身份码:小明,身份码2:小红      (身份码第一次发消息时她会告诉你)
    QQ_BOT_PROXY=auto     auto：先直连，不通再走系统代理 (默认)；direct：只直连；system：只走系统代理
                          开着 Clash 等代理时，QQ 的服务器常常走代理连不上，默认先直连就是为了这个
    QQ_VOICE_REPLY=auto   auto：你发语音她就回语音、你打字她就回文字 (默认)；voice：总是回语音；text：只回文字
    QQ_VOICE_ENGINE=tts  QQ 语音条用朗读合成 (默认，快、便宜)；realtime：改用实时模型生成 (更接近电脑前，能唱)
    QQ_VOICE_STT=auto     auto：先用 QQ 自带识别、没有再用本地 Whisper；qq：只信 QQ；whisper：总是用本地模型
    QQ_VOICE_MAX_CHARS=120  一条语音最多念多少字 (约 50 秒)，多出来的部分用文字消息补发
"""
import base64
import os
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlparse
import json

import requests
import websocket
from dotenv import load_dotenv

import character
import qq_voice


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(get_app_path(), ".env"))


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return default if not value or value.startswith("#") else value


def _env_int(name, default):
    try:
        return int(_env(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


ENABLED = (_env("QQ_BOT_ENABLED", "false") or "").lower() in ("1", "true", "yes", "on")
APP_ID = _env("QQ_BOT_APPID")
APP_SECRET = _env("QQ_BOT_SECRET")
TOKEN_URLS = [_env("QQ_BOT_TOKEN_URL", "https://bots.qq.com/app/getAppAccessToken"),
              "https://api.bot.qq.com/app/getAppAccessToken"]  # 文档里出现过两种域名，第一个不通就试第二个
API_BASE = _env("QQ_BOT_API", "https://api.sgroup.qq.com")
INTENT_GROUP_AND_C2C = 1 << 25
PROXY_MODE = (_env("QQ_BOT_PROXY", "auto") or "auto").lower()

MAX_REPLY_LEN = 500       # QQ 一条文字消息的字数上限
MAX_REPLIES = 4           # QQ 规定同一条消息最多被动回复 4 次
VOICE_REPLY = qq_voice.parse_choice(_env("QQ_VOICE_REPLY"), qq_voice.VOICE_REPLY_MODES, "auto")
VOICE_ENGINE = qq_voice.parse_choice(_env("QQ_VOICE_ENGINE"), ("realtime", "tts"), "tts")
VOICE_STT = qq_voice.parse_choice(_env("QQ_VOICE_STT"), qq_voice.STT_MODES, "auto")
VOICE_MAX_CHARS = _env_int("QQ_VOICE_MAX_CHARS", 120)  # 实测她念中文约 0.45 秒/字，120 字约 50 秒


def _make_session(use_proxy):
    session = requests.Session()
    session.trust_env = use_proxy  # False：不管系统/环境变量里的代理，直接连
    return session


def _proxy_hint():
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}
    return f"（检测到系统代理 {proxies.get('https') or proxies.get('http')}）" if proxies else ""


def parse_allowed(raw):
    """"身份码:名字,身份码2:名字2" → {身份码: 名字}"""
    allowed = {}
    for part in (raw or "").split(","):
        if ":" in part:
            openid, name = part.split(":", 1)
            if openid.strip() and name.strip():
                allowed[openid.strip()] = name.strip()
    return allowed


class QQBot:
    def __init__(self, on_message):
        """on_message(member_name, text) -> 回复文字 (在后台线程里调用)"""
        self.on_message = on_message
        self.allowed = parse_allowed(_env("QQ_ALLOWED_USERS"))
        # 语音相关的设置放实例上，测试和以后的设置界面都能单独改
        self.voice_reply = VOICE_REPLY
        self.voice_stt = VOICE_STT
        self.voice_max_chars = VOICE_MAX_CHARS
        self.voice_engine = VOICE_ENGINE
        self._token, self._token_expire = None, 0
        self._token_url = None
        self.session_id, self.seq = None, None
        self.ws = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self.ready = threading.Event()
        # 先直连；auto 模式下直连不通会自动换成走系统代理
        self.use_proxy = PROXY_MODE == "system"
        self.http = _make_session(self.use_proxy)

    @property
    def configured(self):
        return bool(APP_ID and APP_SECRET)

    # ---------------- 鉴权 ----------------
    def token(self):
        if self._token and time.time() < self._token_expire - 60:
            return self._token
        errors = []
        modes = [self.use_proxy] + ([not self.use_proxy] if PROXY_MODE == "auto" else [])
        urls = [self._token_url] + TOKEN_URLS if self._token_url else TOKEN_URLS
        for use_proxy in modes:
            session = self.http if use_proxy == self.use_proxy else _make_session(use_proxy)
            for url in urls:
                try:
                    data = session.post(url, json={"appId": APP_ID, "clientSecret": APP_SECRET}, timeout=10).json()
                except Exception as e:
                    errors.append(f"[{'代理' if use_proxy else '直连'}] {url} → {e}")
                    continue
                if data.get("access_token"):
                    if use_proxy != self.use_proxy:
                        print(f"   ℹ️ QQ 机器人{'直连不通，改走系统代理' if use_proxy else '走代理不通，改成直连'}后连上了")
                        self.use_proxy, self.http = use_proxy, session
                    self._token, self._token_url = data["access_token"], url
                    self._token_expire = time.time() + int(data.get("expires_in", 7200))
                    return self._token
                errors.append(f"{url} → {data}")
                break  # 服务器有回应 (比如 Key 不对)，换网络方式也没用
            else:
                continue
            break
        raise RuntimeError("获取 QQ 机器人凭证失败" + _proxy_hint() +
                           "：连不上就检查代理/防火墙，有回应就检查 AppID / AppSecret / IP 白名单。详情：" + "；".join(errors))

    def _headers(self):
        return {"Authorization": f"QQBot {self.token()}", "X-Union-Appid": APP_ID}

    # ---------------- 发消息 ----------------
    def reply(self, openid, text, msg_id, seq=1):
        """被动回复：带上收到的那条消息的 id，同一条消息的第 n 次回复 msg_seq 就填 n"""
        resp = self.http.post(f"{API_BASE}/v2/users/{openid}/messages", headers=self._headers(), timeout=10,
                             json={"content": text[:MAX_REPLY_LEN], "msg_type": 0, "msg_id": msg_id, "msg_seq": seq})
        if resp.status_code >= 300:
            print(f"   ⚠️ QQ 回复失败: {resp.status_code} {resp.text[:200]}")
        return resp.status_code < 300

    # ---------------- 语音 ----------------
    def _download(self, url, suffix=".wav"):
        """把 QQ 的语音附件下到临时文件，返回路径；失败返回 None"""
        if url.startswith("//"):  # 附件地址偶尔是协议相对的
            url = "https:" + url
        try:
            resp = self.http.get(url, timeout=30)
            if resp.status_code >= 300:
                print(f"   ⚠️ QQ 语音下载失败: {resp.status_code}")
                return None
            data = resp.content or b""
            if not data:
                return None
            if len(data) > 20 * 1024 * 1024:  # 语音附件的软上限是 20MB
                print("   ⚠️ QQ 语音文件超过 20MB，跳过")
                return None
            fd, path = tempfile.mkstemp(prefix="qq_voice_", suffix=suffix)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return path
        except Exception as e:
            print(f"   ⚠️ QQ 语音下载出错: {e}")
            return None

    def _whisper(self, voice):
        """本地 Whisper 识别；QQ 转好的 WAV 才能直接读，SILK 本地解不开"""
        path = self._download(voice.get("url") or "")
        if not path:
            return ""
        try:
            with open(path, "rb") as f:
                if f.read(4) != b"RIFF":  # 原始 SILK，本地没有解码器
                    return ""
            import transcriber
            return (transcriber.speech_to_text(path) or "").strip()
        except Exception as e:
            print(f"   ⚠️ QQ 语音识别出错: {e}")
            return ""
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _voice_text(self, voice):
        """语音消息 → 文字：auto 先信 QQ、没有再用本地模型；qq 只信 QQ；whisper 总是用本地模型"""
        asr = voice.get("asr") or ""
        if self.voice_stt != "whisper" and asr:
            return asr
        if self.voice_stt == "qq":
            return ""  # 只信 QQ 的结果，不去加载本地模型 (慢机器 / 不想下模型时用)
        text = self._whisper(voice)
        return text or asr

    def _synthesize(self, text):
        """合成一条语音 (只合成，不播放)：默认走实时模型，失败退回原来的朗读"""
        spoken = text
        try:
            import tts
            spoken = tts._speakable(text)  # 别把括号动作、markdown、横杠念出来
        except Exception:
            pass
        if not spoken:
            return None
        if self.voice_engine != "tts":
            try:
                import realtime
                path = realtime.synthesize(spoken)
                if path:
                    return path
                print("   ⚠️ 实时语音没生成出来，改用朗读合成")
            except Exception as e:
                print(f"   ⚠️ 实时语音合成不可用: {e}")
        try:
            import tts
            return tts.synthesize(spoken)
        except Exception as e:
            print(f"   ⚠️ QQ 语音合成不可用: {e}")
            return None

    def upload_voice(self, openid, path):
        """上传语音文件换 file_info；失败返回 None"""
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            print(f"   ⚠️ 读不到要发的语音: {e}")
            return None
        payload = {
            "file_type": 3,   # 3 = 语音条 (silk/mp3/wav/ogg)
            "file_name": os.path.basename(path),
            "file_data": base64.b64encode(data).decode("ascii"),
            "srv_send_msg": False,  # 只上传，等会儿当被动回复发，不占主动消息额度
        }
        try:
            resp = self.http.post(f"{API_BASE}/v2/users/{openid}/files", headers=self._headers(),
                                  json=payload, timeout=60)
        except Exception as e:
            print(f"   ⚠️ QQ 语音上传出错: {e}")
            return None
        if resp.status_code >= 300:
            print(f"   ⚠️ QQ 语音上传失败: {resp.status_code} {resp.text[:200]}")
            return None
        try:
            return (resp.json() or {}).get("file_info")
        except ValueError:
            return None

    def reply_voice(self, openid, path, msg_id, seq=1):
        """被动回复一条语音条：先上传拿 file_info，再用 msg_type=7 发出去"""
        file_info = self.upload_voice(openid, path)
        if not file_info:
            return False
        resp = self.http.post(f"{API_BASE}/v2/users/{openid}/messages", headers=self._headers(), timeout=10,
                              json={"msg_type": 7, "media": {"file_info": file_info},
                                    "msg_id": msg_id, "msg_seq": seq})
        if resp.status_code >= 300:
            print(f"   ⚠️ QQ 语音回复失败: {resp.status_code} {resp.text[:200]}")
        return resp.status_code < 300

    def send_answer(self, openid, answer, msg_id, as_voice):
        """把回复发出去：语音条 + (太长的话) 文字补发；语音发失败就整段发文字"""
        answer = (answer or "").strip()
        if not answer:
            return
        seq = 1
        remaining = answer
        if as_voice:
            spoken, rest = qq_voice.split_voice_reply(answer, self.voice_max_chars)
            path = self._synthesize(spoken)
            sent = False
            if path:
                try:
                    if qq_voice.voice_file_ok(path):
                        sent = self.reply_voice(openid, path, msg_id, seq)
                    else:
                        seconds = qq_voice.wav_seconds(path)
                        size = os.path.getsize(path) / 1024 / 1024
                        print(f"   ⚠️ 这条语音 {seconds:.0f} 秒 / {size:.1f}MB，超过 QQ 语音条限制，改发文字")
                finally:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                # 已经动过 seq 1 了，后面用 2 起步：就算这次发送半路失败，
                # 也不会因为 msg_id + msg_seq 重复被 QQ 去重
                seq += 1
                remaining = rest if sent else answer  # 语音没发成，就别让她白等，整段用文字回
        for part in qq_voice.split_text(remaining, MAX_REPLY_LEN, MAX_REPLIES - (seq - 1)):
            if not self.reply(openid, part, msg_id, seq):
                break
            seq += 1

    # ---------------- 收消息 (WebSocket 长连接) ----------------
    def start(self):
        if not self.configured:
            return False
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def stop(self):
        self._stop.set()
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def _run(self):
        backoff = 5
        while not self._stop.is_set():
            try:
                self._session()
                backoff = 5
            except Exception as e:
                print(f"   ⚠️ QQ 机器人连接断开: {e}，{backoff} 秒后重连")
            self.ready.clear()
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 300)

    def _session(self):
        gateway = self.http.get(f"{API_BASE}/gateway", headers=self._headers(), timeout=10).json()
        if not gateway.get("url"):
            raise RuntimeError(f"拿不到长连接地址: {gateway}")
        options = {} if self.use_proxy else {"http_no_proxy": [urlparse(gateway["url"]).hostname]}  # 直连时别让它读环境变量里的代理
        self.ws = websocket.create_connection(gateway["url"], timeout=60, **options)
        hello = json.loads(self.ws.recv())
        interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000

        if self.session_id:  # 断线重连：接着上次的会话，不漏消息
            self._ws_send({"op": 6, "d": {"token": f"QQBot {self.token()}", "session_id": self.session_id, "seq": self.seq}})
        else:
            self._ws_send({"op": 2, "d": {"token": f"QQBot {self.token()}", "intents": INTENT_GROUP_AND_C2C,
                                          "shard": [0, 1], "properties": {}}})

        alive = threading.Event()
        threading.Thread(target=self._heartbeat, args=(interval, alive), daemon=True).start()
        try:
            while not self._stop.is_set():
                raw = self.ws.recv()
                if not raw:
                    break
                if not self._handle(json.loads(raw)):
                    break
        finally:
            alive.set()
            try:
                self.ws.close()
            except Exception:
                pass

    def _heartbeat(self, interval, stop):
        while not stop.wait(interval):
            try:
                self._ws_send({"op": 1, "d": self.seq})
            except Exception:
                return

    def _ws_send(self, payload):
        with self._send_lock:
            self.ws.send(json.dumps(payload))

    def _handle(self, msg):
        """处理一条长连接消息；返回 False 表示要断开重连"""
        op = msg.get("op")
        if msg.get("s"):
            self.seq = msg["s"]
        if op == 0:
            event, data = msg.get("t"), msg.get("d") or {}
            if event == "READY":
                self.session_id = data.get("session_id")
                self.ready.set()
                print(f"   💬 QQ 机器人已上线 ({data.get('user', {}).get('username', '')})")
            elif event == "RESUMED":
                self.ready.set()
            elif event == "C2C_MESSAGE_CREATE":
                threading.Thread(target=self._on_c2c, args=(data,), daemon=True).start()
        elif op == 7:   # 服务端要求重连
            return False
        elif op == 9:   # 会话失效，重新登录
            self.session_id, self.seq = None, None
            return False
        return True

    def _on_c2c(self, data):
        author = data.get("author") or {}
        openid = author.get("user_openid") or author.get("id", "")
        text = (data.get("content") or "").strip()
        msg_id = data.get("id")
        voice = qq_voice.pick_voice(data.get("attachments"))
        if qq_voice.placeholder_text(text):
            text = ""  # "[语音]" 之类的占位，别当成一句话回
        name = self.allowed.get(openid)
        if not name:
            print(f"   🔒 陌生人的 QQ 消息 (身份码 {openid})，已忽略")
            self.reply(openid, f"你好呀~我是{character.name()}，不过我还不认识你哦。\n你的身份码是：{openid}\n"
                               f"如果你是我的家人，请在 .env 的 QQ_ALLOWED_USERS 里加上「{openid}:你的名字」~", msg_id)
            return

        from_voice = False
        if not text and voice:
            text = self._voice_text(voice)
            if not text:
                self.reply(openid, "呀，这条语音我没听清…可以再说一遍，或者打字告诉我~", msg_id)
                return
            from_voice = True
            print(f"\n📱 QQ 上 {name} 发来语音: {text}")
        elif not text:
            self.reply(openid, "呀，我现在只看得懂文字和语音消息哦~", msg_id)
            return
        else:
            print(f"\n📱 QQ 上 {name} 说: {text}")

        try:
            answer = self.on_message(name, text)
        except Exception as e:
            print(f"   ⚠️ QQ 消息处理出错: {e}")
            answer = "呜…我刚刚脑子卡了一下，你再说一遍好不好？"
        if answer:
            self.send_answer(openid, answer, msg_id,
                             qq_voice.wants_voice_reply(self.voice_reply, from_voice))
            print(f"   📤 QQ 回复 {name}: {answer}")


bot = None


def start(on_message):
    """主程序启动时调用；没配置 AppID/Secret 就什么都不做"""
    global bot
    bot = QQBot(on_message)
    if not ENABLED or not bot.configured:
        return False
    if not bot.allowed:
        print("   ℹ️ QQ 机器人已配置，但 QQ_ALLOWED_USERS 还是空的：先用手机 QQ 给机器人发条消息拿到身份码")
    print("   💬 正在连接 QQ 机器人...")
    return bot.start()
