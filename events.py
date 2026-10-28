"""
后台 -> 桌宠界面的事件通道

后台 (main / tts) 只管 emit，界面订阅后自己决定怎么显示，
不再靠解析 print 出来的文字来传话。

事件一览 (kind -> data):
    status      text, state       状态变化，state 取值见 STATES
    say         text              她说的一句话 (气泡显示)
    thought     text              内心独白 (灰色气泡)
    expression  name              切换表情 (Live2D 表情名)
    lipsync     envelope, frame_ms   一段语音的音量包络，驱动嘴型
    speak_end                     这段语音播完
"""

STATES = ("idle", "listening", "recognizing", "thinking", "acting", "speaking", "busy")

_listeners = []


def subscribe(callback):
    """callback(kind: str, data: dict)，会在后台线程里被调用"""
    _listeners.append(callback)


def emit(kind, **data):
    for callback in list(_listeners):
        try:
            callback(kind, data)
        except Exception as e:
            print(f"⚠️ 事件分发出错 ({kind}): {e}")


def status(text, state="busy"):
    emit("status", text=text, state=state)


def say(text):
    emit("say", text=text)


def thought(text):
    emit("thought", text=text)


def expression(name):
    emit("expression", name=name)
