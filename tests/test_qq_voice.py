"""QQ 语音的小工具：切分、挑附件、WAV 检查。全部离线，不联网、不碰麦克风"""
import wave

import qq_voice


def _write_wav(path, seconds=1.0, rate=8000):
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * frames)


def test_parse_choice_ignores_typos_and_comments():
    assert qq_voice.parse_choice("voice", qq_voice.VOICE_REPLY_MODES, "auto") == "voice"
    assert qq_voice.parse_choice(" VOICE ", qq_voice.VOICE_REPLY_MODES, "auto") == "voice"
    assert qq_voice.parse_choice("vocie", qq_voice.VOICE_REPLY_MODES, "auto") == "auto"
    assert qq_voice.parse_choice(None, qq_voice.VOICE_REPLY_MODES, "auto") == "auto"
    assert qq_voice.parse_choice("#whisper", qq_voice.STT_MODES, "auto") == "auto"
    assert qq_voice.parse_choice("whisper", qq_voice.STT_MODES, "auto") == "whisper"


def test_wants_voice_reply_follows_the_incoming_message():
    assert qq_voice.wants_voice_reply("auto", True)
    assert not qq_voice.wants_voice_reply("auto", False)
    assert qq_voice.wants_voice_reply("voice", False)
    assert not qq_voice.wants_voice_reply("text", True)


def test_pick_voice_prefers_the_converted_wav():
    voice = qq_voice.pick_voice([
        {"content_type": "image/png", "url": "https://example.test/1.png"},
        {"content_type": "voice", "url": "https://example.test/a.silk",
         "voice_wav_url": "https://example.test/a.wav", "asr_refer_text": " 你好呀 "},
    ])
    assert voice == {"url": "https://example.test/a.wav", "is_wav": True, "asr": "你好呀"}


def test_pick_voice_falls_back_to_the_silk_url():
    voice = qq_voice.pick_voice([{"content_type": "voice", "url": "https://example.test/a.silk"}])
    assert voice == {"url": "https://example.test/a.silk", "is_wav": False, "asr": ""}


def test_pick_voice_ignores_other_attachments():
    assert qq_voice.pick_voice(None) is None
    assert qq_voice.pick_voice([]) is None
    assert qq_voice.pick_voice([{"content_type": "image/png", "url": "x"}]) is None
    assert qq_voice.pick_voice([{"content_type": "voice"}]) is None
    assert qq_voice.pick_voice([None, "oops"]) is None


def test_placeholder_text_is_not_treated_as_a_message():
    assert qq_voice.placeholder_text("[语音]")
    assert qq_voice.placeholder_text(" [语音消息] ")
    assert not qq_voice.placeholder_text("今天天气怎么样")
    assert not qq_voice.placeholder_text("")


def test_split_text_respects_limit_and_reply_quota():
    assert qq_voice.split_text("abcdefg", 3, 2) == ["abc", "def"]
    assert qq_voice.split_text("abc", 500) == ["abc"]
    assert qq_voice.split_text("", 500) == []
    assert qq_voice.split_text("abc", 0) == []
    assert qq_voice.split_text("abc", 500, 0) == []


def test_short_reply_is_all_spoken():
    assert qq_voice.split_voice_reply("早上好呀", 200) == ("早上好呀", "")


def test_long_reply_breaks_at_a_sentence_end():
    text = "第一句话说完了。这里还有第二句话没有说完就超了"
    spoken, rest = qq_voice.split_voice_reply(text, 10)
    assert spoken == "第一句话说完了。"
    assert rest == "这里还有第二句话没有说完就超了"


def test_long_reply_without_a_sentence_breaks_at_a_clause():
    text = "第一段没有句号，第二段也没有句号，第三段也没有句号"
    spoken, rest = qq_voice.split_voice_reply(text, 12)
    assert spoken == "第一段没有句号，"
    assert spoken + rest == text


def test_long_reply_without_punctuation_is_cut_at_the_limit():
    text = "啊" * 30
    assert qq_voice.split_voice_reply(text, 10) == ("啊" * 10, "啊" * 20)


def test_wav_seconds_reads_the_duration(tmp_path):
    path = tmp_path / "ok.wav"
    _write_wav(path, seconds=1.5)
    assert qq_voice.wav_seconds(str(path)) == 1.5


def test_voice_file_ok_checks_duration(tmp_path):
    path = tmp_path / "long.wav"
    _write_wav(path, seconds=2.0)
    assert qq_voice.voice_file_ok(str(path))
    assert not qq_voice.voice_file_ok(str(path), max_seconds=1.0)


def test_voice_file_ok_checks_size(tmp_path):
    path = tmp_path / "big.wav"
    _write_wav(path, seconds=1.0)
    assert not qq_voice.voice_file_ok(str(path), max_bytes=10)


def test_voice_file_ok_rejects_missing_or_unreadable_files(tmp_path):
    assert not qq_voice.voice_file_ok(str(tmp_path / "missing.wav"))
    silk = tmp_path / "voice.silk"
    silk.write_bytes(b"SILK" + b"\x00" * 64)
    assert qq_voice.wav_seconds(str(silk)) == 0.0
    assert qq_voice.voice_file_ok(str(silk))
