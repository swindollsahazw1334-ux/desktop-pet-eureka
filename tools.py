"""
她能用的工具 (Function Calling 的定义)。具体怎么执行在 main.py / skills.py 里
"""
import json
import os


def _screen_allowed():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("allow_screen", True)
    except Exception:
        return True


def get_eureka_tools():
    """她能用的工具；隐私设置里关掉了看屏幕，就不给她 screen 工具"""
    tools = _all_tools()
    if not _screen_allowed():
        tools = [t for t in tools if t["function"]["name"] != "screen"]
    return tools


def _all_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "music",
                "description": "播放音乐。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        # 👇 1. 明确告诉大模型：没说歌名就必须留空！
                        "keyword": {
                            "type": "string", 
                            "description": "歌名或歌手名。⚠️ 如果用户没有具体指定（例如只说‘放首歌’），请务必留空（填空字符串）。"
                        },
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    # 👇 2. 把 "keyword" 从这里的必填数组里删掉，只保留 "ack"
                    "required": ["ack"] 
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "bilibili",
                "description": "在B站搜索、推荐或播放视频。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "搜索关键词或UP主名称"},
                        "target": {
                            "type": "string", 
                            "enum": ["search", "latest", "most_viewed", "rank", "recommend"],
                            "description": "操作目标"
                        },
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["target", "ack"] # keyword有时不需要，比如看热门
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "volume",
                "description": "系统音量控制。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string", 
                            "enum": ["set", "up", "down", "mute"],
                            "description": "控制类型"
                        },
                        "value": {"type": "integer", "description": "只有type为set时需要，0-100的百分比数字"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["type", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "app",
                "description": "打开指定的本地软件。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "软件名称，如：计算器、微信"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["name", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "查询天气。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["city", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "browser",
                "description": "打开浏览器窗口或在浏览器中搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "想要搜索的内容，如果不搜留空"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "screen",
                "description": "屏幕分析/看屏幕。提取文字或解释报错等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "用户想问关于屏幕的什么问题"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["query", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_chat",
                "description": "联网搜索客观知识并语音回答。禁止用于私人身份或情感问题。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "需要联网搜索的关键词"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["keyword", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "timer",
                "description": "倒计时/定时提醒。必须将分钟换算为秒。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seconds": {"type": "integer", "description": "倒计时的秒数"},
                        "content": {"type": "string", "description": "提醒的具体内容"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["seconds", "content", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "note",
                "description": "闪念胶囊/记事本。帮用户记录备忘。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "需要记录的内容"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["content", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "记住用户的个人信息、喜好、设定等，写入长期记忆库。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "description": "需要记住的具体事实，尽量精简描述。"},
                        "ack": {"type": "string", "description": "向用户确认已经记住的口语回应。"}
                    },
                    "required": ["fact", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "focus",
                "description": "陪用户专注 (学习/工作/番茄钟)：开始后安静陪着、桌面显示倒计时，结束时提醒休息。用户说结束/不专注了时用 stop。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["start", "stop"], "description": "start 开始专注，stop 提前结束"},
                        "minutes": {"type": "integer", "description": "专注多少分钟，用户没说就用 25"},
                        "task": {"type": "string", "description": "要专注做的事，比如 '背单词'，没说就留空"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["action", "ack"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "tasks",
                "description": "管理用户的今日任务清单：记下今天要做的事、标记完成/撤销、删除、看进度、把昨天没做完的挪到今天、收工回顾 (今天做了什么、在电脑上花了多久)。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "done", "undo", "remove", "list", "carry_over", "review"],
                                   "description": "add 添加任务；done 标记完成；undo 撤销完成；remove 删除；list 看进度；carry_over 把昨天没做完的挪到今天；review 收工回顾"},
                        "items": {"type": "array", "items": {"type": "string"}, "description": "add 时：要添加的任务，每件事一条，简短，如 ['写周报', '改登录页bug']"},
                        "target": {"type": "string", "description": "done/undo/remove 时：是哪件任务，用户怎么说就怎么填，如 '周报'"},
                        "ack": {"type": "string", "description": "执行前口语回应"}
                    },
                    "required": ["action", "ack"]
                }
            }
        }
    ]
