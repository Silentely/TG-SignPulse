"""
账号测试数据 Fixtures

提供 Account 模型的预构建测试数据，涵盖常见场景：
正常账号、带代理的账号、不同状态的账号等。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from tests.utils.helpers import utc_now_naive


# ---------- 纯字典数据（不依赖 ORM 模型，可在无 DB 时使用） ----------

def make_account_data(
    account_id: int = 1,
    account_name: str = "test_account",
    api_id: str = "12345",
    api_hash: str = "test-api-hash-abcdef123456",
    proxy: str | None = None,
    status: str = "idle",
    last_login_at: datetime | None = None,
) -> Dict[str, Any]:
    """生成单个账号字典数据"""
    now = utc_now_naive()
    return {
        "id": account_id,
        "account_name": account_name,
        "api_id": api_id,
        "api_hash": api_hash,
        "proxy": proxy,
        "status": status,
        "last_login_at": last_login_at,
        "created_at": now,
        "updated_at": now,
    }


# ---------- 预置场景数据 ----------

ACCOUNT_BASIC = make_account_data()

ACCOUNT_WITH_PROXY = make_account_data(
    account_id=2,
    account_name="proxy_account",
    proxy=json.dumps({
        "scheme": "socks5",
        "hostname": "127.0.0.1",
        "port": 1080,
    }),
)

ACCOUNT_ACTIVE = make_account_data(
    account_id=3,
    account_name="active_account",
    status="active",
    last_login_at=utc_now_naive(),
)

ACCOUNT_ERROR = make_account_data(
    account_id=4,
    account_name="error_account",
    status="error",
)

# 多账号列表，用于批量测试
ACCOUNT_LIST = [
    ACCOUNT_BASIC,
    ACCOUNT_WITH_PROXY,
    ACCOUNT_ACTIVE,
    ACCOUNT_ERROR,
]


def make_account_dict_list(count: int = 3) -> List[Dict[str, Any]]:
    """生成指定数量的账号字典列表"""
    return [
        make_account_data(
            account_id=i + 1,
            account_name=f"account_{i + 1}",
            status=["idle", "active", "error"][i % 3],
        )
        for i in range(count)
    ]
