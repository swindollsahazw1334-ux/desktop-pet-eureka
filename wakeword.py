import pyaudio
import numpy as np
import os
import time
import sys
import sherpa_onnx
import character

def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# 中文关键词唤醒 (sherpa-onnx)，不用训练，唤醒词直接写拼音
MODEL_NAME = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
MODEL_DIR = os.path.join(get_app_path(), "models", MODEL_NAME)
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{MODEL_NAME}.tar.bz2"
MODEL_FILES = ("tokens.txt",
               "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
               "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
               "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx")

# 唤醒词：拼音按声母、带声调的韵母拆开，用空格隔开，@ 后面是显示名
# 拼法可以对照模型目录里 test_wavs/test_keywords.txt 的写法
WAKE_WORDS = character.wake_words()  # 在 character.json 里改

SAMPLE_RATE = 16000
CHUNK = 1600  # 每次读 0.1 秒

_spotter = None
_spotter_threshold = None


def ensure_model():
    """唤醒模型不在就从 sherpa-onnx 的发布页下载 (约 31MB)，只解压用得到的几个文件。成功返回 True"""
    if all(os.path.exists(os.path.join(MODEL_DIR, f)) for f in MODEL_FILES):
        return True
    import tarfile
    import tempfile
    import requests
    import notify
    notify.notice("第一次用语音唤醒，正在下载唤醒模型 (约 30MB)，稍等一下哦~", key="kws_download")
    print(f"⬇️ 正在下载唤醒模型: {MODEL_URL}")
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "kws.tar.bz2")
            for attempt in range(3):  # 代理/网络抖一下就断的话多试两次
                try:
                    with requests.get(MODEL_URL, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(archive, "wb") as f:
                            for block in r.iter_content(1 << 16):
                                f.write(block)
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    print(f"   ⚠️ 下载中断，重试第 {attempt + 2} 次…")
            with tarfile.open(archive, "r:bz2") as tar:
                for member in tar.getmembers():
                    name = os.path.basename(member.name)
                    if member.isfile() and name in MODEL_FILES:
                        member.name = name
                        tar.extract(member, MODEL_DIR, filter="data")
        print("✅ 唤醒模型下载完成")
        return True
    except Exception as e:
        notify.report(e, "下载唤醒模型")
        return False


def _threshold_from_sensitivity(sensitivity):
    """
    设置里的唤醒灵敏度 0~1 换算成 sherpa 的触发阈值：
    数值越大阈值越高，越难唤醒、越不容易误唤醒。0.5 对应模型默认值 0.25
    """
    return round(0.10 + 0.30 * max(0.0, min(1.0, sensitivity)), 3)


def _get_spotter(sensitivity):
    """模型只加载一次，常驻内存；灵敏度变了才重建"""
    global _spotter, _spotter_threshold
    threshold = _threshold_from_sensitivity(sensitivity)
    if _spotter is not None and threshold == _spotter_threshold:
        return _spotter

    keywords_file = os.path.join(MODEL_DIR, "keywords.txt")
    with open(keywords_file, "w", encoding="utf-8") as f:
        f.write("\n".join(WAKE_WORDS) + "\n")

    _spotter = sherpa_onnx.KeywordSpotter(
        tokens=os.path.join(MODEL_DIR, "tokens.txt"),
        encoder=os.path.join(MODEL_DIR, "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        decoder=os.path.join(MODEL_DIR, "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        joiner=os.path.join(MODEL_DIR, "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        keywords_file=keywords_file,
        num_threads=1,
        keywords_threshold=threshold,
    )
    _spotter_threshold = threshold
    print(f"✅ 唤醒模型已加载 (阈值 {threshold})")
    return _spotter


def detect_in_samples(samples, sensitivity=0.5):
    """在一段 16kHz float32 音频里找唤醒词，返回命中的词或 None (测试用)"""
    spotter = _get_spotter(sensitivity)
    stream = spotter.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    stream.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        result = spotter.get_result(stream)
        if result:
            return result
    return None


def wait_for_wake_word(check_interrupt=None, sensitivity=0.5):
    """
    监听唤醒词，听到返回 True；check_interrupt 返回 True 时也立即返回 True
    """
    if not ensure_model():
        print(f"❌ 找不到唤醒模型: {MODEL_DIR}")
        return False
    if not MODEL_DIR.isascii():
        # sherpa-onnx 在 Windows 上读不了带中文的路径，会报 "No graph was found in the protobuf"
        import notify
        notify.notice("程序放在了带中文的文件夹里，唤醒模型读不了…把整个文件夹挪到全英文路径 (比如 D:\\EurekaPet) 就好啦。"
                      "现在可以双击我来说话", key="kws_ascii")

    audio = None
    mic_stream = None
    try:
        spotter = _get_spotter(sensitivity)
        kws_stream = spotter.create_stream()

        audio = pyaudio.PyAudio()
        mic_stream = audio.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                                input=True, frames_per_buffer=CHUNK)

        print(f"👂 正在监听唤醒词：{' / '.join(w.split('@')[-1] for w in WAKE_WORDS)} ...")

        while True:
            if check_interrupt and check_interrupt():
                print("   ⚡ 接到打断/主动干预指令！")
                return True

            pcm = mic_stream.read(CHUNK, exception_on_overflow=False)
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            kws_stream.accept_waveform(SAMPLE_RATE, samples)

            while spotter.is_ready(kws_stream):
                spotter.decode_stream(kws_stream)
                result = spotter.get_result(kws_stream)
                if result:
                    print(f"\n⚡ 唤醒词 '{result}' 已触发！")
                    spotter.reset_stream(kws_stream)
                    return True

    except Exception as e:
        import notify
        notify.report(e, "唤醒词 / 麦克风")
        # 模型或麦克风坏了，主循环会马上重试：先歇几秒，免得刷屏占 CPU (期间仍能被打断)
        for _ in range(50):
            if check_interrupt and check_interrupt():
                return True
            time.sleep(0.1)
        return False

    finally:
        try:
            if mic_stream is not None:
                mic_stream.stop_stream()
                mic_stream.close()
            if audio is not None:
                audio.terminate()
        except:
            pass

if __name__ == "__main__":
    wait_for_wake_word()
