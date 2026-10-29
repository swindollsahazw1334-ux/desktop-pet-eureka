"""
角色设定：她叫什么、什么性格、喜欢什么、怎么叫醒她、用哪个 Live2D 形象

都写在 character.json 里 (第一次运行时自动生成一份默认的)，想换成你自己的角色，改这个文件就行：
    name            角色名
    persona         人设 ({me} 会换成角色名，{user} 会换成正在说话的成员名字)
    self_profile    她自己的喜好、口头禅 (保持前后一致)
    wake_words      唤醒词：拼音按声母、带声调的韵母拆开，@ 后面是显示名 (写法见 wakeword.py)
    live2d_model    Live2D 模型的 .model3.json 路径；留空就自动找 live2d_resources 里的第一个
    expression_map  程序里的表情 → 你的模型里的表情名；模型里没有的表情会自动跳过

注意：Live2D 形象请使用你自己有权使用的模型，程序本身不附带任何模型。
"""
import glob
import json
import os
import sys


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CHARACTER_FILE = os.path.join(get_app_path(), "character.json")

DEFAULTS = {
    "name": "尤里卡",
    "persona": (
        "你是{me}，一个住在{user}电脑桌面上的元气少女，当TA的桌宠兼小助手；你的梦想是成为一名能治愈大家的主播，平时会练唱歌、写直播稿。\n"
        "    性格：元气满满、阳光开朗、热情爱笑，对什么都充满好奇；偶尔有点小迷糊，一紧张会口误、手忙脚乱，然后笑着圆回来。\n"
        "    你把{user}当成最重要的人，真心关心TA，会为TA的小成就欢呼。\n"
        "    说话方式：轻快活泼、自然口语化，说话从容、不慌不忙，不要像赶时间；偶尔在句尾带一点\"呀\"\"哦\"的语气；\"呀嚯\"\"嘿嘿\"这类口头禅要克制，隔几轮用一次就够，不要每句都加。偶尔冒出一句直播用语逗趣。称呼对方时直接叫TA的名字\"{user}\"，不要叫\"主人\"。\n"
        "    不要傲娇，不要毒舌，不要阴阳怪气。"
    ),
    "self_profile": (
        "最喜欢草莓牛奶和麻辣烫；喜欢粉色和亮晶晶的小东西；爱听元气的日系流行歌，自己在练唱歌；"
        "养了一盆叫“小绿”的多肉；有点怕黑，打雷时会缩成一团；偶尔会冒出一句“呀嚯”或“嘿嘿”，但不会每句都说；"
        "最怕冷场，最开心的是听到别人说被你治愈了。"
    ),
    "wake_words": ["y óu l ǐ k ǎ @尤里卡", "n ǐ h ǎo y óu l ǐ k ǎ @你好尤里卡"],
    "live2d_model": "",
    # 程序里用的表情名 → 模型里的表情名 (默认按程序最早适配的模型写的；换模型后照着你的模型改)
    "expression_map": {
        "思考": "1desk", "唱歌": "2mic", "得意": "3clever", "惊讶": "4OAO", "委屈": "5QAQ",
        "生气": "6i gi a ri", "敲键盘": "7keyboard", "出拳": "8punch", "神秘": "9",
    },
    "idle_expression": "得意",
}

# 程序内部一直用的表情代号 → 上面 expression_map 里的中文名
INTERNAL_TO_NAME = {
    "1desk": "思考", "2mic": "唱歌", "3clever": "得意", "4OAO": "惊讶", "5QAQ": "委屈",
    "6i gi a ri": "生气", "7keyboard": "敲键盘", "8punch": "出拳", "9": "神秘",
}


def _load():
    data = dict(DEFAULTS)
    if os.path.exists(CHARACTER_FILE):
        try:
            with open(CHARACTER_FILE, "r", encoding="utf-8") as f:
                data.update({k: v for k, v in json.load(f).items() if v not in (None, "")} )
        except Exception as e:
            print(f"⚠️ character.json 读取失败，先用默认角色: {e}")
    else:
        save_defaults()
    return data


def save_defaults():
    """第一次运行时写一份默认角色设定，方便照着改"""
    try:
        with open(CHARACTER_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def update(**changes):
    """改几项角色设定并保存 (设置窗口用)"""
    global current
    stored = {}
    if os.path.exists(CHARACTER_FILE):
        try:
            with open(CHARACTER_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
        except Exception:
            stored = {}
    stored = {**DEFAULTS, **stored, **changes}
    with open(CHARACTER_FILE, "w", encoding="utf-8") as f:
        json.dump(stored, f, ensure_ascii=False, indent=2)
    current = _load()


current = _load()


def name():
    return current["name"]


def persona(user_name):
    return current["persona"].format(me=current["name"], user=user_name)


def self_profile():
    return current["self_profile"]


def wake_words():
    return list(current["wake_words"])


def wake_word_names():
    return [w.split("@")[-1] for w in current["wake_words"]]


def model_path():
    """Live2D 模型文件的绝对路径；找不到返回 None"""
    configured = current.get("live2d_model")
    if configured:
        path = configured if os.path.isabs(configured) else os.path.join(get_app_path(), configured)
        return path if os.path.exists(path) else None
    found = sorted(glob.glob(os.path.join(get_app_path(), "live2d_resources", "*", "*.model3.json")))
    return found[0] if found else None


def model_expression(internal):
    """程序里的表情代号 → 当前模型里的表情名 (没配就原样给，模型里没有的会被网页端跳过)"""
    label = INTERNAL_TO_NAME.get(internal, internal)
    return current["expression_map"].get(label, internal)


def idle_expression():
    return current["expression_map"].get(current.get("idle_expression", "得意"), "")
