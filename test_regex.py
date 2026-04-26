import re


def _clean_text_for_match(text: str) -> str:
    if not text:
        return ""
    # Remove emojis and zero-width characters (using a broad unicode range for emojis and symbols)
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    text = re.sub(r'[\u2600-\u27bf]', '', text)
    text = re.sub(r'[\u2B50]', '', text)  # ⭐
    # Remove all whitespace and zero width joiners to make fuzzy match extremely forgiving
    text = re.sub(r'[\s\u200b\u200e\u200f\u202a-\u202e]', '', text)
    # Remove all common punctuation
    text = re.sub(r'[!"#$%&\'()*+,-./:;<=>?@\[\]^_`{|}~，。！？；：“”‘’（）【】《》]', '', text)
    return text.strip().lower()

def test_clean_text_removes_emoji_for_chinese_match():
    assert _clean_text_for_match("签到") in _clean_text_for_match("🤖 签到")


def test_clean_text_removes_emoji_for_english_match():
    assert _clean_text_for_match("Check-in") in _clean_text_for_match("✅ Check-in")


def test_clean_text_removes_punctuation():
    assert _clean_text_for_match("Check-in") == "checkin"
