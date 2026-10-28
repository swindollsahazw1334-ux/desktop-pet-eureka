import pyaudio
import wave
import audioop
import time
import sys
import os 


def get_app_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# --- 配置参数 ---
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
WAVE_OUTPUT_FILENAME = os.path.join(get_app_path(), "input.wav")

# 🎚️ 灵敏度设置
THRESHOLD = 500              
SILENCE_LIMIT = 3            
MAX_RECORD_SECONDS = 15      
MAX_WAIT_SECONDS = 5         

def record_audio(threshold=500, stop_check=None):
    p = pyaudio.PyAudio()
    stream = None
    
    try:
        stream = p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK)

        # 👇 修改点 2：打印当前的阈值，方便你调试
        print(f">>> 🔴 正在聆听... (当前灵敏度阈值: {threshold})")
        
        frames = []
        silent_chunks = 0
        has_started = False
        start_time = time.time()
        
        chunks_per_second = RATE / CHUNK
        silence_threshold_chunks = SILENCE_LIMIT * chunks_per_second

        while True:
            # 👇👇👇 [核心插入]：每次读取音频前，看一眼主程序有没有发来中断信号
            if stop_check and stop_check():
                print("\n>>> 🛑 录音过程被手动打断！放弃倾听。")
                return False # 直接返回 False。底部的 finally 会自动帮你关掉麦克风！

            data = stream.read(CHUNK)
            frames.append(data)
            
            rms = audioop.rms(data, 2)
            
            # 👇 修改点 3：这里使用传入的 threshold 变量，而不是全局常量
            if rms > threshold:
                silent_chunks = 0
                if not has_started:
                    print("   🎤 检测到人声，开始记录...")
                    has_started = True
            else:
                if has_started:
                    silent_chunks += 1

            # 2. 正常结束
            if has_started and silent_chunks > silence_threshold_chunks:
                print("\n>>> 🛑 说话结束 (检测到静音)")
                break
            
            # 3. 超时保险 A
            if not has_started and (time.time() - start_time > MAX_WAIT_SECONDS):
                print("\n>>> ⚠️ 没人说话，取消录音")
                return False

            # 4. 超时保险 B
            if len(frames) > chunks_per_second * MAX_RECORD_SECONDS:
                print("\n>>> ⏱️ 说话时间太长，强制结束")
                break

        # 👇👇👇 修改点：这里删除了手动关闭的代码，全部交给 finally 处理 👇👇👇
        # (原先这里有 stream.stop_stream() 等代码，现在去掉了)

        # 保存文件
        if has_started:
            wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
            wf.close()
            return True
        else:
            return False

    except Exception as e:
        import notify
        notify.report(e, "录音 / 麦克风")
        return False
        
    finally:
        # 🛡️ 最终安全防线：无论上面成功还是失败，都在这里统一关闭
        try:
            if stream:
                stream.stop_stream()
                stream.close()
            if p:
                p.terminate()
        except Exception as e:
            # 这里如果报错，通常可以忽略，因为说明已经关掉了
            pass

if __name__ == "__main__":
    record_audio()