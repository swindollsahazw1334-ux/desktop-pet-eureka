"""朗读前的文字清理：横杠、破折号和 markdown 不该被念出来"""
import tts


def test_bullet_dashes_are_removed():
    assert tts._speakable("- 第一点\n- 第二点") == "第一点\n第二点"


def test_em_dashes_and_underline_are_removed():
    assert tts._speakable("——这样——") == "这样"
    assert tts._speakable("—— 分隔线 ——") == "分隔线"
    assert tts._speakable("这样——那样") == "这样，那样"


def test_dates_lose_hyphens_but_negative_numbers_keep_them():
    assert tts._speakable("2026-10-29 见面") == "2026 10 29 见面"
    assert tts._speakable("3-5天") == "3 5天"
    assert tts._speakable("温度 -5 度") == "温度 -5 度"


def test_markdown_marks_are_removed():
    assert tts._speakable("**重点**和`代码`") == "重点和代码"
    assert tts._speakable("## 标题") == "标题"


def test_action_and_emotion_tags_stay_out_of_speech():
    assert tts._speakable("（挥挥手）你好呀[表情:得意]") == "你好呀"


def test_english_hyphenated_words_drop_the_hyphen():
    assert tts._speakable("GPT-4 很强") == "GPT 4 很强"


def test_unicode_dashes_are_removed():
    assert tts._speakable("2026‑10‑29 见") == "2026 10 29 见"
    assert tts._speakable("5−3 等于 2") == "5 3 等于 2"


def test_tildes_and_ellipses_become_pauses():
    assert tts._speakable("好呀～那我唱两句") == "好呀，那我唱两句"
    assert tts._speakable("哼～") == "哼"
    assert tts._speakable("等等…") == "等等"


def test_symbol_names_are_not_spoken():
    assert tts._speakable("这里有个横杠和一个波浪号") == "这里有个和一个"


def test_empty_text_is_empty():
    assert tts._speakable("") == ""
    assert tts._speakable(None) == ""
