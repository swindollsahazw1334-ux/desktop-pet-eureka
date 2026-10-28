from functools import reduce
from hashlib import md5
import urllib.parse
import time
import requests
import uuid

# 混淆密钥表
mixinKeyEncTab = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

def getMixinKey(orig: str):
    return reduce(lambda s, i: s + orig[i], mixinKeyEncTab, "")[:32]

def encWbi(params: dict, img_key: str, sub_key: str):
    mixin_key = getMixinKey(img_key + sub_key)
    curr_time = round(time.time())
    params['wts'] = curr_time
    params = dict(sorted(params.items()))
    params = {
        k: ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    wbi_sign = md5((query + mixin_key).encode()).hexdigest()
    params['w_rid'] = wbi_sign
    return params

def getWbiKeys():
    # 你的 SESSDATA
    SESSDATA = "d65dc5dc%2C1780239256%2Cb00ea%2Ac1CjB24BP1wKTi2NPxlXRPA074tF9-0c7lq_BtCpSlPq-ofA8CNfLuL71vWZPicX1HYR0SVlBPVFUtbFVNMFhhaHVtT3Nvb3ZCVElscjJrdVZTV2M0a21DOXZBVVZidE45NXBjeTY0X1dvb0tQOUltcFN0OWRtWGpPckYxYlU0RFN5eTZhWlhjOUJBIIEC"
    
    # 补全设备ID (buvid3)
    BUVID3 = "84D21716-1681-4940-8422-77119106093322115infoc"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": f"SESSDATA={SESSDATA}; buvid3={BUVID3};"
    }
    try:
        resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers, timeout=5)
        resp.raise_for_status()
        json_content = resp.json()
        
        img_url = json_content['data']['wbi_img']['img_url']
        sub_url = json_content['data']['wbi_img']['sub_url']
        return img_url.rsplit('/', 1)[1].split('.')[0], sub_url.rsplit('/', 1)[1].split('.')[0]
    except Exception as e:
        print(f"❌ 获取 Wbi 密钥失败: {e}")
        return None, None