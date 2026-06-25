"""
任务测试数据 Fixtures

提供 Task 模型及 SignConfigV3 的预构建测试数据，
涵盖简单签到、多动作签到、带 AI 的签到等场景。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from tests.utils.helpers import utc_now_naive


# ---------- 纯字典任务数据 ----------

def make_task_data(
    task_id: int = 1,
    name: str = "daily_sign",
    cron: str = "0 6 * * *",
    enabled: bool = True,
    account_id: int = 1,
    last_run_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """生成单个任务字典数据"""
    now = utc_now_naive()
    return {
        "id": task_id,
        "name": name,
        "cron": cron,
        "enabled": enabled,
        "account_id": account_id,
        "last_run_at": last_run_at,
        "created_at": now,
        "updated_at": now,
    }


TASK_BASIC = make_task_data()
TASK_DISABLED = make_task_data(task_id=2, name="disabled_sign", enabled=False)
TASK_NIGHTLY = make_task_data(task_id=3, name="nightly_sign", cron="0 23 * * *")

TASK_LIST = [TASK_BASIC, TASK_DISABLED, TASK_NIGHTLY]


# ---------- SignConfigV3 字典数据（用于配置文件测试） ----------

SIGN_CONFIG_V3_BASIC = {
    "version": 3,
    "chats": [
        {
            "chat_id": -1001234567890,
            "name": "测试签到群",
            "actions": [
                {"action": 1, "text": "签到"},
            ],
            "action_interval": 1,
        }
    ],
    "sign_at": "0 6 * * *",
    "random_seconds": 0,
    "sign_interval": 1,
}

SIGN_CONFIG_V3_MULTI_CHAT = {
    "version": 3,
    "chats": [
        {
            "chat_id": -1001234567890,
            "name": "签到群1",
            "actions": [
                {"action": 1, "text": "签到"},
            ],
        },
        {
            "chat_id": -1009876543210,
            "name": "签到群2",
            "actions": [
                {"action": 1, "text": "打卡"},
            ],
        },
    ],
    "sign_at": "30 8 * * *",
    "random_seconds": 60,
    "sign_interval": 2,
}

SIGN_CONFIG_V3_DICE = {
    "version": 3,
    "chats": [
        {
            "chat_id": -1001234567890,
            "name": "骰子签到群",
            "actions": [
                {"action": 2, "dice": "🎲"},
            ],
        }
    ],
    "sign_at": "0 9 * * *",
}

SIGN_CONFIG_V3_MULTI_ACTION = {
    "version": 3,
    "chats": [
        {
            "chat_id": -1001234567890,
            "name": "多动作签到群",
            "actions": [
                {"action": 1, "text": "签到"},
                {"action": 3, "text": "确认"},
            ],
            "action_interval": 2,
        }
    ],
    "sign_at": "0 7 * * *",
}

SIGN_CONFIG_V3_WITH_AI = {
    "version": 3,
    "chats": [
        {
            "chat_id": -1001234567890,
            "name": "AI签到群",
            "actions": [
                {"action": 1, "text": "签到"},
                {"action": 4},
                {"action": 5},
            ],
        }
    ],
    "sign_at": "0 6 * * *",
}

SIGN_CONFIG_V3_WITH_KEYWORD = {
    "version": 3,
    "chats": [
        {
            "chat_id": -1001234567890,
            "name": "关键词监听群",
            "actions": [
                {
                    "action": 8,
                    "keywords": ["紧急", "通知"],
                    "match_mode": "contains",
                    "push_channel": "telegram",
                },
            ],
        }
    ],
    "sign_at": "0 8 * * *",
}


def make_sign_config_v3_dict(
    chat_ids: Optional[List[int]] = None,
    sign_at: str = "0 6 * * *",
    send_text: str = "签到",
) -> Dict[str, Any]:
    """快速生成 SignConfigV3 字典"""
    if chat_ids is None:
        chat_ids = [-1001234567890]
    return {
        "version": 3,
        "chats": [
            {
                "chat_id": cid,
                "actions": [{"action": 1, "text": send_text}],
            }
            for cid in chat_ids
        ],
        "sign_at": sign_at,
    }


def make_task_data_list(count: int = 3, account_id: int = 1) -> List[Dict[str, Any]]:
    """生成指定数量的任务字典列表"""
    return [
        make_task_data(
            task_id=i + 1,
            name=f"task_{i + 1}",
            cron=f"{i} 6 * * *",
            enabled=i % 2 == 0,
            account_id=account_id,
        )
        for i in range(count)
    ]
