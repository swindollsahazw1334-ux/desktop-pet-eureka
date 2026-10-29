import time
import sys
import recorder
import ai_brain
import nudges
import tts
import skills
import wakeword
import webbrowser
import json
import observer
import events
import realtime
import memory_store
import companion as companion_mod
import tasks
import activity
import inner_life
import relationship
import qq_bot
import character
import notify
import usage
import threading
from datetime import datetime
import os
import pygame # 必须导入这个来停止声音
import ctypes

try:
    # 告诉 Windows：Python 是高分屏感知的，把真实的 4K 物理像素交出来！(截图要用)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

def get_app_path():
    """获取程序真实运行目录"""
    if getattr(sys, 'frozen', False):
        # 这里的路径就是 exe 所在的文件夹
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# 第一次运行还没有软件路径表时，从示例复制一份 (apps.json 是每个人自己的，不进仓库)
if not os.path.exists(os.path.join(get_app_path(), "apps.json")):
    try:
        import shutil
        shutil.copy(os.path.join(get_app_path(), "apps.example.json"), os.path.join(get_app_path(), "apps.json"))
    except OSError:
        pass

# ==========================================
# 设置读写 (settings.json)
# ==========================================
DEFAULT_SETTINGS = {
    "vad_threshold": 500,
    "wake_sensitivity": 0.5,
    "news_topic": "今日科技社会热点新闻",
    "enable_daily_broadcast": True,
    "enable_observer": True,
    "whisper_model": "small",
    "voice_mode": "omni",       # omni: 千问 Omni 实时语音对话；classic: 本地识别 + 文字模型 + 语音合成
    "allow_barge_in": False,    # 实时对话时允许插话打断 (外放会录到她自己的声音，戴耳机再开)
    "enable_activity": True,    # 统计电脑使用时长 (隐私设置)
    "allow_screen": True,       # 允许 "看看屏幕" (隐私设置)
    "daily_omni_minutes": 60,   # 实时语音当天超过这么多分钟提醒一次
    "setup_done": False,
    "do_not_disturb": False,    # 免打扰：不主动开口 (专注结束提醒除外)
}

def settings_path():
    return os.path.join(get_app_path(), "settings.json")

def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), 'r', encoding='utf-8') as f:
            settings.update(json.load(f))
    except Exception:
        pass
    return settings

def save_settings(updates):
    """只改传进来的几项，其余设置保持原样"""
    settings = load_settings()
    settings.update(updates)
    with open(settings_path(), 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    return settings

# ==========================================
# Global State & Interrupt Logic
# ==========================================
IS_INTERRUPTED = False  # 全局中断标志
PASSIVE_EVENT_TEXT = None # 被动观察触发的环境事件
PENDING_TEXT = None     # 用户打字发来的话
OBSERVER_ENABLED = load_settings().get("enable_observer", True) and load_settings().get("enable_activity", True)
OMNI_SESSION = None     # 正在进行的实时对话会话
OMNI_DISABLED = False   # Key/模型/地址不对时，本次运行不再尝试实时对话
PROACTIVE = None        # 陪伴模块到点了、等着说的事

companion = companion_mod.companion
companion.do_not_disturb = load_settings().get("do_not_disturb", False)
memory_store.on_plans = companion.add_plans   # 记忆整理出 "哪天要做什么"，交给陪伴模块到点追问
_last_companion_poll = 0.0

# 执行很快的工具不念"执行前回应"，最后的总结回复会一并交代
QUIET_TOOLS = {"music", "app", "volume", "browser", "note", "timer", "remember", "tasks"}

def set_status(text, state="busy"):
    events.status(text, state)

def check_interruption():
    """给 wakeword 用的回调"""
    global PASSIVE_EVENT_TEXT, PROACTIVE, _last_companion_poll

    # 1. 手动中断 / 打字输入
    if IS_INTERRUPTED or PENDING_TEXT: return True

    # 2. 陪伴：早安、欢迎回来、计划追问、专注结束……(每秒看一次就够)
    if time.time() - _last_companion_poll >= 1:
        _last_companion_poll = time.time()
        try:
            item = companion.poll(ai_brain.get_last_active_user())
            if item:
                PROACTIVE = item
                return True
        except Exception as e:
            print(f"   ⚠️ 陪伴模块出错: {e}")

    # 2. 用户关掉了"观察我"，就不看窗口了
    if not OBSERVER_ENABLED: return False

    try:
        # 获取纯感官数据 (Heartbeat)，这里只做简单计算，不调 LLM，不会卡麦
        heartbeat = observer.observer.check_environment()

        if heartbeat:
            should_speak, event = nudges.manager.should_interrupt(heartbeat, "neutral")

            # 免打扰 / 专注中 / 全屏 / 刚说过话，就先不唠叨
            if should_speak and companion.allow_observer_nudge():
                companion.note_proactive()
                # 大脑批准干预！先立 Flag 退出监听，出去后再让 LLM 生成文本
                PASSIVE_EVENT_TEXT = heartbeat
                return True

    except Exception as e:
        pass

    return False

def force_stop_everything():
    """GUI 调用：强制停止 (也用作手动唤醒)"""
    global IS_INTERRUPTED
    if OMNI_SESSION is not None:
        # 实时对话中：只打断她正在说的话，会话继续
        print(">>> ✋ 打断实时对话里的发言")
        OMNI_SESSION.interrupt()
        return
    print(">>> 🛑 收到强制中断指令！")
    tts.stop()
    IS_INTERRUPTED = True

def submit_text(text):
    """GUI 调用：用打字代替说话"""
    global PENDING_TEXT
    text = (text or "").strip()
    if text:
        PENDING_TEXT = text
        tts.stop()  # 正在说话就先停下来听你的

def note_interaction(kind, user=None):
    """互动让她开心、也让你们更亲近：chat / pat / poke / focus_done / task_done"""
    inner_life.life.on_event(kind)
    relationship.bond.add(user or ai_brain.get_last_active_user(), kind)

def on_pet_touch(kind):
    """GUI 调用：摸头 (pat) / 戳 (poke)"""
    note_interaction(kind)

def relationship_summary():
    """GUI "我们的关系" 菜单显示的文字"""
    user = ai_brain.get_last_active_user()
    return (f"💗 {relationship.bond.summary(user)}\n"
            f"她现在{inner_life.life.doing_now()}，心情{inner_life.life.mood_label()}，{inner_life.life.energy_label()}")

def add_tasks(items):
    """GUI 功能面板：直接往今天的任务清单里加 (不经过大模型)"""
    return tasks.board.add(ai_brain.get_last_active_user(), items)

def start_focus(minutes, task=""):
    """GUI 功能面板：直接开始专注计时"""
    return companion.start_focus(minutes, task)

def stop_focus():
    return companion.stop_focus()

def today_summary():
    """GUI 功能面板："今天干了啥" 显示的文字"""
    user = ai_brain.get_last_active_user()
    return (f"📋 任务：{tasks.board.describe(user)}\n💻 电脑上：{activity.tracker.describe_today()}\n"
            f"☁️ 用量：{usage.describe_today()}")

def life_state():
    """GUI 待机小动作用：(心情, 精力)"""
    return inner_life.life.mood(), inner_life.life.energy()

def set_do_not_disturb(enabled):
    """GUI 调用：免打扰 (不主动开口)"""
    companion.do_not_disturb = bool(enabled)
    save_settings({"do_not_disturb": bool(enabled)})
    print(f"   🔕 免打扰已{'开启' if enabled else '关闭'}")

def set_barge_in(enabled):
    """GUI 调用：实时对话时是否允许插话 (戴耳机时开)"""
    save_settings({"allow_barge_in": bool(enabled)})
    if OMNI_SESSION is not None:
        OMNI_SESSION.allow_barge_in = bool(enabled)
    print(f"   🎧 插话打断已{'开启' if enabled else '关闭'}")

def set_observer_enabled(enabled):
    """GUI 调用：开关"观察我" (行为观察)"""
    global OBSERVER_ENABLED
    OBSERVER_ENABLED = bool(enabled)
    save_settings({"enable_observer": OBSERVER_ENABLED})
    print(f"   👀 行为观察已{'开启' if OBSERVER_ENABLED else '关闭'}")

def is_stop():
    """辅助函数：检查是否应该停手"""
    if IS_INTERRUPTED:
        print(">>> 🛑 检测到中断信号，任务终止。")
        return True
    return False

# ==========================================
# Core Functions
# ==========================================

def _preload_classic_models():
    try:
        import transcriber
        transcriber.ensure_model()
        import voiceprint  # noqa: F401
    except Exception as e:
        print(f"   ⚠️ 预加载识别模型失败: {e}")


def run_eureka():
    global IS_INTERRUPTED, PASSIVE_EVENT_TEXT, PENDING_TEXT, PROACTIVE

    print("==================================================")
    print(f"桌宠 {character.name()} 已启动")
    print("==================================================")

    IS_INTERRUPTED = False

    # 手机 QQ 上也能找她聊 (配置了 QQ 机器人才会启动)
    qq_bot.start(reply_remote)

    # 经典模式要用本地识别和声纹：启动后在后台先悄悄加载好，免得第一句话等很久
    if load_settings().get("voice_mode", "omni") == "classic":
        threading.Thread(target=_preload_classic_models, daemon=True).start()

    # 后台开始记工作统计；界面显示今天的任务进度
    if load_settings().get("enable_activity", True):
        activity.tracker.start()
    tasks.board.refresh(ai_brain.get_last_active_user())

    # 旧档案 (memory.json 的 user_profiles) 第一次运行时搬进新记忆库，只做一次，后台进行
    threading.Thread(target=memory_store.store.migrate_old_profiles,
                     args=(ai_brain.MEMORY.get("user_profiles", {}),), daemon=True).start()

    set_status("正在检查日期...")
    print("   📅 正在检查重要日期...")
    birthday_wish = ai_brain.check_birthday()

    if birthday_wish:
        print(f"   🎉 生日祝福: {birthday_wish}")
        events.expression("3clever")
        tts.speak(birthday_wish)
    else:
        daily_broadcast()
    if birthday_wish or load_settings().get("enable_daily_broadcast", True):
        companion.state["last_morning"] = datetime.now().date().isoformat()  # 已经打过招呼，今天不再说早安

    audio_path = os.path.join(get_app_path(), "input.wav")

    while True:
        # --- 每次循环开始，重置中断标志 ---
        IS_INTERRUPTED = False
        tts.reset()

        current_settings = load_settings()
        threshold = current_settings.get("vad_threshold", 500)
        sensitivity = current_settings.get("wake_sensitivity", 0.5)

        # 1. 等待唤醒 (喊名字 / 双击 / 打字 / 观察事件 都会让它返回)
        if not PENDING_TEXT:
            set_status(f"等待唤醒 (灵敏度: {sensitivity})...", "idle")
            wake_success = wakeword.wait_for_wake_word(check_interrupt=check_interruption, sensitivity=sensitivity)
        else:
            wake_success = False

        # 情况 A: 打字输入，跳过录音和识别
        if PENDING_TEXT:
            user_text, PENDING_TEXT = PENDING_TEXT, None
            IS_INTERRUPTED = False
            tts.reset()
            print(f"\n⌨️ 用户输入: {user_text}")
            handle_user_text(user_text)
            continue

        # 情况 B0: 陪伴模块到点了，主动开口
        if PROACTIVE:
            item, PROACTIVE = PROACTIVE, None
            deliver_proactive(item, current_settings)
            continue

        # 情况 B: 被动观察触发了
        if PASSIVE_EVENT_TEXT:
            heartbeat_data = PASSIVE_EVENT_TEXT
            PASSIVE_EVENT_TEXT = None

            # check_interruption 已经做过决策，这里直接让 Brain 生成回复
            print(f"   👀 收到环境事件，准备生成回复...")
            result = nudges.generate_reaction(
                heartbeat_data,
                current_user=ai_brain.get_last_active_user()
            )

            if result:
                set_status(f"👀 {result['event_type']}")
                print(f"<<< AI反应: {result['text']}")

                if result['event_type'] == 'late_night_coding':
                    events.expression("6i gi a ri")
                elif result['event_type'] == 'distraction_video':
                    events.expression("3clever")
                else:
                    events.expression("5QAQ")

                tts.speak(result['text'])

            continue

        # 情况 C: 手动唤醒 (双击/菜单)
        if IS_INTERRUPTED:
             print(">>> 🔘 手动唤醒触发")
             IS_INTERRUPTED = False
             tts.reset()

        # 情况 D: 既没被动触发，也没手动唤醒，唤醒也没成功 -> 误触，继续听
        elif not wake_success:
             continue

        # --- 下面是正常的语音唤醒流程 ---
        print(f"   ✨ 被唤醒了！")

        # 播放唤醒音效
        try:
            tts.ensure_mixer()
            pygame.mixer.music.load(os.path.join(getattr(sys, "_MEIPASS", get_app_path()), "assets", "ding.wav"))
            pygame.mixer.music.play()
        except: pass

        # 实时对话：她直接听、直接说，可以连着聊，不用每句都喊名字
        if current_settings.get("voice_mode", "omni") == "omni" and not OMNI_DISABLED:
            if run_omni_session(current_settings):
                continue

        set_status("🔴 正在录音...", "listening")

        if not recorder.record_audio(threshold=threshold, stop_check=is_stop):
            print("录音失败、未检测到语音或被手动打断，重试...")
            continue

        if is_stop(): continue

        # 声纹识别：认出是谁在说话，自动切换档案
        set_status("🔍 正在核验声纹...", "recognizing")
        try:
            import voiceprint  # 用到时才加载 (要用 PyTorch，比较慢)
            speaker = voiceprint.vp_manager.identify_user(audio_path)

            if speaker and speaker != "unknown":
                current_user = ai_brain.get_last_active_user()
                if speaker != current_user:
                    print(f"\n🔄 [声纹识别] 侦测到用户变更: {current_user} -> {speaker}")
                    ai_brain.set_last_active_user(speaker)
                    events.thought(f"是{speaker}呀，切换到 {speaker} 的专属档案~")
                    tasks.board.refresh(speaker)
            elif speaker == "unknown":
                print("\n❓ [声纹识别] 未知声纹，维持当前状态。")
        except Exception as e:
            print(f"\n⚠️ 声纹模块跳过: {e}")

        # 语音转文字
        set_status("📝 正在识别...", "recognizing")
        import transcriber
        user_text = transcriber.speech_to_text(audio_path)
        if not user_text or len(user_text) < 1:
            continue

        print(f"\n🗣️ 用户说: {user_text}")
        if is_stop(): continue

        handle_user_text(user_text)


# ==========================================
# 不在电脑前：手机 QQ 上找她聊天
# ==========================================
_ctx = threading.local()  # 当前线程在替谁处理 (QQ 上的消息不一定是电脑前的人)
REMOTE_TOOLS = {"tasks", "remember", "note", "weather", "search_chat"}
REMOTE_SCENE = """
    【现在的场景】：TA 在用聊天软件给你发消息。像发消息一样回复：口语、简短（一般一到三句），
    可以带一两个颜文字。你手头只有任务清单、记住信息、备忘、查天气、联网搜索这些工具；
    放歌、开软件、看屏幕这类电脑上的事，等TA回到电脑前再做。
"""


def current_user():
    return getattr(_ctx, "user", None) or ai_brain.get_last_active_user()


def reply_remote(user_name, text):
    """QQ 上来的一句话：同样的人设、记忆和任务，只开放远程能用的工具，返回要回的文字"""
    _ctx.user, _ctx.remote = user_name, True
    try:
        tools = [t for t in ai_brain.get_eureka_tools() if t["function"]["name"] in REMOTE_TOOLS]
        messages = [
            {"role": "system", "content": ai_brain.get_agent_system_prompt(text, user_name) + REMOTE_SCENE},
            {"role": "user", "content": f"【近期对话上下文】:\n{ai_brain.history_context(4, user_name)}\n\n当前用户最新消息（来自手机 QQ）: {text}"},
        ]
        reply, notes = "", []
        for _ in range(4):
            message = ai_brain.analyze_intent(messages, tools=tools)
            if not message:
                break
            messages.append(message)
            if not message.get("tool_calls"):
                reply = message.get("content") or ""
                break
            for call in message["tool_calls"]:
                name = call["function"]["name"]
                try:
                    intent = json.loads(call["function"]["arguments"] or "{}")
                except Exception:
                    intent = {}
                result = run_tool(name, intent) if name in REMOTE_TOOLS else f"{name} 只能在电脑前用"
                notes.append(f"[{name}: {result}]")
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": str(result)})

        m = ai_brain._EMOTION_TAG.match(reply)
        if m:
            reply = reply[m.end():]
        reply = reply.strip() or "嗯嗯，我在呢。"

        ai_brain.update_memory(f"（QQ）{text}", " ".join(notes + [reply]), user_name)
        note_interaction("chat", user_name)
        memory_store.add_turn_async(user_name, text, reply)
        return reply
    finally:
        _ctx.user, _ctx.remote = None, False


def deliver_proactive(item, settings):
    """陪伴模块到点了：现编一句主动开口的话念出来；实时模式下念完直接接着听，TA 不用再喊名字就能回话"""
    user = ai_brain.get_last_active_user()
    if item["kind"] == "focus_done":
        note_interaction("focus_done", user)
    line = ai_brain.generate_proactive_line(item["kind"], item.get("detail"), user)
    if not line:
        return
    m = ai_brain._EMOTION_TAG.match(line)
    if m:
        expression = ai_brain.emotion_to_expression(m.group(1))
        if expression:
            events.expression(expression)
        line = line[m.end():].strip()
    print(f"<<< 💬 主动开口 ({item['kind']}): {line}")
    tts.speak(line)
    ai_brain.remember_exchange(f"（{character.name()}主动开口）", line, user)
    if is_stop():
        return
    if settings.get("voice_mode", "omni") == "omni" and not OMNI_DISABLED:
        run_omni_session(settings, opening=line)


def run_omni_session(settings, opening=None):
    """开一次实时对话，聊到没人说话为止；成功返回 True，连不上返回 False (调用方退回经典模式)"""
    global OMNI_SESSION, OMNI_DISABLED
    current_user = ai_brain.get_last_active_user()

    def on_turn(user_text, reply):
        # 已经在后台线程里了：记进短期对话，再整理进长期记忆
        ai_brain.update_memory(user_text, reply, current_user)
        note_interaction("chat", current_user)
        memory_store.store.add_turn(current_user, user_text, reply)

    session = realtime.OmniSession(
        instructions=ai_brain.get_realtime_instructions() + (
            f"    【你刚才主动对TA说了】：{opening}\n    现在等TA回应，顺着这个话题自然地聊；TA没接话也没关系。\n"
            if opening else ""),
        tools=ai_brain.get_eureka_tools(),
        run_tool=run_tool,
        should_stop=lambda: PENDING_TEXT is not None,
        on_turn=on_turn,
        allow_barge_in=settings.get("allow_barge_in", False),
    )
    OMNI_SESSION = session
    try:
        session.run()
        return True
    except realtime.OmniUnavailable as e:
        print(f"   ⚠️ 实时语音不可用，这次改用经典模式: {e}")
        notify.report(e, "实时语音")
        if any(w in str(e) for w in ("连接被拒绝", "没有配置", "没有建立会话")):
            OMNI_DISABLED = True
        return False
    except Exception as e:  # 比如麦克风打不开
        notify.report(e, "实时语音")
        return False
    finally:
        OMNI_SESSION = None
        set_status("等待唤醒...", "idle")


def tool_speak(text):
    """工具执行时插一句话；实时对话中由 Omni 自己说、QQ 上的人听不到，这两种情况就不出声"""
    if OMNI_SESSION is None and not getattr(_ctx, "remote", False):
        tts.speak(text)


def say_ack(action, intent, default):
    """耗时工具先念一句"执行前回应"垫场，快的工具就不念了"""
    if action not in QUIET_TOOLS:
        tool_speak(intent.get('ack', default))


def handle_user_text(user_text):
    """ReAct 思考循环：理解 -> 调工具 -> 看结果 -> ... -> 边想边说出最终回复"""
    current_user = ai_brain.get_last_active_user()
    print(f"👤 当前用户：{current_user}")

    set_status("🧠 正在思考...", "thinking")

    # 检查名字唤醒更新
    for user in ai_brain.MEMORY.get("owners", []):
        if user["name"] in user_text:
            ai_brain.set_last_active_user(user["name"])
            break
    current_user = ai_brain.get_last_active_user()  # 名字切换过档案的话，短期记忆也跟着这个人走
    if is_stop(): return

    print("\n>>> 🧠 Agent 启动 ReAct 思考引擎...")

    system_prompt = ai_brain.get_agent_system_prompt(user_text)

    # 拼装短期历史对话 (更早的摘要 + 最近几句)
    history_str = f"【近期对话上下文】:\n{ai_brain.history_context(4, current_user)}\n"

    messages_thread = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{history_str}\n当前用户最新指令: {user_text}"}
    ]

    loop_count = 0
    max_loops = 5 # 防止死循环
    final_summary = [] # 用于最后存入向量记忆

    while loop_count < max_loops:
        loop_count += 1
        if is_stop(): break

        # 1. 询问大模型：回复文字一边生成一边念
        speech = tts.SpeechStream()
        tag_filter = ai_brain.EmotionTagFilter(events.expression)
        ai_message = ai_brain.analyze_intent(
            messages_thread,
            on_text=lambda delta: speech.feed(tag_filter.feed(delta)),
            should_stop=lambda: IS_INTERRUPTED,
        )
        speech.feed(tag_filter.flush())
        spoken = speech.finish()
        if not ai_message: break

        messages_thread.append(ai_message)

        # 2. 调用了工具：逐个执行，把结果喂回去再想一轮
        if ai_message.get("tool_calls"):
            print(f"   ⚙️ [思考周期 {loop_count}]: 大脑决定调用 {len(ai_message['tool_calls'])} 个工具")

            for tool_call in ai_message["tool_calls"]:
                if is_stop(): break
                action = tool_call["function"]["name"]
                try:
                    intent = json.loads(tool_call["function"]["arguments"] or "{}")
                except:
                    intent = {}

                set_status(f"🚀 执行: {action}", "acting")
                executed_summary = run_tool(action, intent)

                print(f"      👀 观察结果: {executed_summary}")
                final_summary.append(executed_summary)

                # 闭环核心：把执行结果作为 role="tool" 传回给大脑
                messages_thread.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": action,
                    "content": str(executed_summary)
                })

            set_status("🧠 正在思考...", "thinking")
            continue

        # 3. 没有工具调用：这就是最终回复 (已经边生成边念完了)
        if spoken:
            print(f"<<< 🏁 Agent 最终决策回复: {spoken}")
            final_summary.append(f"AI最终回复：{spoken}")

        if final_summary:
            ai_brain.update_memory(user_text, " | ".join(final_summary), current_user)

        note_interaction("chat")
        # 后台整理长期记忆：提炼事实，和旧记忆比对后增/改/删
        memory_store.add_turn_async(current_user, user_text, spoken or " | ".join(final_summary))
        break


def run_tool(action, intent):
    """执行一个工具，返回给大模型看的观察结果"""
    executed_summary = f"{action} 执行成功" # 默认观察结果

    if action == "music":
        keyword = intent.get("keyword", "")
        say_ack(action, intent, '准备为你播放音乐。')
        skills.play_music(keyword)
        executed_summary = f"已开始播放音乐：{keyword if keyword else '默认歌单'}"

    elif action == "app":
        app_name = intent.get("name", "")
        say_ack(action, intent, f'没问题，正在启动 {app_name}！')

        executed_summary = f"执行失败：未找到 {app_name} 的路径配置。"
        apps_config_path = os.path.join(get_app_path(), "apps.json")

        try:
            # 1. 尝试从你的 GUI 配置的 apps.json 读取路径
            if os.path.exists(apps_config_path):
                with open(apps_config_path, 'r', encoding='utf-8') as f:
                    apps_dict = json.load(f)

                # 寻找名字匹配的软件 (支持模糊匹配，比如你说"网易云"，配置里是"网易云音乐")
                target_path = None
                for key, path in apps_dict.items():
                    if key.lower() in app_name.lower() or app_name.lower() in key.lower():
                        target_path = path
                        break

                if target_path and os.path.exists(target_path):
                    os.startfile(target_path)
                    executed_summary = f"已通过系统底层成功唤醒 {app_name}"
                else:
                    executed_summary = f"执行失败：虽然在配置里找到了 {app_name}，但填写的路径无效或文件不存在。"
                    print(f"   ❌ 路径无效: {target_path}")
            else:
                executed_summary = "执行失败：没有找到 apps.json 配置文件，请先在 [系统配置] 里添加软件路径。"

        except Exception as e:
            executed_summary = f"启动软件报错: {e}"
            print(f"   ❌ 启动软件报错: {e}")

    elif action == "bilibili":
        keyword = intent.get("keyword", "")
        target = intent.get("target", "search")
        say_ack(action, intent, '这就去B站瞧瞧！')

        if target == "rank":
            result = skills.get_bilibili_rank_video()
            if result:
                title, author, url = result
                tool_speak(f"热门第一是UP主{author}的：{title}。")
                webbrowser.open(url)
                executed_summary = f"打开了热门视频《{title}》"
        elif target == "recommend":
            smart_query = ai_brain.generate_recommend_query(keyword)
            result = skills.search_video_return_first(smart_query)
            if result:
                title, author, url = result
                if OMNI_SESSION is None:
                    tool_speak(ai_brain.generate_verbal_reply(f"找到视频《{title}》"))
                webbrowser.open(url)
                executed_summary = f"智能推荐并播放了B站视频《{title}》"
            else:
                executed_summary = "未找到合适视频，打开了搜索页"
                webbrowser.open(f"https://search.bilibili.com/all?keyword={keyword}")

    elif action == "weather":
        city = intent.get("city", "当地")
        say_ack(action, intent, f'正在查询{city}天气...')
        info = skills.get_weather(city)
        # 把查到的天气作为 observation 喂给大模型
        executed_summary = f"查询到的天气详情：{info}"

    elif action == "search_chat":
        keyword = intent.get("keyword")
        say_ack(action, intent, f'正在全网检索 {keyword}...')
        search_context = skills.web_search_fetch(keyword)
        # 将网页抓取结果喂回给大模型，让它自己总结
        executed_summary = f"网页搜索结果原始内容如下：\n{search_context[:800]}..." if search_context else "网页搜索失败"

    elif action == "screen" and not load_settings().get("allow_screen", True):
        executed_summary = "用户在隐私设置里关掉了「看看屏幕」，没有截图。可以提醒TA在 设置 → 隐私 里打开"

    elif action == "screen":
        query = intent.get("query", "描述截图")
        say_ack(action, intent, '让我看看屏幕上有啥！')
        path = skills.take_screenshot()
        if path:
            try:
                result = ai_brain.analyze_image(path, query)
            finally:
                # 截图可能有隐私内容，分析完立刻删掉
                try:
                    os.remove(path)
                except Exception:
                    pass
            executed_summary = f"屏幕分析结果：{result}"
        else:
            executed_summary = "截图失败"

    elif action == "timer":
        seconds = intent.get("seconds", 0)
        content = intent.get("content", "时间到了")
        if seconds > 0:
            mins = round(seconds / 60, 1)
            say_ack(action, intent, f'闹钟设好啦，{mins}分钟后叫你！')
            skills.start_countdown(seconds, content)
            executed_summary = f"成功设置了 {mins} 分钟的倒计时：{content}"

    elif action == "remember":
        fact = intent.get("fact")
        if fact:
            say_ack(action, intent, '记下啦！')
            ai_brain.save_user_memory(current_user(), fact)
            executed_summary = f"已记进长期记忆：{fact}"

    elif action == "focus":
        if intent.get("action") == "stop":
            done = companion.stop_focus()
            executed_summary = "已结束专注" if done else "现在没有在专注"
        else:
            say_ack(action, intent, '好，我安静陪着你！')
            minutes = companion.start_focus(intent.get("minutes") or 25, intent.get("task", ""))
            executed_summary = f"已开始 {minutes} 分钟专注计时，期间不主动打扰，结束时会提醒休息"

    elif action == "tasks":
        user = current_user()
        board = tasks.board
        task_action = intent.get("action", "list")
        say_ack(action, intent, '好嘞。')
        if task_action == "add":
            added = board.add(user, intent.get("items") or [])
            done, total = board.progress(user)
            executed_summary = (f"已添加：{'、'.join(added)}。" if added else "这些任务已经在清单里了。") + f"今天共 {total} 件，完成 {done} 件。"
        elif task_action in ("done", "undo", "remove"):
            handler = {"done": board.complete, "undo": board.undo, "remove": board.remove}[task_action]
            task = handler(user, intent.get("target", ""))
            done, total = board.progress(user)
            if not task:
                executed_summary = f"清单里没找到「{intent.get('target', '')}」。今天的任务：{board.describe(user)}"
            else:
                verb = {"done": "已完成", "undo": "已改回未完成", "remove": "已删除"}[task_action]
                remaining = board.unfinished(user)
                executed_summary = f"{verb}「{task['text']}」，进度 {done}/{total}。" + (f"还剩：{'、'.join(remaining)}" if remaining else "今天的任务全部完成！")
                if task_action == "done":
                    events.expression("3clever")
                    note_interaction("task_done", user)
        elif task_action == "carry_over":
            moved = board.carry_over(user)
            executed_summary = f"已把昨天没做完的挪到今天：{'、'.join(moved)}" if moved else "昨天没有没做完的任务。"
        elif task_action == "review":
            companion.mark_reviewed()
            d = companion.review_detail(user)
            executed_summary = (f"今天的任务完成 {d['done']}/{d['total']}" + (f"，还没做完：{'、'.join(d['unfinished'])}" if d['unfinished'] else "")
                                + f"；今天在电脑上：{d['activity']}；专注了 {d['focus_count']} 轮。")
        else:
            executed_summary = f"今天的任务：{board.describe(user)}；今天在电脑上：{activity.tracker.describe_today()}"

    elif action == "volume":
        vol_type = intent.get("type", "set")
        value = intent.get("value", 50)
        say_ack(action, intent, '音量调好啦。')
        if skills.control_system_volume(vol_type, value):
            executed_summary = f"音量调节成功（{vol_type} {value if vol_type == 'set' else ''}）"
        else:
            executed_summary = "音量调节失败"

    elif action == "browser":
        keyword = intent.get("keyword", "")
        say_ack(action, intent, '浏览器来咯！')
        if keyword:
            ok = skills.open_browser(keyword)
            executed_summary = f"已在浏览器中搜索：{keyword}" if ok else "打开浏览器失败"
        else:
            webbrowser.open("https://cn.bing.com")
            executed_summary = "已打开浏览器"

    elif action == "note":
        content = intent.get("content", "")
        if content:
            say_ack(action, intent, '帮你记在小本本上啦！')
            ok = skills.save_note(content)
            executed_summary = f"已记入桌面 memo.txt：{content}" if ok else "记录备忘失败"
        else:
            executed_summary = "没有需要记录的内容"

    else:
        executed_summary = f"未知工具或已执行: {action}"

    return executed_summary


def daily_broadcast():
    """每日早报 (支持自定义话题)"""
    if is_stop(): return

    settings = load_settings()
    search_topic = settings.get("news_topic") or DEFAULT_SETTINGS["news_topic"]

    # 开关没开，直接静悄悄地退下
    if not settings.get("enable_daily_broadcast", True):
        print("   🔇 每日早报已在设置中关闭，跳过播报。")
        return

    set_status(f"正在生成关于 {search_topic} 的早报...")
    print(f"   🌅 正在准备每日早报 (话题: {search_topic})...")
    tts.speak(f"早安！正在为您搜集关于 {search_topic} 的最新资讯，请稍候...")

    if is_stop(): return

    weather_info = skills.get_weather("当地")

    if is_stop(): return

    print(f"   🌍 正在抓取: {search_topic}...")
    set_status("正在阅读互联网信息...")

    news_info = skills.web_search_fetch(f"今日 {search_topic}")
    if not news_info:
        news_info = "暂时没有获取到相关新闻。"

    if is_stop(): return

    today_str = datetime.now().strftime("%Y年%m月%d日")

    briefing_prompt = f"""
    今天是 {today_str}。
    【用户关注话题】：{search_topic}
    【天气情况】：{weather_info}
    【搜索结果】：{news_info}

    请你扮演【{character.name()}】，为我播报今天的晨间资讯。
    要求：
    1. 重点总结用户关注的“{search_topic}”相关内容。
    2. 语气元气满满，像贴身秘书一样。
    3. 字数控制在200字左右。
    """

    briefing_text, expression = ai_brain.generate_briefing(briefing_prompt)
    if expression:
        events.expression(expression)

    print(f"   📰 早报稿件: {briefing_text}")

    if is_stop(): return

    # 如果有共享的待定决策，顺便提醒一下
    try:
        pending = ai_brain.get_pending_decisions()
        if pending:
            tts.speak(f"对了，你们还没决定：{pending[0]}")
    except Exception:
        pass

    tts.speak(briefing_text)
    skills.play_music()

if __name__ == "__main__":
    run_eureka()
