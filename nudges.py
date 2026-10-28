"""
观察提醒：observer.py 发现摸鱼、熬夜、太累等情况后，这里决定要不要开口、说什么
"""
import time

import ai_brain


class InterventionManager:
    def __init__(self):
        self.last_intervention_time = 0
        # 两次提醒至少隔 30 分钟 (深夜写代码例外)
        self.BASE_COOLDOWN = 1800 
        
        # 🌟 [新增] 事件画像：定义每个事件的“性格”
        self.EVENT_PROFILES = {
            "late_night_coding": {"priority": 100, "interrupt": True},  # 高危：必须打断
            "attention_fragmented": {"priority": 95, "interrupt": True}, # 碎片化：高优，但语气要软
            "distraction_video": {"priority": 90, "interrupt": True},    # 摸鱼：中等
            "gaming_addiction": {"priority": 60, "interrupt": True},
            "fatigue": {"priority": 80, "interrupt": True}              # 疲劳：低优 (别老抢戏)
        }
    
    def should_interrupt(self, heartbeat_data, current_mood):
        """
        🧠 决策核心：判断是否应该打断用户
        """
        if not heartbeat_data: return False, None
        
        events = heartbeat_data.get("events", [])
        if not events: return False, None

        now = time.time()
        time_since_last = now - self.last_intervention_time
        
        # 1. 动态冷却计算
        cooldown = self.BASE_COOLDOWN
        # 如果心情不好，AI 变冷淡，冷却翻倍
        if current_mood in ["tired", "irritated"]:
            cooldown *= 1.5
            
        # 2. 紧急事件豁免权 (深夜修仙直接穿透冷却)
        is_emergency = any(e['type'] == 'late_night_coding' for e in events)
        if not is_emergency and time_since_last < cooldown:
            return False, None

        # 3. 优先级仲裁 (基于 EVENT_PROFILES)
        # 选出优先级最高的事件
        best_event = max(events, key=lambda e: self.EVENT_PROFILES.get(e['type'], {}).get("priority", 0))
        
        # 4. 最终决定
        # (这里未来可以扩展：如果 interrupt=False，可以存入 pending_events 等下次对话再说)
        # 目前为了演示效果，我们默认都 True，但在生成话术时做区分
        
        self.last_intervention_time = now
        return True, best_event


manager = InterventionManager()


def generate_reaction(heartbeat_data, current_user=None):
    """
    已经确定要干预了，直接生成 LLM 回复
    """
    events = heartbeat_data.get("events", [])
    if not events: return None
    
    # 1. 再次确认优先级 (保持和 Manager 一致)
    priority_map = manager.EVENT_PROFILES
    event = max(events, key=lambda e: priority_map.get(e['type'], {}).get("priority", 0))
    
    current_mood = "neutral" 

    # 根据传入的 current_user 做个简单的人格化处理
    user_profile = None
    user_name = current_user
    if current_user:
        try:
            user_profile = ai_brain.get_user_profile(current_user)
            if user_profile:
                user_name = user_profile.get('name', current_user)
        except Exception:
            user_profile = None
    if not user_name:
        user_name = "用户"
    
    # =================================================
    # 🌟 方案 C 核心：专属人格通道 (Event Specific Prompt)
    # =================================================
    
    if event['type'] == 'attention_fragmented':
        # 🟢 专属通道：温柔提醒 + 提供工具 (番茄钟)
        prompt = f"""
        【当前用户】：{user_name}。
        【环境感知】：用户在过去20分钟内，在代码编辑器和视频窗口之间频繁切换了{event.get('count', 0)}次。
        【诊断】：注意力碎片化 (Attention Fragmentation)。
        【当前AI心情】：{current_mood}。
        
        请生成一句温柔、有建设性的提醒。
        要求：
        1. ❌ 绝对不要指责用户摸鱼，不要说教。
        2. ✅ 语气要像朋友一样，指出“来回切窗口”有点难专心。
        3. ✅ 核心任务：试探性地建议：“要不要帮你定个25分钟的专注闹钟？” (番茄钟法)。
        4. 字数控制在40字以内，口语化。
        """
        
    elif event['type'] == 'distraction_video':
        # 🟡 摸鱼通道：调侃 + 提醒
        prompt = f"""
        【当前用户】：{user_name}。
        【环境感知】：用户正在写代码，但过去30分钟里看视频累计超过{event.get('duration', 0):.1f}分钟。
        【诊断】：明显的摸鱼行为。
        【当前AI心情】：{current_mood}。
        
        请生成一句俏皮的提醒。
        要求：
        1. 轻松逗趣，不要说教、不要毒舌（比如“呀，视频好看吗？代码在等你哦~”）。
        2. 或者幽默地提醒他进度。
        3. 30字以内。
        """
        
    else:
        # ⚪ 通用兜底通道 (疲劳、深夜等)
        desc_map = {
            "late_night_coding": "深夜还在写代码",
            "fatigue": f"高强度工作累计超过{event.get('value', 0)}分钟",
            "gaming_addiction": "沉迷游戏时间过长"
        }
        # 按这位成员登记时选的态度来说 (温柔贴心 / 元气满满 / 允许吐槽……)
        style = (user_profile or {}).get("interaction_style", {})
        persona_hint = ""
        if style.get("tone"):
            persona_hint = f"（对TA说话的态度：{style['tone']}" + ("，可以开个小玩笑）" if style.get("allow_roast") else "，语气温柔一点）")

        prompt = f"""
        【当前用户】：{user_name}。
        【环境感知触发】：{desc_map.get(event['type'], '异常')}。
        【当前AI心情】：{current_mood}。
        {persona_hint}
        生成一句30字以内的提醒。
        """

    # =================================================
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt > 0: print(f"   🔄 正在尝试连接大脑 (第 {attempt+1} 次)...")
            
            response = ai_brain.client.chat.completions.create(
                model=ai_brain.MODEL_NAME,
                messages=[{"role": "system", "content": ai_brain.eureka_persona(user_name)},
                          {"role": "user", "content": prompt}],
                temperature=0.7,
                timeout=10 # 建议加上超时
            )
            return {"text": response.choices[0].message.content, "event_type": event['type']}
        
        except Exception as e:
            print(f"   ⚠️ API 连接失败 ({attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1) # 歇一秒再试
            else:
                return {"text": "注意休息。", "event_type": "default"}
