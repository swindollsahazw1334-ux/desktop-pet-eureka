import os
import webbrowser
import urllib.parse
import requests
import wbi_signer
import json
import time
import subprocess
import ai_brain
import random
import threading  # 👈 新增这个用于倒计时
import sys
import re
from PIL import ImageGrab

# 👇👇👇 添加这些导入 👇👇👇
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
import comtypes # 👈 新增这个
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def clean_html_violent(html_content):
    """
    [通用 HTML 清洗工具] 将网页源码转为纯文本
    """
    import re
    html_content = re.sub(r'<head.*?>.*?</head>', '', html_content, flags=re.S|re.I)
    html_content = re.sub(r'<script.*?>.*?</script>', '', html_content, flags=re.S|re.I)
    html_content = re.sub(r'<style.*?>.*?</style>', '', html_content, flags=re.S|re.I)
    html_content = re.sub(r'', '', html_content, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', html_content)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def take_screenshot():
    """
    [主屏 4K 原生版] 仅截取主屏幕的无损原图，不压缩，不带副屏！
    """
    try:
        import sys
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        save_path = os.path.join(base_path, "current_screen.jpg")
        
        # 🌟 核心修改：all_screens=False 只截取主屏幕！
        img = ImageGrab.grab(all_screens=False)
        
        # 直接保存，质量95
        img.save(save_path, "JPEG", quality=95)
        
        print(f"   📸 [主屏原生截图]: 分辨率 {img.width}x{img.height}，已保存至 {save_path}")
        return save_path
        
    except Exception as e:
        print(f"❌ 原生截图失败: {e}")
        return None

def open_browser(keyword):
    """通用浏览器搜索 (默认百度)"""
    try:
        print(f"   🌐 执行: 浏览器搜索 [{keyword}]")
        if not keyword:
            return False
            
        # 这里默认用百度，你也可以换成 Bing 或 Google
        # 百度: https://www.baidu.com/s?wd=
        # 必应: https://cn.bing.com/search?q=
        # 谷歌: https://www.google.com/search?q=
        
        base_url = "https://cn.bing.com/search?q="
        url = base_url + urllib.parse.quote(keyword)
        
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"❌ 浏览器打开失败: {e}")
        return False

def open_app(app_name):
    """打开常用软件 (升级版：读取外部配置文件)"""
    import json
    import os
    import sys
    import subprocess

    # 1. 获取 json 文件的绝对路径 (兼容打包后的 exe)
    def get_app_path():
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    config_path = os.path.join(get_app_path(), "apps.json")
    
    # 2. 如果配置文件不存在，提示用户
    if not os.path.exists(config_path):
        print(f"❌ 找不到配置文件: {config_path}")
        print("请在软件目录下创建一个 apps.json 文件并配置路径。")
        return False

    # 3. 读取配置
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            app_map = json.load(f)
    except Exception as e:
        print(f"❌ 读取 apps.json 失败: {e}")
        return False

    # 4. 模糊匹配逻辑
    target_path = None
    
    # 先尝试直接匹配 key
    if app_name in app_map:
        target_path = app_map[app_name]
    else:
        # 别名映射 (代码里的逻辑只负责“翻译”名字，路径去 json 里查)
        # 例如：用户说"网易云" -> 代码翻译成"music" -> 去json找"music"的路径
        alias_map = {
            "计算器": "calculator",
            "记事本": "notepad",
            "微信": "wechat",
            "网易云": "music",
            "音乐": "music",
            "浏览器": "browser",
            "方舟": "arknight",
            "鸣潮": "wuthering wave",
            "无限暖暖": "InfinityNikki"
        }
        
        # 遍历别名找 key
        for alias, key in alias_map.items():
            if alias in app_name:
                if key in app_map:
                    target_path = app_map[key]
                break
    
    # 5. 执行启动
    if target_path:
        try:
            print(f"   🚀 正在启动: {target_path}")
            
            # 如果是系统命令 (calc.exe)，直接运行
            if "\\" not in target_path and "/" not in target_path:
                subprocess.Popen(target_path)
                return True
                
            # 如果是具体路径，检查文件是否存在
            if os.path.exists(target_path):
                # cwd参数很重要：有些游戏必须在安装目录下才能运行
                working_dir = os.path.dirname(target_path)
                subprocess.Popen(target_path, cwd=working_dir)
                return True
            else:
                print(f"❌ 路径无效，文件不存在: {target_path}")
                return False
        except Exception as e:
            print(f"❌ 启动失败: {e}")
            return False
    else:
        print(f"❌ 未在 apps.json 里找到对应配置: {app_name}")
        return False

def get_weather(city=""):
    """
    天气技能 (终极版：爬虫 + LLM 阅读理解)
    """
    # 1. 优化搜索词
    # 如果是模糊指代，直接搜 "天气" (百度通常会按IP显示当地天气)
    # 或者搜 "当地天气"
    if not city or city in ["当前城市", "当前所在地", "这里", "本地", "当前位置"]:
        search_query = "当地天气"
    else:
        search_query = f"{city}天气"
    
    print(f"   🌤️ 正在调用爬虫查询: {search_query}...")
    
    # 2. 调用我们最强的暴力爬虫
    weather_data = web_search_fetch(search_query)
    
    if weather_data:
        print("   🧠 正在让大脑阅读天气数据...")
        
        # 3. 直接调用 ai_brain 的 RAG 功能进行提取！
        # 假设你之前已经把 generate_search_answer 加到了 ai_brain.py 里
        try:
            # 构造一个明确的问题，让 AI 知道我们在查天气
            query_for_ai = f"请根据搜索结果，告诉我【{search_query}】怎么样？特别是明天的天气。只回答天气情况，不要废话。"
            
            # 复用 generate_search_answer 函数
            answer = ai_brain.generate_search_answer(query_for_ai, weather_data)
            
            # 简单清洗一下，防止 AI 回复 "根据搜索结果..." 这种废话
            print(f"   ✅ AI提取结果: {answer}")
            return answer
            
        except AttributeError:
            # 万一你没加 generate_search_answer，兜底一下
            return "抓取到了数据，但大脑阅读模块(generate_search_answer)似乎没找到。"
    else:
        return "网络爬虫没抓到数据，可能是百度反爬了。"

def control_system_volume(vol_type, value=0):
    """
    控制系统音量
    """
    try:
        # 1. 🛡️ 初始化 COM 库 (关键修复：防止报错)
        comtypes.CoInitialize()
        
        # 2. 获取扬声器对象
        devices = AudioUtilities.GetSpeakers()
        
        # 3. 激活接口
        interface = devices.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        
        # 获取当前音量
        current_vol = volume.GetMasterVolumeLevelScalar()
        
        # 计算目标音量
        target_vol = current_vol

        if vol_type == "mute":
            # 静音操作
            is_muted = volume.GetMute()
            volume.SetMute(not is_muted, None)
            print(f"   🔇 {'已静音' if not is_muted else '已解除静音'}")
            return True

        elif vol_type == "up":
            target_vol = min(1.0, current_vol + 0.1) # 加10%
        elif vol_type == "down":
            target_vol = max(0.0, current_vol - 0.1) # 减10%
        elif vol_type == "set":
            target_vol = max(0.0, min(1.0, value / 100.0))
        
        # 应用设置
        volume.SetMasterVolumeLevelScalar(target_vol, None)
        print(f"   🔊 音量调节: {int(current_vol*100)}% -> {int(target_vol*100)}%")
        return True

    except Exception as e:
        print(f"❌ 音量调节失败: {e}")
        # 调试信息：如果还报错，打印出来看看 devices 到底是个啥
        # print(f"调试: devices类型={type(devices)}")
        return False

# --- B站 API 工具函数 (保持不变) ---

def get_bilibili_latest_video(up_name):
    # 你的 SESSDATA (拥有VIP身份)
    SESSDATA = "d65dc5dc%2C1780239256%2Cb00ea%2Ac1CjB24BP1wKTi2NPxlXRPA074tF9-0c7lq_BtCpSlPq-ofA8CNfLuL71vWZPicX1HYR0SVlBPVFUtbFVNMFhhaHVtT3Nvb3ZCVElscjJrdVZTV2M0a21DOXZBVVZidE45NXBjeTY0X1dvb0tQOUltcFN0OWRtWGpPckYxYlU0RFN5eTZhWlhjOUJBIIEC"
    BUVID3 = "84D21716-1681-4940-8422-77119106093322115infoc"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": f"SESSDATA={SESSDATA}; buvid3={BUVID3};" 
    }

    corrections = {
        "食频道": "食贫道",
        "蜡笔小鲜": "蜡笔小新",
        "罗翔": "罗翔说刑法", 
        "影视飓风": "影视飓风",
    }
    if up_name in corrections:
        up_name = corrections[up_name]

    try:
        print(f"   🕵️ 正在查找 UP主: {up_name} ...")
        
        img_key, sub_key = wbi_signer.getWbiKeys()
        if not img_key: return None 
            
        search_params = { "search_type": "bili_user", "keyword": up_name }
        signed_search_params = wbi_signer.encWbi(search_params, img_key, sub_key)
        
        response = requests.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params=signed_search_params,
            headers=headers,
            timeout=5
        )
        
        try:
            res = response.json()
        except:
            return None

        if res.get('code') == 0 and res.get('data') and res['data'].get('numResults') > 0:
            users_found = res['data']['result']
            
            for user in users_found[:3]:
                mid = user['mid']
                name = user['uname']
                video_count = user.get('videos', 0)
                
                print(f"   🔎 检查候选人: {name} (ID: {mid} | 视频数: {video_count})")
                if video_count < 3: continue

                params = { 'mid': mid, 'ps': 1, 'pn': 1 }
                signed_params = wbi_signer.encWbi(params, img_key, sub_key)
                
                space_res = requests.get(
                    "https://api.bilibili.com/x/space/wbi/arc/search",
                    params=signed_params,
                    headers=headers,
                    timeout=5
                ).json()
                
                if space_res.get('code') == 0 and space_res.get('data') and space_res['data']['list']['vlist']:
                    video_data = space_res['data']['list']['vlist'][0]
                    title = video_data['title']
                    bvid = video_data['bvid']
                    print(f"   ✅ 锁定目标: {name}")
                    print(f"   🎬 最新视频: {title}")
                    return f"https://www.bilibili.com/video/{bvid}"
            
            print("   🚀 启动保底策略")
            return f"https://search.bilibili.com/all?keyword={urllib.parse.quote(up_name)}"
        else:
            print("   ❌ 未找到该 UP 主")
            return None

    except Exception as e:
        print(f"   ❌ 请求出错: {e}")
        return None

def get_bilibili_hot_video(keyword):
    """获取指定UP主播放量最高的视频"""
    # ... (SESSDATA, BUVID3, headers 定义保持不变) ...
    # 你的 SESSDATA
    SESSDATA = "d65dc5dc%2C1780239256%2Cb00ea%2Ac1CjB24BP1wKTi2NPxlXRPA074tF9-0c7lq_BtCpSlPq-ofA8CNfLuL71vWZPicX1HYR0SVlBPVFUtbFVNMFhhaHVtT3Nvb3ZCVElscjJrdVZTV2M0a21DOXZBVVZidE45NXBjeTY0X1dvb0tQOUltcFN0OWRtWGpPckYxYlU0RFN5eTZhWlhjOUJBIIEC"
    BUVID3 = "84D21716-1681-4940-8422-77119106093322115infoc"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": f"SESSDATA={SESSDATA}; buvid3={BUVID3};" 
    }

    try:
        print(f"   🔥 正在定位 UP主: {keyword} ...")
        
        img_key, sub_key = wbi_signer.getWbiKeys()
        if not img_key: return None 
        
        # 1. 第一步：先搜人 (确保是找这个人的视频，而不是全站蹭热度的视频)
        search_params = { "search_type": "bili_user", "keyword": keyword }
        signed_search_params = wbi_signer.encWbi(search_params, img_key, sub_key)
        
        user_resp = requests.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params=signed_search_params,
            headers=headers,
            timeout=5
        )
        user_data = user_resp.json()
        
        target_mid = None
        if user_data.get('code') == 0 and user_data.get('data') and user_data['data'].get('numResults') > 0:
            # 取第一个搜索结果作为目标 UP 主
            first_user = user_data['data']['result'][0]
            target_mid = first_user['mid']
            print(f"   ✅ 找到 UP主: {first_user['uname']} (MID: {target_mid})")
        else:
            print("   ❌ 未找到该 UP 主")
            return None

        # 2. 第二步：去他的空间搜最热视频
        # order=click (播放量), ps=1 (只取第1个)
        space_params = { 
            "mid": target_mid, 
            "order": "click", 
            "ps": 1, 
            "pn": 1 
        }
        signed_space_params = wbi_signer.encWbi(space_params, img_key, sub_key)
        
        space_resp = requests.get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params=signed_space_params,
            headers=headers,
            timeout=5
        )
        space_data = space_resp.json()
        
        if space_data.get('code') == 0 and space_data.get('data') and space_data['data']['list']['vlist']:
            top_video = space_data['data']['list']['vlist'][0]
            title = top_video['title']
            play_count = top_video['play']
            bvid = top_video['bvid']
            
            print(f"   ✅ 锁定最热作品: {title}")
            print(f"   🔥 播放量: {play_count}")
            return f"https://www.bilibili.com/video/{bvid}"
        else:
            print("   ❌ 该 UP 主好像没有视频")
            return None

    except Exception as e:
        print(f"   ❌ 搜索出错: {e}")
        return None
# --- 具体技能实现 ---

def play_music(keyword=""):
    """播放音乐技能"""
    DEFAULT_PLAYLIST = "24381616"
    try:
        if not keyword:
            print(f"   🎵 执行: 播放默认歌单")
            url = f"orpheus://playlist/{DEFAULT_PLAYLIST}"
        else:
            print(f"   🔍 执行: 搜索歌曲 [{keyword}]")
            encoded = urllib.parse.quote(keyword)
            url = f"https://music.163.com/#/search/m/?s={encoded}&type=1"
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"❌ 音乐执行失败: {e}")
        return False

def search_bilibili(keyword, target="search"):
    """B站技能 (已升级)"""
    
    # --- 1. 找最新 ---
    if target == "latest":
        print(f"   📺 执行: 打开 [{keyword}] 的最新视频")
        video_url = get_bilibili_latest_video(keyword)
        if video_url:
            webbrowser.open(video_url)
        else:
            print("   ⚠️ 降级为普通搜索")
            webbrowser.open(f"https://search.bilibili.com/all?keyword={keyword}")
            
    # --- 2. 找最热 (新增) ---
    elif target == "most_viewed":
        print(f"   🔥 执行: 打开 [{keyword}] 播放量最高的视频")
        video_url = get_bilibili_hot_video(keyword)
        if video_url:
            webbrowser.open(video_url)
        else:
            print("   ⚠️ 降级为按播放量搜索")
            webbrowser.open(f"https://search.bilibili.com/all?keyword={keyword}&order=click")

    # --- 3. 普通搜索 ---
    else:
        print(f"   📺 执行: B站搜索 [{keyword}]")
        if keyword:
            webbrowser.open(f"https://search.bilibili.com/all?keyword={keyword}")
        else:
            webbrowser.open("https://www.bilibili.com")
    return True

def get_bilibili_rank_video():
    """获取B站当前热门榜第一名的视频"""
    # 复用之前的 Header 配置
    SESSDATA = "d65dc5dc%2C1780239256%2Cb00ea%2Ac1CjB24BP1wKTi2NPxlXRPA074tF9-0c7lq_BtCpSlPq-ofA8CNfLuL71vWZPicX1HYR0SVlBPVFUtbFVNMFhhaHVtT3Nvb3ZCVElscjJrdVZTV2M0a21DOXZBVVZidE45NXBjeTY0X1dvb0tQOUltcFN0OWRtWGpPckYxYlU0RFN5eTZhWlhjOUJBIIEC"
    BUVID3 = "84D21716-1681-4940-8422-77119106093322115infoc"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": f"SESSDATA={SESSDATA}; buvid3={BUVID3};" 
    }

    try:
        print("   🔥 正在获取B站热门榜单...")
        
        # 1. 获取 Wbi 签名 (复用你已有的模块)
        img_key, sub_key = wbi_signer.getWbiKeys()
        if not img_key: return None

        # 2. 请求热门接口 (ps=1 表示只取第1个)
        params = { "ps": 1, "pn": 1 }
        signed_params = wbi_signer.encWbi(params, img_key, sub_key)
        
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params=signed_params,
            headers=headers,
            timeout=5
        )
        data = resp.json()
        
        # 3. 解析结果
        if data['code'] == 0 and data['data']['list']:
            top_video = data['data']['list'][0]
            title = top_video['title']
            # 过滤掉标题里的奇怪符号，方便 TTS 朗读
            title = title.replace("&quot;", '"').replace("<em class=\"keyword\">", "").replace("</em>", "")
            
            author = top_video['owner']['name']
            short_link = top_video['short_link_v2'] # 短链接
            
            print(f"   👑 榜首视频: {title} (UP: {author})")
            return title, author, short_link
            
        return None

    except Exception as e:
        print(f"   ❌ 获取榜单失败: {e}")
        return None

def search_video_return_first(keyword):
    """
    搜索视频 - 精准增强版
    1. 【随机范围】：获取前 20 个结果。
    2. 【双重筛选】：
       - 第一轮：必须超过 10万 播放。
       - 第二轮（核心）：把包含关键词的视频放入【VIP池】，不包含的放入【普通池】。
    3. 【优先录取】：如果【VIP池】里有货，就在VIP里随机；否则才去普通池找。
    """
    # ... (前面的配置和 headers 保持不变) ...
    SESSDATA = "d65dc5dc%2C1780239256%2Cb00ea%2Ac1CjB24BP1wKTi2NPxlXRPA074tF9-0c7lq_BtCpSlPq-ofA8CNfLuL71vWZPicX1HYR0SVlBPVFUtbFVNMFhhaHVtT3Nvb3ZCVElscjJrdVZTV2M0a21DOXZBVVZidE45NXBjeTY0X1dvb0tQOUltcFN0OWRtWGpPckYxYlU0RFN5eTZhWlhjOUJBIIEC"
    BUVID3 = "84D21716-1681-4940-8422-77119106093322115infoc"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Cookie": f"SESSDATA={SESSDATA}; buvid3={BUVID3};" 
    }

    # 个性化：若存在活跃用户偏好，追加一个兴趣关键词以调整推荐
    try:
        current_user = ai_brain.get_last_active_user()
        profile = ai_brain.get_user_profile(current_user)
        if profile:
            interests = profile.get("preferences", {}).get("media_interests", {}).get("keywords", [])
            if interests:
                extra = random.choice(interests)
                print(f"   🎯 根据用户偏好追加兴趣关键词: {extra}")
                keyword = f"{keyword} {extra}"
    except Exception:
        pass

    # 提取关键词里的核心词 (去掉 "测评", "视频" 这种通用词，保留核心如 "S11")
    # 简单的做法：直接用完整关键词匹配，或者提取字母/数字
    # 这里我们做一个简单的清洗，去掉空格
    clean_keyword = keyword.replace(" ", "")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"   🔍 正在搜索 (目标: {keyword}, 第 {attempt+1} 次尝试)...")
            
            img_key, sub_key = wbi_signer.getWbiKeys()
            if not img_key: return None
            
            params = { 
                "search_type": "video", 
                "keyword": keyword,
                "page": 1,
                "page_size": 20 
            }
            signed_params = wbi_signer.encWbi(params, img_key, sub_key)
            
            resp = requests.get(
                "https://api.bilibili.com/x/web-interface/search/type",
                params=signed_params,
                headers=headers,
                timeout=5
            )
            
            if resp.status_code != 200:
                raise Exception(f"HTTP状态码异常: {resp.status_code}")

            data = resp.json()
            
            # 定义两个池子
            vip_pool = []    # 既有高播放，标题又精准匹配的
            normal_pool = [] # 只有高播放的

            if data['code'] == 0 and data['data'].get('result'):
                video_list = data['data']['result']
                
                for video in video_list:
                    try:
                        play_count = int(video.get('play', 0))
                    except:
                        continue 
                    
                    # 基础门槛：播放量要够
                    if play_count >= 10000: # 稍微降低门槛到1w，防止新品评测播放还没上去
                        title = video['title'].replace('<em class="keyword">', '').replace('</em>', '').replace('&quot;', '"')
                        
                        # 🎯 核心逻辑：标题匹配度检查
                        # 检查 keyword 里的关键字符是否在标题里
                        # 比如搜 "S11"，标题必须有 "S11" (忽略大小写)
                        
                        # 这里用一个简单的策略：如果搜索词里的“字母和数字”在标题里出现了，就算精准
                        # 例如：keyword="苹果S11", 提取出 "S11"。如果标题里有 "S11"，就进 VIP。
                        import re
                        key_tokens = re.findall(r'[a-zA-Z0-9]+', keyword) # 提取英文数字，如 ['S11']
                        
                        is_match = True
                        if key_tokens:
                            # 如果有英文数字关键词，必须全部匹配
                            for token in key_tokens:
                                if token.lower() not in title.lower():
                                    is_match = False
                                    break
                        else:
                            # 如果全是中文，就看包含关系
                            if keyword not in title: 
                                # 尝试放宽一点，只取前两个字？不，保持严格
                                # 如果标题不包含完整关键词，降级为普通池
                                is_match = False

                        video_data = {
                            "title": title,
                            "author": video['author'],
                            "url": f"https://www.bilibili.com/video/{video['bvid']}",
                            "play": play_count
                        }

                        if is_match:
                            vip_pool.append(video_data)
                        else:
                            normal_pool.append(video_data)

                # 🎲 抽奖环节
                final_choice = None
                
                if vip_pool:
                    print(f"   💎 命中 {len(vip_pool)} 个精准匹配视频，优先抽取...")
                    final_choice = random.choice(vip_pool)
                elif normal_pool:
                    print(f"   ⚠️ 无精准匹配，从 {len(normal_pool)} 个泛相关视频中抽取...")
                    final_choice = random.choice(normal_pool)
                
                if final_choice:
                    print(f"   ✅ 最终选择: {final_choice['title']} (播放: {final_choice['play']})")
                    return final_choice['title'], final_choice['author'], final_choice['url']
                else:
                    # 如果这页没合适的，就直接break，不用重试了
                    print("   ❌ 未找到合适视频")
                    break

        except Exception as e:
            print(f"   ⚠️ 第 {attempt+1} 次搜索异常: {e}")
            if attempt < max_retries - 1:
                time.sleep(1.5)
                
    return None
    
def web_search_fetch(keyword):
    """
    【联网阅读技能】(专注 Bing 暴力清洗版)
    """
    print(f"   🌐 正在后台阅读 Bing 信息: {keyword} ...")

    # --- 1. 尝试 DuckDuckGo (API方式，最干净) ---
    search_results = ""
    try:
        from duckduckgo_search import DDGS
        # 增加 timeout 防止卡死
        with DDGS(timeout=10) as ddgs:
            results = list(ddgs.text(keyword, max_results=3))
            if results:
                for i, res in enumerate(results):
                    title = res.get('title', '无标题')
                    body = res.get('body', res.get('snippet', '无内容'))
                    search_results += f"【来源{i+1}】{title}\n内容：{body}\n\n"
                
                if len(search_results) > 20:
                    print("   ✅ DuckDuckGo 搜索成功")
                    return search_results
    except Exception as e:
        print(f"   ⚠️ DDG 暂不可用 ({e})，切换网页爬虫...")

    # --- 2. DuckDuckGo 不通就抓 Bing 的搜索结果页 ---
    url = f"https://cn.bing.com/search?q={urllib.parse.quote(keyword)}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://cn.bing.com/" # 👈 记得修改 Referer
    }

    print(f"   🚀 启动 Bing 暴力爬虫...")
    try:
        res = requests.get(url, headers=headers, timeout=8)
        res.encoding = 'utf-8'
        
        raw_text = clean_html_violent(res.text) # 复用你已有的清洗函数
        useful_text = raw_text[:1500]
        
        if len(useful_text) > 100:
            print(f"   ✅ Bing 抓取成功")
            return f"【Bing 搜索结果摘要】：\n{useful_text}..."
    except Exception as e:
        print(f"   ❌ Bing 爬取失败: {e}")

    return None

def start_countdown(seconds, content):
    """
    异步倒计时函数
    """
    def _timer_task():
        print(f"   ⏳ 倒计时开始: {seconds}秒后提醒 [{content}]")
        # 1. 睡眠 (不卡主线程)
        time.sleep(seconds)
        
        # 2. 时间到了，播放声音
        # 注意：为了避免循环引用，我们在函数内部引用 tts
        import tts 
        print(f"   ⏰ 时间到！提醒内容: {content}")
        import ai_brain
        name = ai_brain.get_last_active_user() or ""
        tts.speak(f"{name}，时间到啦！别忘了：{content}" if name else f"时间到啦！别忘了：{content}")

    # 启动一个后台线程跑这个任务，这样主程序可以继续听你说话
    threading.Thread(target=_timer_task).start()
    return True

def save_note(content):
    """
    闪念胶囊：保存内容到桌面备忘录
    """
    import os
    from datetime import datetime
    
    # 自动获取当前用户的桌面路径
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    file_path = os.path.join(desktop, "memo.txt")
    
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 以追加模式('a')写入，不会覆盖旧内容
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {content}\n")
        print(f"   📝 已写入备忘录: {file_path}")
        return True
    except Exception as e:
        print(f"   ❌ 记录失败: {e}")
        return False