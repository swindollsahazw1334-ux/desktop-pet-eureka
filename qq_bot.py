"""
QQ 官方机器人：不在电脑前也能在手机 QQ 上找尤里卡聊天

    - 走 QQ 开放平台的官方接口 (合规，不会封号)，用 WebSocket 长连接收消息，家里电脑不需要公网 IP
    - 只和白名单里的人聊 (QQ_ALLOWED_USERS)，陌生人只会收到一句 "我还不认识你" 和加白名单用的身份码
    - 同一个她：人设、记忆、任务清单、你们的关系都和电脑上通用
    - 远程只开放适合离开电脑时用的工具：任务清单、记事、备忘、查天气、联网搜索

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
"""
import urllib.request
from urllib.parse import urlparse
import json
import os
import sys
import threading
import time

import requests
import websocket
from dotenv import load_dotenv

import character


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(get_app_path(), ".env"))


def _env(name, default=None):
    value = (os.getenv(name) or "").strip()
    return default if not value or value.startswith("#") else value


ENABLED = (_env("QQ_BOT_ENABLED", "false") or "").lower() in ("1", "true", "yes", "on")
APP_ID = _env("QQ_BOT_APPID")
APP_SECRET = _env("QQ_BOT_SECRET")
TOKEN_URLS = [_env("QQ_BOT_TOKEN_URL", "https://bots.qq.com/app/getAppAccessToken"),
              "https://api.bot.qq.com/app/getAppAccessToken"]  # 文档里出现过两种域名，第一个不通就试第二个
API_BASE = _env("QQ_BOT_API", "https://api.sgroup.qq.com")
INTENT_GROUP_AND_C2C = 1 << 25
PROXY_MODE = (_env("QQ_BOT_PROXY", "auto") or "auto").lower()


def _make_session(use_proxy):
    session = requests.Session()
    session.trust_env = use_proxy  # False：不管系统/环境变量里的代理，直接连
    return session


def _proxy_hint():
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}
    return f"（检测到系统代理 {proxies.get('https') or proxies.get('http')}）" if proxies else ""
MAX_REPLY_LEN = 500


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
        openid = (data.get("author") or {}).get("user_openid") or (data.get("author") or {}).get("id", "")
        text = (data.get("content") or "").strip()
        msg_id = data.get("id")
        name = self.allowed.get(openid)
        if not name:
            print(f"   🔒 陌生人的 QQ 消息 (身份码 {openid})，已忽略")
            self.reply(openid, f"你好呀~我是{character.name()}，不过我还不认识你哦。\n你的身份码是：{openid}\n"
                               f"如果你是我的家人，请在 .env 的 QQ_ALLOWED_USERS 里加上「{openid}:你的名字」~", msg_id)
            return
        if not text:
            self.reply(openid, "呀，我现在只看得懂文字消息哦~", msg_id)
            return
        print(f"\n📱 QQ 上 {name} 说: {text}")
        try:
            answer = self.on_message(name, text)
        except Exception as e:
            print(f"   ⚠️ QQ 消息处理出错: {e}")
            answer = "呜…我刚刚脑子卡了一下，你再说一遍好不好？"
        if answer:
            # 太长就分成两条发 (QQ 每条消息最多被动回复 4 次)
            parts = [answer[i:i + MAX_REPLY_LEN] for i in range(0, len(answer), MAX_REPLY_LEN)][:4]
            for seq, part in enumerate(parts, start=1):
                self.reply(openid, part, msg_id, seq)
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
