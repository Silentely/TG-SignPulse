"""登录审计日志 API 回归：naive UTC 序列化必须带时区标记，避免前端偏差 8 小时。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.models.login_log import LoginLog
from tests.test_api import _login, api_client, db  # noqa: F401 — fixtures re-export


@pytest.fixture
def client(api_client: TestClient) -> Iterator[TestClient]:  # noqa: F811
    yield api_client


class TestLoginAuditTimezone:
    def test_created_at_serialized_with_utc_marker(self, client: TestClient, db):  # noqa: F811
        """存储为 naive UTC 的 created_at 序列化时补 +00:00，前端按本地时区解析不偏移。"""
        db.add(
            LoginLog(
                username="u1",
                ip_address="1.2.3.4",
                user_agent="test",
                detail="login ok",
                success=True,
                created_at=datetime(2026, 8, 12, 4, 30, 0),  # naive UTC
            )
        )
        db.commit()

        token = _login(client)
        resp = client.get("/api/logs/login", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        rows = resp.json()
        # 定位我们插入的记录（登录行为本身也会产生一条审计日志）
        mine = next((r for r in rows if r["username"] == "u1"), None)
        assert mine is not None, "应能找到插入的登录审计记录"
        created_at = mine["created_at"]
        assert isinstance(created_at, str)
        # 必须带 UTC 时区标记（+00:00 或 Z），否则前端 new Date() 按浏览器本地解析
        assert "+00:00" in created_at or created_at.endswith("Z")
        # 值与存储的 UTC 时刻一致
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.astimezone(timezone.utc).hour == 4
