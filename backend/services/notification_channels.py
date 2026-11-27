"""任务级通知渠道注册表。

渠道以 id 为标识，Webhook 地址沿用现有的全局设置字段
（``wecom_webhook_url`` / ``feishu_webhook_url`` / ``dingtalk_webhook_url`` /
``discord_webhook_url``），因此无需新增存储或额外的密钥面。任务在
``config.json`` 里用 ``notify_channel_ids`` 选择渠道；id 不存在或未配置
地址时由分发层记日志并跳过该渠道。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class NotifyChannel:
    id: str
    label: str
    settings_key: str


# 顺序即默认分发顺序（保持与原有矩阵通知一致）
NOTIFY_CHANNELS: Dict[str, NotifyChannel] = {
    "wecom": NotifyChannel("wecom", "企业微信", "wecom_webhook_url"),
    "feishu": NotifyChannel("feishu", "飞书", "feishu_webhook_url"),
    "dingtalk": NotifyChannel("dingtalk", "钉钉", "dingtalk_webhook_url"),
    "discord": NotifyChannel("discord", "Discord", "discord_webhook_url"),
}


def normalize_channel_ids(value: Any) -> List[str]:
    """清洗渠道 id 列表：去空白、转小写、去重；非列表输入返回空列表。"""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    result: List[str] = []
    for raw in value:
        channel_id = str(raw or "").strip().lower()
        if channel_id and channel_id not in result:
            result.append(channel_id)
    return result


def resolve_channel_webhook(settings: Dict[str, Any], channel_id: str) -> Optional[str]:
    """返回渠道对应的 Webhook 地址；渠道不存在或未配置时返回 None。"""
    channel = NOTIFY_CHANNELS.get(channel_id)
    if channel is None:
        return None
    url = str(settings.get(channel.settings_key) or "").strip()
    return url or None
