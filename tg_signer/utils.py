import os
import re
import sys
from typing import Dict, Literal, Optional

from typing_extensions import TypeAlias

# FloodWait 文本形态引导词：flood[_wait] 后允许夹一段非数字说明（错误码、前缀文案），
# 或直接是 "wait N"；单位可省略（"FloodWait: 420"），但引导词必须紧邻秒数，
# 避免把 "timeout after 300 seconds of waiting" 这类瞬时报错误判为限流冷却。
_FLOOD_WAIT_TEXT_RE = re.compile(
    r"(?:\bflood\w*[^\d]{0,24}|\bwait\b)\s*(\d+)\s*(?:seconds?|secs?|s|秒)?",
    re.IGNORECASE,
)

NumberingLangT: TypeAlias = Literal[
    "arabic",
    "chinese_simple",
    "chinese_traditional",
    "roman",
    "roman_lower",
    "letter_upper",
    "letter_lower",
    "greek_upper",
    "greek_lower",
    "circled",
    "parenthesized",
    "japanese_kanji",
    "japanese_kana",
    "arabic_indic",
    "devanagari",
    "hebrew",
    "tian_gan",
    "di_zhi",
    "emoji",
]

numbering_systems: Dict[int, Dict[NumberingLangT, str]] = {
    # 基础数字
    1: {
        "arabic": "1",
        "chinese_simple": "一",
        "chinese_traditional": "壹",
        "roman": "I",
        "roman_lower": "i",
        "letter_upper": "A",
        "letter_lower": "a",
        "greek_upper": "Α",  # Alpha
        "greek_lower": "α",
        "circled": "①",
        "parenthesized": "⑴",
        "japanese_kanji": "一",
        "japanese_kana": "いち",
        "arabic_indic": "١",  # Arabic numeral 1
        "devanagari": "१",  # Hindi/Sanskrit
        "hebrew": "א",  # Aleph
        "tian_gan": "甲",  # 天干
        "di_zhi": "子",  # 地支
        "emoji": "1️⃣",
    },
    2: {
        "arabic": "2",
        "chinese_simple": "二",
        "chinese_traditional": "貳",
        "roman": "II",
        "roman_lower": "ii",
        "letter_upper": "B",
        "letter_lower": "b",
        "greek_upper": "Β",  # Beta
        "greek_lower": "β",
        "circled": "②",
        "parenthesized": "⑵",
        "japanese_kanji": "二",
        "japanese_kana": "に",
        "arabic_indic": "٢",
        "devanagari": "२",
        "hebrew": "ב",  # Bet
        "tian_gan": "乙",
        "di_zhi": "丑",
        "emoji": "2️⃣",
    },
    3: {
        "arabic": "3",
        "chinese_simple": "三",
        "chinese_traditional": "叁",
        "roman": "III",
        "roman_lower": "iii",
        "letter_upper": "C",
        "letter_lower": "c",
        "greek_upper": "Γ",  # Gamma
        "greek_lower": "γ",
        "circled": "③",
        "parenthesized": "⑶",
        "japanese_kanji": "三",
        "japanese_kana": "さん",
        "arabic_indic": "٣",
        "devanagari": "३",
        "hebrew": "ג",  # Gimel
        "tian_gan": "丙",
        "di_zhi": "寅",
        "emoji": "3️⃣",
    },
    4: {
        "arabic": "4",
        "chinese_simple": "四",
        "chinese_traditional": "肆",
        "roman": "IV",
        "roman_lower": "iv",
        "letter_upper": "D",
        "letter_lower": "d",
        "greek_upper": "Δ",  # Delta
        "greek_lower": "δ",
        "circled": "④",
        "parenthesized": "⑷",
        "japanese_kanji": "四",
        "japanese_kana": "し／よん",
        "arabic_indic": "٤",
        "devanagari": "४",
        "hebrew": "ד",  # Dalet
        "tian_gan": "丁",
        "di_zhi": "卯",
        "emoji": "4️⃣",
    },
    5: {
        "arabic": "5",
        "chinese_simple": "五",
        "chinese_traditional": "伍",
        "roman": "V",
        "roman_lower": "v",
        "letter_upper": "E",
        "letter_lower": "e",
        "greek_upper": "Ε",  # Epsilon
        "greek_lower": "ε",
        "circled": "⑤",
        "parenthesized": "⑸",
        "japanese_kanji": "五",
        "japanese_kana": "ご",
        "arabic_indic": "٥",
        "devanagari": "५",
        "hebrew": "ה",  # He
        "tian_gan": "戊",
        "di_zhi": "辰",
        "emoji": "5️⃣",
    },
    6: {
        "arabic": "6",
        "chinese_simple": "六",
        "chinese_traditional": "陸",
        "roman": "VI",
        "roman_lower": "vi",
        "letter_upper": "F",
        "letter_lower": "f",
        "greek_upper": "Ζ",  # Zeta
        "greek_lower": "ζ",
        "circled": "⑥",
        "parenthesized": "⑹",
        "japanese_kanji": "六",
        "japanese_kana": "ろく",
        "arabic_indic": "٦",
        "devanagari": "६",
        "hebrew": "ו",  # Vav
        "tian_gan": "己",
        "di_zhi": "巳",
        "emoji": "6️⃣",
    },
    7: {
        "arabic": "7",
        "chinese_simple": "七",
        "chinese_traditional": "柒",
        "roman": "VII",
        "roman_lower": "vii",
        "letter_upper": "G",
        "letter_lower": "g",
        "greek_upper": "Η",  # Eta
        "greek_lower": "η",
        "circled": "⑦",
        "parenthesized": "⑺",
        "japanese_kanji": "七",
        "japanese_kana": "しち／なな",
        "arabic_indic": "٧",
        "devanagari": "७",
        "hebrew": "ז",  # Zayin
        "tian_gan": "庚",
        "di_zhi": "午",
        "emoji": "7️⃣",
    },
    8: {
        "arabic": "8",
        "chinese_simple": "八",
        "chinese_traditional": "捌",
        "roman": "VIII",
        "roman_lower": "viii",
        "letter_upper": "H",
        "letter_lower": "h",
        "greek_upper": "Θ",  # Theta
        "greek_lower": "θ",
        "circled": "⑧",
        "parenthesized": "⑻",
        "japanese_kanji": "八",
        "japanese_kana": "はち",
        "arabic_indic": "٨",
        "devanagari": "८",
        "hebrew": "ח",  # Het
        "tian_gan": "辛",
        "di_zhi": "未",
        "emoji": "8️⃣",
    },
    9: {
        "arabic": "9",
        "chinese_simple": "九",
        "chinese_traditional": "玖",
        "roman": "IX",
        "roman_lower": "ix",
        "letter_upper": "I",
        "letter_lower": "i",
        "greek_upper": "Ι",  # Iota
        "greek_lower": "ι",
        "circled": "⑨",
        "parenthesized": "⑼",
        "japanese_kanji": "九",
        "japanese_kana": "きゅう／く",
        "arabic_indic": "٩",
        "devanagari": "९",
        "hebrew": "ט",  # Tet
        "tian_gan": "壬",
        "di_zhi": "申",
        "emoji": "9️⃣",
    },
    10: {
        "arabic": "10",
        "chinese_simple": "十",
        "chinese_traditional": "拾",
        "roman": "X",
        "roman_lower": "x",
        "letter_upper": "J",
        "letter_lower": "j",
        "greek_upper": "Κ",  # Kappa
        "greek_lower": "κ",
        "circled": "⑩",
        "parenthesized": "⑽",
        "japanese_kanji": "十",
        "japanese_kana": "じゅう",
        "arabic_indic": "١٠",
        "devanagari": "१०",
        "hebrew": "י",  # Yod
        "tian_gan": "癸",
        "di_zhi": "酉",
        "emoji": "🔟",  # 10的emoji是特殊符号
    },
}


def numbering(num: int, lang: NumberingLangT):
    try:
        return numbering_systems[num][lang]
    except KeyError:
        return str(num)


class UserInput:
    def __init__(self, index: int = 1, numbering_lang: NumberingLangT = "arabic"):
        self.index = index
        self.numbering_lang = numbering_lang

    def incr(self, n: int = 1):
        self.index += n

    def decr(self, n: int = 1):
        self.index -= n

    @property
    def index_str(self):
        return f"{numbering(self.index, self.numbering_lang)}. "

    def __call__(self, prompt: str = None):
        r = input(f"{self.index_str}{prompt}")
        self.incr(1)
        return r


def print_to_user(*args, sep=" ", end="\n", flush=False, **kwargs):
    text = sep.join(str(arg) for arg in args) + end
    stream = kwargs.get("file") or sys.stdout
    try:
        stream.write(text)
    except UnicodeEncodeError:
        # 流已表明无法直接写入当前文本；编码未知时按 ascii 兜底，
        # 保证 backslashreplace 能产出可写入的安全文本
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(
            encoding,
            errors="ignore",
        )
        stream.write(safe_text)
    if flush:
        try:
            stream.flush()
        except Exception:
            # flush 失败仅为输出未及时落盘，不影响调用方流程
            pass


def clamp(value, low, high) -> float:
    """把数值钳制到 [low, high] 区间（等价 max(low, min(value, high))）。

    统一后端散落的 `max(min(...))` 写法；low > high 时返回 high，
    与 min/max 组合语义保持一致。
    """
    return max(low, min(value, high))


def read_positive_int_env(name: str, default: int, minimum: int = 1) -> int:
    """读取正整数环境变量；缺失或非法时回退默认值，结果不低于 minimum。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


def read_positive_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    """读取正浮点环境变量；缺失或非法时回退默认值，结果不低于 minimum。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default


def extract_flood_wait_seconds(exc: BaseException) -> Optional[int]:
    """从异常中解析 FloodWait 等待秒数；无法判定时返回 None。

    必须先做类型判定再回退文本匹配：`str(FloodWait(300))` 是
    "Telegram says: [420 FLOOD_WAIT_X] - Please wait 300 seconds ..."，
    仅靠关键词匹配既可能漏判实例，也可能把 "timeout after 300 seconds of waiting"
    这类瞬时报错误判成限流冷却，故文本分支要求出现 flood/wait 引导词。

    秒数为 0 是有效等待（立即重试），因此用 None 而非 0 表示"非限流错误"。
    """
    value = getattr(exc, "value", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return max(value, 0)

    # 类名判定覆盖 Kurigram/Pyrogram 的 FloodWait 及其子类，避免模块级引入重依赖
    if any(klass.__name__ == "FloodWait" for klass in type(exc).__mro__):
        seconds = getattr(exc, "value", None)
        if isinstance(seconds, int) and not isinstance(seconds, bool):
            return max(seconds, 0)
        return None

    match = _FLOOD_WAIT_TEXT_RE.search(str(exc))
    if match:
        return int(match.group(1))
    return None


def get_display_width(text: str) -> int:
    """计算文本在终端中的显示宽度（中文字符占 2 个字符位）。"""
    width = 0
    for char in text:
        width += 2 if ord(char) > 127 else 1
    return width


def pad_text_to_width(text: str, target_width: int, align: str = "left") -> str:
    """将文本填充到指定宽度。"""
    padding_needed = target_width - get_display_width(text)
    if padding_needed <= 0:
        return text
    if align == "right":
        return " " * padding_needed + text
    if align == "center":
        left_padding = padding_needed // 2
        return " " * left_padding + text + " " * (padding_needed - left_padding)
    return text + " " * padding_needed


def format_sign_chat_box(chat) -> str:
    """渲染签到对象盒式终端展示（供 __str__ 使用，展示细节不进入配置模型）。"""
    from tg_signer.config import (
        ClickKeyboardByTextAction,
        SendDiceAction,
        SendTextAction,
    )

    content_width = 48
    top_border = "╔" + "═" * content_width + "╗"
    bottom_border = "╚" + "═" * content_width + "╝"
    separator = "╟" + "─" * content_width + "╢"

    title = f"║ {pad_text_to_width(f'Chat ID: {chat.chat_id}', content_width - 2)} ║"
    name_value = chat.name or "-"
    name_info = f"║ {pad_text_to_width(f'Name: {name_value}', content_width - 2)} ║"
    delete_value = chat.delete_after or "-"
    delete_info = (
        f"║ {pad_text_to_width(f'Delete After: {delete_value}', content_width - 2)} ║"
    )
    actions_header = f"║ {pad_text_to_width('Actions Flow:', content_width - 2)} ║"

    actions_lines = []
    for i, action in enumerate(chat.actions, 1):
        action_type = action.action.desc
        details = ""
        if isinstance(action, SendTextAction):
            text_preview = (
                action.text[:15] + "..." if len(action.text) > 15 else action.text
            )
            details = f"Text: {text_preview}"
        elif isinstance(action, SendDiceAction):
            details = f"Dice: {action.dice}"
        elif isinstance(action, ClickKeyboardByTextAction):
            text_preview = (
                action.text[:15] + "..." if len(action.text) > 15 else action.text
            )
            details = f"Click: {text_preview}"
        if details:
            action_text = f"{i}. [{action_type}] {details}"
        else:
            action_text = f"{i}. [{action_type}]"
        actions_lines.append(
            f"║ {pad_text_to_width(action_text, content_width - 2)} ║"
        )

    result = [
        top_border,
        title,
        name_info,
        delete_info,
        separator,
        actions_header,
        *actions_lines,
        bottom_border,
    ]
    return "\n".join(result)


def validate_public_http_url(url: str) -> "tuple[str, str]":
    """校验 HTTP(S) URL 仅指向全局可路由的公网地址，用于 SSRF 防护。

    白名单式校验：scheme 限定 http/https，解析出的所有候选地址（含 IPv4-mapped、
    6to4、Teredo 内嵌 IPv4）必须全部为 is_global 的公网地址。解析结果以钉扎 IP
    形式返回，调用方应以钉扎 IP 建立连接，避免二次 DNS 解析造成 rebinding 绕过。

    返回 (pinned_ip, hostname)；URL 不合法、主机不可解析或指向内网时抛出 ValueError。
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("URL 必须以 http:// 或 https:// 开头")

    parsed_url = urlparse(url)
    hostname = parsed_url.hostname or ""
    if not hostname:
        raise ValueError("无效的主机名")

    def _is_forbidden_target(ip_obj: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> bool:
        embedded: list[ipaddress.IPv4Address] = []
        if ip_obj.version == 6:
            # IPv4-mapped/6to4/Teredo 内嵌的 IPv4 地址需一并判定，防止 ::ffff:10.0.0.1 之类字面量绕过
            if ip_obj.ipv4_mapped:
                embedded.append(ip_obj.ipv4_mapped)
            if ip_obj.sixtofour:
                embedded.append(ip_obj.sixtofour)
            if ip_obj.teredo:
                embedded.extend([ip_obj.teredo.server, ip_obj.teredo.client])
        if not ip_obj.is_global:
            return True
        return any(not addr.is_global for addr in embedded)

    # 解析候选地址并逐一校验；字面量 IP 直接采用，主机名则走 DNS 解析
    try:
        candidates = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, UnicodeError):
            raise ValueError(f"无法解析主机: {hostname}")
        candidates = []
        for addr in addr_info:
            try:
                candidates.append(ipaddress.ip_address(addr[4][0]))
            except ValueError:
                continue
    if not candidates:
        raise ValueError(f"无法解析主机: {hostname}")
    for ip_obj in candidates:
        if _is_forbidden_target(ip_obj):
            raise ValueError("安全限制：禁止请求私有或内网地址")

    pinned_ip_obj = candidates[0]
    if pinned_ip_obj.version == 6 and pinned_ip_obj.ipv4_mapped:
        pinned_ip_obj = pinned_ip_obj.ipv4_mapped
    return str(pinned_ip_obj), hostname
