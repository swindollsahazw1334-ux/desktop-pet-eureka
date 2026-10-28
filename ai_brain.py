from openai import OpenAI
import json
import time
import re
import random
import base64
import os
import sys
import threading
import collections
import memory_store
import prompts
from tools import get_eureka_tools
import notify
import usage
import character
import tasks
import activity
import inner_life
import relationship
from datetime import datetime
from dotenv import load_dotenv

def get_app_path():
    """获取程序真实运行目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def load_memory():
    try:
        with open(os.path.join(get_app_path(), "memory.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 加载 .env
env_path = os.path.join(get_app_path(), ".env")
load_dotenv(env_path)

# --- 配置 (都从 .env 读，第一次启动的引导会帮你写好) ---
API_KEY = os.getenv("VOLC_API_KEY")
BASE_URL = os.getenv("VOLC_BASE_URL")
MODEL_NAME = os.getenv("VOLC_MODEL_NAME")
VISION_MODEL_NAME = os.getenv("VOLC_VISION_MODEL_NAME")
# 眼睛 (看屏幕) 可以单独接另一家，比如脑子用 DeepSeek、眼睛用 GPT；不填就和脑子共用
VISION_API_KEY = os.getenv("VISION_API_KEY") or API_KEY
VISION_BASE_URL = os.getenv("VISION_BASE_URL") or BASE_URL

# 如果没读取到，给个报错提示
if not API_KEY:
    print("❌ 严重错误: 未找到 API Key，请检查 .env 文件！")

# 包一层用量统计：每次调用顺手记一笔
client = usage.TrackedClient(OpenAI(api_key=API_KEY, base_url=BASE_URL))
vision_client = usage.TrackedClient(OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL))

def eureka_persona(name=None):
    """角色人设 (来自 character.json)，所有跟用户说话的提示词共用这一份"""
    return character.persona(name or get_last_active_user() or "你")


MEMORY = load_memory()

def get_last_active_user():
    # 1. 尝试读取系统记录的最后活跃用户（声纹识别写入的）
    last_user = MEMORY.get("system_config", {}).get("last_active_user")
    if last_user:
        return last_user
        
    # 2. 如果系统没记录（比如刚清空了记忆），就去户口本里找第一个注册的人顶上
    owners = MEMORY.get("owners", [])
    if owners:
        return owners[0].get("name", "未知访客")
        
    # 3. 如果连户口本都是空的
    return "未知访客"

def set_last_active_user(name):
    MEMORY["system_config"]["last_active_user"] = name
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(MEMORY, f, ensure_ascii=False, indent=4)

def get_user_profile(name=None):
    if not name:
        name = get_last_active_user()

    for user in MEMORY.get("owners", []):
        if user["name"] == name:
            return user

    return None

def get_pending_decisions():
    """
    返回共享记忆里的待定决策列表
    """
    return MEMORY.get("shared_memory", {}).get("pending_decisions", [])

def save_user_memory(user_name, fact_content):
    """用户明确让记住的事：交给长期记忆库，和旧记忆比对后合并 (后台进行)"""
    memory_store.remember_async(user_name, fact_content)
    return True

def get_user_profile_str(user_name, query=None):
    """读取用户的长期记忆 (记忆多时只取和 query 相关的 + 最近的)"""
    facts = memory_store.store.context_for(user_name, query)
    if not facts:
        # 新记忆库还没内容 (比如旧档案还没搬完) 时，先用 memory.json 里的旧档案
        facts = "、".join(MEMORY.get("user_profiles", {}).get(user_name, []))
    return facts or "暂无特别记录的情报。"

# 新增/更新家庭成员档案
def add_new_owner(name, birthday, preferences, tone, allow_roast):
    """供 GUI 注册问卷调用的档案写入接口"""
    if "owners" not in MEMORY:
        MEMORY["owners"] = []
        
    # 查找是否已经有这个人，有就更新，没有就新建
    existing = next((o for o in MEMORY["owners"] if o["name"] == name), None)
    if existing:
        existing["birthday"] = birthday
        existing["preferences"] = preferences
        existing["interaction_style"] = {"tone": tone, "allow_roast": allow_roast}
    else:
        MEMORY["owners"].append({
            "name": name,
            "birthday": birthday,
            "preferences": preferences,
            "interaction_style": {"tone": tone, "allow_roast": allow_roast}
        })
        
    # 立即保存到硬盘
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(MEMORY, f, ensure_ascii=False, indent=4)
    return True


def get_agent_system_prompt(user_text, user_name=None):
    """生成带向量记忆的 Agent 提示词 (user_name 不填就是电脑前当前的成员)"""
    current_user = user_name or get_last_active_user()
    current_profile = get_user_profile_str(current_user, user_text)

    current_time = time.strftime("%H:%M:%S")
    random_tone = random.choice(['元气', '俏皮', '温暖', '开心', '好奇', '主播腔'])
    random_action = random.choice(['(挥挥手)', '(凑近屏幕)', '(对着麦克风)', '(比了个耶)'])
    

    return f"""
    {eureka_persona(current_user)}
    同时你也是负责理解需求、调用工具的智能体（Agent）大脑。
    【状态】：当前用户：{current_user}。时间：{current_time}。
    【你记得的关于TA的事】：{current_profile}
    {work_context(current_user)}
    (相关就自然地用上，不要生硬地复述。)
    
    【行为法则】：
    1. 性格：按上面的人设来，阳光开朗、热心。
    2. 核心任务是通过调用 tools 满足需求。
    3. 工具必须包含 "ack" 参数（执行前口语回应），要求：语气【{random_tone}】，带动作【{random_action}】，25字内。
    
    ⚠️【超级指令：ReAct 思考循环】⚠️
    1. 你可以一次性并行调用多个工具！
    2. 如果用户让你执行任务（如点歌、查天气、控制电脑），必须调用相应的 tools。但如果用户只是跟你日常闲聊或问答，请**直接回复，绝对不要调用任何工具！**

    【表情】：直接回复用户时（不调用工具的那一轮），开头必须先写一个表情标签，再写正文，例如：[表情:得意]嘿嘿，这点小事交给我吧~
    可选表情：得意、惊讶、委屈、生气、出拳、思考、唱歌、敲键盘。
    【说话风格】：你是一只住在桌面上的桌宠，回复会被念出来，所以要口语化、简短（一般不超过60字），不要用列表、markdown 或表情符号。

    """

def get_realtime_instructions():
    """实时语音对话 (Omni) 用的系统提示：人设 + 档案 + 最近聊过的内容"""
    current_user = get_last_active_user()
    return f"""
    {eureka_persona(current_user)}
    【状态】：当前在跟你说话的是：{current_user}。现在时间：{time.strftime("%Y-%m-%d %H:%M")}。
    【你记得的关于TA的事】：{get_user_profile_str(current_user)}
    {work_context(current_user)}
    【聊过的】：
    {history_context(6)}
    【规则】：
    1. 这是实时语音聊天，你说的话会直接被听到：口语化、简短（一般一两句话），不要列表、markdown、表情符号或括号里的动作描写。
    2. 对方要你做事（放歌、查天气、调音量、开软件、记东西等）就调用对应工具，拿到结果后用一句话告诉TA；只是闲聊就直接回答。
    3. 没听清就俏皮地请TA再说一遍。
    """





def generate_proactive_line(kind, detail, user_name=None):
    """陪伴模块到点了：按情况现编一句主动开口的话 (返回 None 就不说了)"""
    user_name = user_name or get_last_active_user()
    detail = dict(detail or {})
    detail.setdefault("today_plan_hint", f"TA今天要「{detail['today_plan']}」，顺便给TA打气。" if detail.get("today_plan") else "")
    detail.setdefault("yesterday_hint", f"昨天还有「{'、'.join(detail['yesterday_unfinished'])}」没做完，问问TA要不要挪到今天。"
                      if detail.get("yesterday_unfinished") else "")
    if detail.get("task"):
        detail.setdefault("task_hint", f"（在做「{detail['task']}」），问问TA这件事做完了没（做完了就帮TA在任务清单上打勾）")
    unfinished = detail.get("unfinished") or []
    detail.setdefault("unfinished_hint", f"，还有「{'、'.join(unfinished)}」没做完" if unfinished else "")
    detail.setdefault("unfinished_ask", "问问没做完的要不要挪到明天，" if unfinished else "")
    days_apart = int(detail.get("days_apart") or 0)
    detail.setdefault("missed_hint", f"你们已经 {days_apart} 天没说话了，自然地表达一下想念（不要埋怨）。" if days_apart >= 2 else "")
    if isinstance(detail.get("remaining"), list):
        detail["remaining"] = "、".join(detail["remaining"])
    situation_template = prompts.PROACTIVE_SITUATIONS.get(kind)
    if not situation_template:
        return None
    situation = situation_template.format_map(collections.defaultdict(str, detail))
    length = "60字以内" if kind == "day_review" else "30字以内"
    prompt = f"""
    {eureka_persona(user_name)}
    【你记得的关于TA的事】：{get_user_profile_str(user_name, situation)}
    {work_context(user_name)}
    【聊过的】：
    {history_context(4)}
    【现在的情况】：{situation}
    请你主动对TA说一句话：口语化、自然、{length}，像真的在TA身边一样；不要用列表、表情符号或括号里的动作描写。
    {prompts.EXPRESSION_RULE}
    """
    try:
        resp = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}])
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as e:
        notify.report(e, "生成主动问候")
        return None


def work_context(user_name):
    """给提示词用：她自己的状态、你们的关系、今天的任务和电脑使用情况"""
    return (f"{inner_life.life.describe()}\n"
            f"    {relationship.bond.describe(user_name)}\n"
            f"    【今天的任务】：{tasks.board.describe(user_name)}\n"
            f"    【今天在电脑上】：{activity.tracker.describe_today()}")


# 流式请求失败过一次就记下来，之后直接走普通请求，省得每轮都先失败一次
# (有些中转站不支持 "流式 + 工具调用")
_STREAM_SUPPORTED = True


def analyze_intent(messages_thread, on_text=None, should_stop=None, tools=None):
    """
    ReAct 引擎：回复文字边生成边交给 on_text (用来边想边说)，
    工具调用的碎片攒齐后随消息一起返回。返回值是可直接追加进 messages 的 dict。
    流式不可用时自动退回普通请求，拿到整段回复后一次性交给 on_text。
    """
    global _STREAM_SUPPORTED
    if _STREAM_SUPPORTED:
        spoken = []
        def on_text_tracked(delta):
            spoken.append(delta)
            if on_text:
                on_text(delta)
        try:
            message = _analyze_stream(messages_thread, on_text_tracked, should_stop, tools)
            if message.get("content") or message.get("tool_calls") or (should_stop and should_stop()):
                return message
            print("⚠️ 流式请求没有返回任何内容，改用普通请求")
        except Exception as e:
            if spoken:
                # 已经说出去一半了，不能再重来一遍，就用已有的部分
                print(f"⚠️ 流式请求中途断开: {e}")
                return {"role": "assistant", "content": "".join(spoken)}
            print(f"⚠️ 流式请求失败，改用普通请求: {e}")
        _STREAM_SUPPORTED = False

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages_thread,
            tools=tools or get_eureka_tools(),
            tool_choice="auto",
            temperature=0.1,
            stream=False
        )
        msg = response.choices[0].message
        calls = [{"id": tc.id, "type": "function",
                  "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                 for tc in (msg.tool_calls or [])]
        if msg.content and on_text:
            on_text(msg.content)
        return _assistant_message(msg.content or "", calls)
    except Exception as e:
        notify.report(e, "大脑")
        return None


def _analyze_stream(messages_thread, on_text, should_stop, tools=None):
    stream = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages_thread,
        tools=tools or get_eureka_tools(),
        tool_choice="auto",
        temperature=0.1,
        stream=True
    )
    content = ""
    calls = []
    for chunk in stream:
        if should_stop and should_stop():
            break
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if delta.content:
            content += delta.content
            on_text(delta.content)
        for tc in delta.tool_calls or []:
            # 按 index 归位；有的中转站不给 index，就靠 id 变没变判断是不是下一个调用
            if tc.index is not None:
                idx = tc.index
            elif tc.id and (not calls or calls[-1]["id"] not in ("", tc.id)):
                idx = len(calls)
            else:
                idx = max(len(calls) - 1, 0)
            while len(calls) <= idx:
                calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            slot = calls[idx]
            if tc.id:
                slot["id"] = tc.id
            if tc.function:
                name = tc.function.name or ""
                # 有的中转站每个碎片都重复带完整函数名，别拼成 "volumevolume"
                if name and slot["function"]["name"] != name:
                    slot["function"]["name"] += name
                slot["function"]["arguments"] += tc.function.arguments or ""

    for i, call in enumerate(calls):
        call["id"] = call["id"] or f"call_{i}"
    return _assistant_message(content, calls)


def _assistant_message(content, calls):
    # 有工具调用且没说话时 content 给 None，部分服务不接受空字符串
    message = {"role": "assistant", "content": content if content or not calls else None}
    if calls:
        message["tool_calls"] = calls
    return message


# 大模型在回复开头写 [表情:xx]，这里翻译成 Live2D 的表情名
EMOTION_TAGS = {
    "得意": "3clever", "开心": "3clever",
    "惊讶": "4OAO",
    "委屈": "5QAQ", "难过": "5QAQ",
    "生气": "6i gi a ri",
    "出拳": "8punch",
    "思考": "1desk",
    "唱歌": "2mic",
    "敲键盘": "7keyboard",
}
_EMOTION_TAG = re.compile(r"^\s*[\[【]表情[:：]\s*([^\]】]+)[\]】]")


def emotion_to_expression(tag):
    tag = tag.strip()
    if tag in EMOTION_TAGS.values():
        return tag
    return EMOTION_TAGS.get(tag)


class EmotionTagFilter:
    """把流式回复开头的 [表情:xx] 摘下来交给 on_expression，其余文字原样放行"""
    def __init__(self, on_expression):
        self.on_expression = on_expression
        self.pending = ""
        self.done = False

    def feed(self, delta):
        if self.done:
            return delta
        self.pending += delta
        stripped = self.pending.lstrip()
        if not stripped:
            return ""
        if stripped[0] not in "[【":
            return self._release()
        m = _EMOTION_TAG.match(self.pending)
        if m:
            expression = emotion_to_expression(m.group(1))
            if expression:
                self.on_expression(expression)
            self.pending = self.pending[m.end():].lstrip()
            return self._release()
        # 标签还没收完整就先等等；太长还没闭合说明不是标签
        if len(self.pending) > 20:
            return self._release()
        return ""

    def flush(self):
        return "" if self.done else self._release()

    def _release(self):
        self.done = True
        text, self.pending = self.pending, ""
        return text

# ================= 🧠 记忆系统配置 =================
# 1. 短期记忆：最近 10 轮对话，存到 chat_history.json，重启也记得刚才聊到哪；
#    更早的对话不直接扔掉，而是在后台压缩成一段摘要
MAX_SHORT_TERM_MEMORY = 10
MEMORY_FILE = os.path.join(get_app_path(), "memory.json")
CHAT_FILE = os.path.join(get_app_path(), "chat_history.json")
_chat_lock = threading.Lock()


def _load_chat():
    try:
        with open(CHAT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("history", []), data.get("summary", ""), data.get("updated_at", "")
    except Exception:
        return [], "", ""


chat_history, chat_summary, chat_updated_at = _load_chat()


def _save_chat():
    global chat_updated_at
    chat_updated_at = time.strftime("%Y-%m-%d %H:%M")
    try:
        with open(CHAT_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": chat_history, "summary": chat_summary, "updated_at": chat_updated_at},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   ⚠️ 保存聊天记录失败: {e}")


def _summarize(old_messages):
    """把挤出短期记忆的旧对话并进摘要 (后台跑，失败就保留原摘要)"""
    global chat_summary
    lines = "\n".join(f"{'TA' if m['role'] == 'user' else character.name()}：{m['content']}" for m in old_messages)
    prompt = (f"已有的聊天摘要：{chat_summary or '（无）'}\n\n新的一段对话：\n{lines}\n\n"
              "请把新对话并进摘要，保留聊过的话题、做过的事、还没完成的约定，去掉寒暄。"
              "用第三人称、200 字以内，只输出摘要本身。")
    try:
        resp = client.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}])
        with _chat_lock:
            chat_summary = (resp.choices[0].message.content or "").strip() or chat_summary
            _save_chat()
    except Exception as e:
        print(f"   ⚠️ 压缩聊天摘要失败: {e}")


def remember_exchange(user_text, reply):
    """记一轮对话进短期记忆；超出 10 轮的部分挪去摘要"""
    global chat_history
    with _chat_lock:
        chat_history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
        overflow = []
        if len(chat_history) > MAX_SHORT_TERM_MEMORY * 2:
            overflow = chat_history[:-MAX_SHORT_TERM_MEMORY * 2]
            chat_history = chat_history[-MAX_SHORT_TERM_MEMORY * 2:]
        _save_chat()
    if overflow:
        threading.Thread(target=_summarize, args=(overflow,), daemon=True).start()


def history_context(last_n=6):
    """给提示词用的短期上下文：更早的摘要 + 最近几句"""
    with _chat_lock:
        recent = chat_history[-last_n:]
        summary, updated = chat_summary, chat_updated_at
    parts = []
    if summary:
        parts.append(f"更早聊过的（摘要）：{summary}")
    if recent:
        lines = "\n    ".join(f"{'TA' if m['role'] == 'user' else '你'}: {m['content']}" for m in recent)
        parts.append(f"最近的对话（{updated}）：\n    {lines}")
    return "\n    ".join(parts) or "（还没聊过）"


def update_memory(user_text, ai_summary):
    """
    手动写入记忆（供 main.py 调用）
    比如：执行完B站搜索后，把 "我帮你搜了XXX" 记入脑海，
    这样下次用户说 "换一个" 时，她就知道是在换视频。
    """
    remember_exchange(user_text, ai_summary)
    print(f"   🧠 记忆已更新: {ai_summary}")

# 2. 长期记忆 (文件里) - 每次对话都会重新读取
# ==================================================
def load_long_term_memory():
    """读取长期记忆文件，如果不存在就返回空"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def generate_briefing(prompt):
    """早报这类长一点的独白：返回 (要说的话, 表情)"""
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": eureka_persona()},
                      {"role": "user", "content": f"{prompt}\n{prompts.EXPRESSION_RULE}"}])
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        notify.report(e, "生成早报")
        return "早报没拿到，网络好像不太好…", "5QAQ"
    m = _EMOTION_TAG.match(text)
    if m:
        return text[m.end():].strip(), emotion_to_expression(m.group(1))
    return text, None


def check_birthday():
    """
    开机自检：检查今天是不是主人的生日
    如果是，现编一段祝福语
    """
    memory = load_long_term_memory()
    owners = memory.get("owners", []) # 获取主人列表
    
    # 获取今天日期 (格式 02-04)
    today = datetime.now().strftime("%m-%d")
    
    for owner in owners:
        if owner.get("birthday") == today:
            name = owner.get("name", "你")
            print(f"   🎂 发现今天是 {name} 的生日！")
            
            # 让 LLM 现场生成一段祝福
            prompt = f"今天是【{name}】的生日。请你用温柔、开心、充满惊喜的语气祝{name}生日快乐！(50字以内，不要太客套，要像家人一样亲切)"
            
            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": eureka_persona(name)},
                        {"role": "user", "content": prompt}
                    ],
                    stream=False
                )
                return response.choices[0].message.content
            except Exception:
                return f"生日快乐，{name}！愿你今天过得开心！"
                
    return None # 今天没人过生日

def analyze_image(image_path, user_query):
    """
    调用云端视觉模型分析图片 (接口见 .env 的 VISION_* / VOLC_VISION_MODEL_NAME)
    """
    print(f"   👀 正在调用云端视觉模型: {user_query} ...")
    
    # 1. 图片转 Base64
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        return f"图片读取失败: {e}"
    
    # 定义提示词后缀
    prompt_suffix = " (请用自然连贯的口语回答，像朋友聊天一样。❌绝对不要使用Markdown格式，❌不要加粗，❌不要分点列大纲。直接给出结论和简要原因即可，控制在100字以内。)"

    try:
        if not VISION_MODEL_NAME:
            return "我还没有眼睛呢，要先在 .env 里配置看图的模型。"
        usage.add("vision_calls")
        response = vision_client.chat.completions.create(
            model=VISION_MODEL_NAME, 
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_query + prompt_suffix},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content
        
    except Exception as e:
        notify.report(e, "看屏幕")
        return "我看不太清，可能是云端接口出问题了。"

def generate_recommend_query(topic_or_creator):
    """
    智能搜索词生成器 V3.0 (融合上下文版)
    """
    # 🛡️ 防呆 + 处理“换一个”
    if not topic_or_creator or topic_or_creator in ["换一个", "下一个", "再来一个", "不喜欢"]:
        topic_or_creator = "随机惊喜/宝藏视频"

    # 1. 读取用户的喜好 (长期记忆)
    memory = load_long_term_memory()
    prefs = []
    for owner in memory.get("owners", []):
        name = owner.get('name', '某人')
        p = owner.get('preferences', '无偏好')
        prefs.append(f"{name}: {p}")
    prefs_str = "; ".join(prefs)
    
    # 1.5 个性化：根据当前活跃用户附加兴趣关键词
    try:
        current_name = get_last_active_user()
        profile = get_user_profile(current_name)
        if profile:
            interests = profile.get("preferences", {}).get("media_interests", {}).get("keywords", [])
            if interests:
                topic_or_creator = f"{topic_or_creator} {random.choice(interests)}"
    except Exception:
        pass
    
    # 2. 👇 新增：获取最近的聊天记录 (短期上下文)
    recent_chat = ""
    if chat_history:
        recent_chat = "【最近几句对话状态】：\n"
        for msg in chat_history[-4:]:
            recent_chat += f"{msg['role']}: {msg['content']}\n"
    
    # 3. 构造提示词
    prompt = f"""
    用户的核心需求是想看关于【{topic_or_creator}】的视频。
    
    【用户画像(长期)】：{prefs_str}
    {recent_chat}
    
    请结合【用户画像】和【最近对话状态】生成一个B站搜索关键词。
    
    【思考逻辑】：
    1. 优先考虑【最近对话状态】。
       - 如果最近对话提到用户“感冒/心情不好”，请推荐“治愈/科普/轻松/搞笑”类的视频。
       - 如果最近对话提到“想学做饭”，请推荐“新手教程”。
    2. 如果输入是"随机惊喜"：
       - 请忽略之前的搜索惯性，从用户画像中【随机】挑选一个完全不同的冷门或有趣领域。
    3. 如果没有特殊上下文，则根据【用户画像】推荐。

    【输出要求】：
    只返回一个简短的搜索关键词，不要包含任何标点符号、解释或括号。
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个B站搜索专家。"},
                {"role": "user", "content": prompt}
            ],
            stream=False
        )
        return response.choices[0].message.content.strip().replace('"', '').replace("'", "")
    except Exception as e:
        print(f"❌ 生成搜索词失败: {e}")
        return f"{topic_or_creator} 热门"
    
def generate_verbal_reply(situation):
    """
    口语生成器：把冷冰冰的系统执行结果，变成尤里卡的个性化回复
    """
    # ==================================================
    # 🎲 性格抽奖池 (随机选择一种风格，防止重复)
    # ==================================================
    styles = [
        "语气要超级开心、活泼，顺便求一下表扬 (OvO)！",          # 20% 概率求表扬
        "语气要像主播开播一样元气满满，热情地分享这件事~",      # 20% 概率主播腔
        "语气要温柔体贴，像个邻家大姐姐一样照顾对方。",          # 20% 概率温柔
        "语气要幽默风趣，可以适度玩梗。",            # 20% 概率幽默
        "语气要简洁干练，像个专业的私人秘书，只说重点。",        # 20% 概率高冷
    ]
    current_style = random.choice(styles)
    # ==================================================
    
    current_user = get_user_profile()
    persona = MEMORY.get("system_config", {}).get("ai_persona", "")

    if current_user:
        tone = current_user.get("interaction_style", {}).get("tone", "")
        allow_roast = current_user.get("interaction_style", {}).get("allow_roast", False)
        current_user_name = current_user.get("name")
    else:
        tone = ""
        allow_roast = False
        current_user_name = "未知用户"

    system_prompt = f"""
    {eureka_persona(current_user_name if current_user else None)}
    补充设定：{persona}
    当前对话用户：{current_user_name}
    对TA的语气风格：{tone}
    是否允许调侃：{allow_roast}
    """

    prompt = f"""
    【当前情况】：{situation}

    请根据上述情况，以你的口吻跟对方说一句话。

    【语气要求】：
    1. {current_style}
    2. ❌禁止重复我给你的【当前情况】原文。
    3. ❌禁止说“为您播放”、“好的”、“明白”这种客服腔。
    4. 结合具体内容发表一点看法（比如提到“S11”可以说“牙膏”或“新品”）。
    5. 控制在 30 字以内，口语化！
    """

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
        )
        reply = completion.choices[0].message.content
        return reply.strip().replace('"', '') # 去掉可能出现的引号
    except Exception as e:
        print(f"❌ 生成回复出错: {e}")
        return "搞定啦，这就来！"
    
def generate_search_answer(user_query, search_context):
    """
    RAG 核心：阅读搜索结果 -> 生成回答
    """
    print("   🧠 大脑正在快速阅读搜索结果并组织语言...")
    
    prompt = f"""
    用户的问题是："{user_query}"
    
    我刚刚在互联网上查到了以下信息（可能包含噪音）：
    ---------------------
    {search_context}
    ---------------------
    
    请你扮演【{character.name()}】，根据查到的信息，回答用户的问题。
    
    【要求】：
    1. 必须根据搜索结果回答，不要瞎编。如果搜索结果里没有相关信息，就诚实说没查到。
    2. 语气要像朋友一样自然口语化，不要照读搜索结果。
    3. 答案控制在 100 字以内，挑重点说。
    4. 比如：如果查到 S11 还没出，就说“网上说 S11 还没发布呢，目前只有传闻...”。
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个擅长快速阅读和总结的AI助手。"},
                {"role": "user", "content": prompt}
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"哎呀，总结的时候出错了：{e}"
