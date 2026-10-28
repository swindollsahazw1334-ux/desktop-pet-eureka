import os
import time
import sys
import json
import threading
# 彻底不再引用 modelscope 和 datasets
from faster_whisper import WhisperModel

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# --- 配置参数 ---
# 模型大小在 settings.json 的 "whisper_model" 里改：
# "tiny", "base", "small"(默认，常驻后台够用), "medium", "large-v3-turbo"(最准但最吃内存)
DEFAULT_MODEL = "small"
FALLBACK_MODEL = "large-v3-turbo"  # 新模型下载失败时，退回已经下好的这个
DEVICE = "cpu"        # 9700X 单核极强，CPU 跑 int8 量化也是秒出结果
COMPUTE_TYPE = "int8" # 量化模式

MODELS_DIR = os.path.join(get_app_path(), "models")


def _configured_model():
    try:
        with open(os.path.join(get_app_path(), "settings.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("whisper_model", DEFAULT_MODEL)
    except Exception:
        return DEFAULT_MODEL


def _load(size):
    """优先用 models/faster-whisper-<size>，没有就下载到那里"""
    local_path = os.path.join(MODELS_DIR, f"faster-whisper-{size}")
    if os.path.exists(os.path.join(local_path, "model.bin")):
        print(f"📂 使用本地模型路径: {local_path}")
        return WhisperModel(local_path, device=DEVICE, compute_type=COMPUTE_TYPE)

    print(f"⬇️ 本地未找到 {size} 模型，正在下载到 {local_path} ...")
    from faster_whisper import download_model
    download_model(size, output_dir=local_path)
    return WhisperModel(local_path, device=DEVICE, compute_type=COMPUTE_TYPE)


MODEL_SIZE = _configured_model()
model = None
_load_lock = threading.Lock()


def ensure_model():
    """第一次用到时才加载 (实时语音模式下根本用不到它，启动就快很多)"""
    global model, MODEL_SIZE
    with _load_lock:
        if model is not None:
            return model
        print(f"--- 正在加载 Whisper 模型 ({MODEL_SIZE}) ---")
        for size in dict.fromkeys([MODEL_SIZE, FALLBACK_MODEL]):
            try:
                model = _load(size)
                MODEL_SIZE = size
                print(f"✅ Whisper 模型加载完成！({size})")
                break
            except Exception as e:
                print(f"❌ 模型 {size} 加载失败: {e}")
        return model


def speech_to_text(audio_file="input.wav"):
    if ensure_model() is None:
        return ""

    try:
        print(f">>> 正在转录 (Faster-Whisper)...")
        start_time = time.time()

        # language="zh" 强制指定中文，避免因为杂音识别成其他语言
        # initial_prompt 用简体中文开头，防止小模型输出繁体
        # vad_filter 跳过静音段 (录音结尾固定有 3 秒静音)，又快又不容易瞎编
        segments, info = model.transcribe(audio_file, beam_size=5, language="zh",
                                          initial_prompt="以下是普通话的句子。", vad_filter=True)

        # Whisper 返回的是生成器，需要遍历取出结果
        result_text = ""
        for segment in segments:
            result_text += segment.text

        end_time = time.time()

        result = result_text.strip()
        if not result:
            return ""

        print(f"<<< 转录完成 ({end_time - start_time:.3f}s)")
        print(f"识别结果: 【 {result} 】")

        return result

    except Exception as e:
        print(f"❌ 转录出错: {e}")
        return None

if __name__ == "__main__":
    # 测试一下
    speech_to_text("input.wav")
