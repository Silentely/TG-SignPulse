"""内置素材数据字典预设。

内置字典只作为可引用的模板展示，用户在前端点击引用后才写入数据目录，
避免首次启动时向用户空间写入大量未使用的字典。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class DataDictPreset:
    """一条内置字典预设。"""

    name: str
    remark: str
    entries: Tuple[str, ...]


BUILTIN_DATA_DICTS: Tuple[DataDictPreset, ...] = (
    DataDictPreset(
        name="greetings",
        remark="日常问候与开场白",
        entries=(
            "你好，在吗？",
            "早上好～",
            "上午好！",
            "中午好",
            "下午好～",
            "晚上好！",
            "大家好，来冒个泡",
            "哈喽，最近怎么样？",
            "在的，有什么可以帮你？",
            "好久不见，一切都好吗？",
            "路过看看，大家好呀",
            "新的一天，来打个招呼",
        ),
    ),
    DataDictPreset(
        name="checkin",
        remark="签到打卡常用文案",
        entries=(
            "签到",
            "打卡",
            "每日签到",
            "签到打卡",
            "来签到啦",
            "今日打卡",
            "准时打卡",
            "签到成功",
            "例行打卡，滴～",
            "今日份签到已完成",
            "打个卡，证明来过",
            "签到一下，继续加油",
        ),
    ),
    DataDictPreset(
        name="blessings",
        remark="祝福与励志短句",
        entries=(
            "天天开心",
            "诸事顺遂",
            "好运常伴",
            "元气满满",
            "一切顺利",
            "平安喜乐",
            "事事如意",
            "继续加油",
            "愿所求皆如愿",
            "今天也要顺顺利利",
            "保持热爱，奔赴山海",
            "慢慢来，一切都会更好",
        ),
    ),
    DataDictPreset(
        name="thanks",
        remark="感谢与致谢回复",
        entries=(
            "谢谢",
            "感谢分享",
            "多谢",
            "辛苦了",
            "收到，谢谢",
            "感谢关照",
            "太感谢了",
            "谢谢大家",
            "感谢解答，很有帮助",
            "感谢提醒，已收到",
        ),
    ),
    DataDictPreset(
        name="chitchat",
        remark="群聊水群与闲聊搭话",
        entries=(
            "哈哈，确实",
            "说得在理",
            "同感同感",
            "冒个泡，继续潜水",
            "来水一下",
            "前排围观",
            "蹲一个后续",
            "有瓜吗？",
            "笑死，太真实了",
            "这么巧，我也在",
            "收到，明白了",
            "学到了，涨知识",
            "这波可以",
            "路过看看",
            "等个大佬解答",
            "刚看到，来晚了",
            "今天群里好热闹",
            "在线摸鱼中",
            "有点意思",
            "先撤了，晚安各位",
        ),
    ),
)

BUILTIN_DATA_DICT_MAP: Dict[str, DataDictPreset] = {
    preset.name: preset for preset in BUILTIN_DATA_DICTS
}
