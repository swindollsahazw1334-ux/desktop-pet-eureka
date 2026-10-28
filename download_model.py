"""
提前把要用的本地模型下好 (平时不用手动跑，第一次用到时也会自动下载)：
    唤醒词模型 (sherpa-onnx，约 31MB)
    语音识别模型 (faster-whisper，按 settings.json 里的 whisper_model，默认 small)
"""
import json
import os

from faster_whisper import download_model

import wakeword

print("1/2 唤醒词模型...")
print("   ✅ 已就绪" if wakeword.ensure_model() else "   ❌ 下载失败，检查网络后再试")

try:
    with open("settings.json", "r", encoding="utf-8") as f:
        size = json.load(f).get("whisper_model", "small")
except Exception:
    size = "small"

output_dir = os.path.join("models", f"faster-whisper-{size}")
print(f"2/2 语音识别模型 {size} → {output_dir} ...")
model_path = download_model(size, output_dir=output_dir)
print(f"   ✅ 已就绪: {model_path}")
