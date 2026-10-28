import os
import sys
import torch
import torchaudio
import huggingface_hub
import soundfile as sf
import numpy as np
# ==============================================================
# 🛡️ 尤里卡专属底层防爆盾 (Monkey Patches) 终极版
# ==============================================================

# 0. 提前设置 Hugging Face 国内镜像源
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 1. 动态修复 torchaudio 的版本断层 BUG
if not hasattr(torchaudio, 'list_audio_backends'):
    torchaudio.list_audio_backends = lambda: ['soundfile']

# 2. 动态修复 huggingface_hub，并施展“空城计”拦截 custom.py 报错
_orig_download = huggingface_hub.hf_hub_download
def _patched_download(*args, **kwargs):
    # 修复旧参数名
    if 'use_auth_token' in kwargs:
        kwargs['token'] = kwargs.pop('use_auth_token')
    
    try:
        # 尝试正常下载
        return _orig_download(*args, **kwargs)
    except Exception as e:
        # 核心魔法：如果是因为找不到 custom.py 报错，直接丢给它一个空的假文件
        if kwargs.get('filename') == 'custom.py' or 'custom.py' in str(e):
            print("   🛡️ [防爆盾] 拦截到 custom.py 幽灵报错，已伪造空文件放行...")
            dummy_path = os.path.abspath("dummy_custom.py")
            if not os.path.exists(dummy_path):
                with open(dummy_path, 'w', encoding='utf-8') as f:
                    f.write("") # 写入空内容骗过系统
            return dummy_path
        # 如果是其他严重错误，依然抛出
        raise e

huggingface_hub.hf_hub_download = _patched_download

# ==============================================================
from speechbrain.inference.speaker import EncoderClassifier

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

class VoiceprintManager:
    def __init__(self):
        print("--- 正在加载声纹识别大模型 (首次运行需下载) ---")
        # 使用业界经典的 ECAPA-TDNN 模型，专门用于声纹比对
        self.classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb", 
            savedir=os.path.join(get_app_path(), "models", "spkrec-ecapa-voxceleb"),
            run_opts={"device": "cpu"} # 如果你有N卡可以换成 "cuda"
        )
        
        self.profiles_dir = os.path.join(get_app_path(), "voice_profiles")
        os.makedirs(self.profiles_dir, exist_ok=True)
        
        # 预先加载已注册的声纹特征
        self.enrolled_profiles = {}
        self.load_profiles()

    def extract_embedding(self, wav_path):
        """提取一段音频的声纹向量 (完全绕过 torchaudio 的加载 bug)"""
        # 1. 使用老实人 soundfile 直接把 wav 读成 numpy 数组
        data, fs = sf.read(wav_path)
        
        # 2. 如果录音不小心录成了双声道，强制混音成单声道
        if len(data.shape) > 1:
            data = np.mean(data, axis=1)
            
        # 3. 转换成 PyTorch 需要的张量格式，并套上一层 Batch 维度: (1, 长度)
        signal = torch.from_numpy(data).float().unsqueeze(0)
        
        # 4. 如果手机录音不是 16000 采样率，用纯数学公式重采样 (不依赖音频解码器)
        if fs != 16000:
            resampler = torchaudio.transforms.Resample(orig_freq=fs, new_freq=16000)
            signal = resampler(signal)
            
        # 5. 丢给大模型提取特征
        with torch.no_grad():
            embeddings = self.classifier.encode_batch(signal)
            
        return embeddings.squeeze()

    def load_profiles(self):
        """加载本地保存的声纹特征"""
        for file in os.listdir(self.profiles_dir):
            if file.endswith(".pt"):
                name = file.replace(".pt", "")
                tensor_path = os.path.join(self.profiles_dir, file)
                self.enrolled_profiles[name] = torch.load(tensor_path)
                print(f"   📂 已加载用户声纹: {name}")

    def enroll_user(self, name, wav_path):
        """注册新用户：提取向量并保存为 .pt 文件"""
        embedding = self.extract_embedding(wav_path)
        save_path = os.path.join(self.profiles_dir, f"{name}.pt")
        torch.save(embedding, save_path)
        self.enrolled_profiles[name] = embedding
        print(f"✅ 用户 [{name}] 声纹注册成功！")

    def identify_user(self, wav_path, threshold=0.50): # 👈 将默认及格线从 0.65 降到 0.50
        """识别当前说话人是谁"""
        if not self.enrolled_profiles:
            return "unknown"
            
        current_emb = self.extract_embedding(wav_path)
        
        best_match = None
        highest_score = -1.0
        
        # 将当前声音与所有注册过的声纹进行相似度打分
        cos = torch.nn.CosineSimilarity(dim=-1)
        print("\n   📊 --- 声纹比对雷达 ---")
        for name, saved_emb in self.enrolled_profiles.items():
            score = cos(current_emb, saved_emb).item()
            print(f"   [比对] 与 {name} 的相似度: {score:.3f}") # 👈 打印真实得分
            if score > highest_score:
                highest_score = score
                best_match = name
        print("   ------------------------")
                
        # 超过阈值才认为是同一个人
        if highest_score > threshold:
            return best_match
        else:
            return "unknown"

# 实例化一个全局单例供主程序调用
vp_manager = VoiceprintManager()