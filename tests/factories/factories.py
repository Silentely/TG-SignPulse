"""
测试数据工厂

提供工厂类用于动态生成测试数据对象，支持：
自定义参数覆盖、批量生成、序列化为 ORM 模型或字典。
适用于需要大量变体数据的参数化测试。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from tests.utils.helpers import TEST_API_HASH, TEST_API_ID, utc_now_naive


class AccountFactory:
    """
    账号数据工厂

    用法:
        account = AccountFactory.build()
        accounts = AccountFactory.build_batch(5)
        account_dict = AccountFactory.build_dict()
    """

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        cls._counter += 1
        return cls._counter

    @classmethod
    def build_dict(
        cls,
        account_id: Optional[int] = None,
        account_name: Optional[str] = None,
        api_id: str = TEST_API_ID,
        api_hash: str = TEST_API_HASH,
        proxy: Optional[str] = None,
        status: str = "idle",
        last_login_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """生成账号字典"""
        aid = account_id if account_id is not None else cls._next_id()
        name = account_name or f"test_account_{aid}"
        now = utc_now_naive()
        return {
            "id": aid,
            "account_name": name,
            "api_id": api_id,
            "api_hash": api_hash,
            "proxy": proxy,
            "status": status,
            "last_login_at": last_login_at,
            "created_at": now,
            "updated_at": now,
        }

    @classmethod
    def build_batch_dict(cls, count: int = 3, **kwargs) -> List[Dict[str, Any]]:
        """批量生成账号字典"""
        return [cls.build_dict(**kwargs) for _ in range(count)]

    @classmethod
    def build_orm(
        cls,
        session=None,
        **kwargs,
    ):
        """
        生成 ORM Account 对象

        如果传入 session，会自动 add 并 flush。
        需要后端模型可用时才调用。
        """
        from backend.models.account import Account

        data = cls.build_dict(**kwargs)
        account = Account(
            account_name=data["account_name"],
            api_id=data["api_id"],
            api_hash=data["api_hash"],
            proxy=data.get("proxy"),
            status=data["status"],
        )
        if session is not None:
            session.add(account)
            session.flush()
        return account


class TaskFactory:
    """
    任务数据工厂

    用法:
        task = TaskFactory.build()
        tasks = TaskFactory.build_batch(3, account_id=1)
    """

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        cls._counter += 1
        return cls._counter

    @classmethod
    def build_dict(
        cls,
        task_id: Optional[int] = None,
        name: Optional[str] = None,
        cron: str = "0 6 * * *",
        enabled: bool = True,
        account_id: int = 1,
        last_run_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """生成任务字典"""
        tid = task_id if task_id is not None else cls._next_id()
        task_name = name or f"test_task_{tid}"
        now = utc_now_naive()
        return {
            "id": tid,
            "name": task_name,
            "cron": cron,
            "enabled": enabled,
            "account_id": account_id,
            "last_run_at": last_run_at,
            "created_at": now,
            "updated_at": now,
        }

    @classmethod
    def build_batch_dict(cls, count: int = 3, **kwargs) -> List[Dict[str, Any]]:
        """批量生成任务字典"""
        return [cls.build_dict(**kwargs) for _ in range(count)]

    @classmethod
    def build_orm(cls, session=None, **kwargs):
        """
        生成 ORM Task 对象

        如果传入 session，会自动 add 并 flush。
        """
        from backend.models.task import Task

        data = cls.build_dict(**kwargs)
        task = Task(
            name=data["name"],
            cron=data["cron"],
            enabled=data["enabled"],
            account_id=data["account_id"],
        )
        if session is not None:
            session.add(task)
            session.flush()
        return task


class SignConfigFactory:
    """
    签到配置工厂

    生成 SignConfigV3 兼容的字典数据，可直接用于 JSON 文件或模型加载。
    """

    _counter = 0

    @classmethod
    def _next_chat_id(cls) -> int:
        cls._counter += 1
        return -1001000000000 - cls._counter

    @classmethod
    def build_dict(
        cls,
        chat_ids: Optional[List[int]] = None,
        sign_at: str = "0 6 * * *",
        send_text: str = "签到",
        random_seconds: int = 0,
        sign_interval: int = 1,
        actions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        生成 SignConfigV3 字典

        Args:
            chat_ids: 聊天 ID 列表，为 None 时自动生成
            sign_at: 签到时间（crontab 表达式）
            send_text: 发送的文本（当 actions 为 None 时使用）
            random_seconds: 随机延迟秒数
            sign_interval: 多聊天间的间隔秒数
            actions: 自定义动作列表，为 None 时生成简单文本动作
        """
        if chat_ids is None:
            chat_ids = [cls._next_chat_id()]

        if actions is None:
            actions = [{"action": 1, "text": send_text}]

        return {
            "version": 3,
            "chats": [
                {
                    "chat_id": cid,
                    "actions": list(actions),
                }
                for cid in chat_ids
            ],
            "sign_at": sign_at,
            "random_seconds": random_seconds,
            "sign_interval": sign_interval,
        }

    @classmethod
    def build_dict_with_keyboard(
        cls,
        chat_id: Optional[int] = None,
        sign_text: str = "签到",
        button_text: str = "确认",
        sign_at: str = "0 7 * * *",
    ) -> Dict[str, Any]:
        """生成带键盘点击动作的配置"""
        cid = chat_id or cls._next_chat_id()
        return {
            "version": 3,
            "chats": [
                {
                    "chat_id": cid,
                    "actions": [
                        {"action": 1, "text": sign_text},
                        {"action": 3, "text": button_text},
                    ],
                    "action_interval": 2,
                }
            ],
            "sign_at": sign_at,
        }

    @classmethod
    def build_dict_with_ai(
        cls,
        chat_id: Optional[int] = None,
        sign_text: str = "签到",
        sign_at: str = "0 6 * * *",
    ) -> Dict[str, Any]:
        """生成带 AI 动作的配置（图片选择 + 计算题）"""
        cid = chat_id or cls._next_chat_id()
        return {
            "version": 3,
            "chats": [
                {
                    "chat_id": cid,
                    "actions": [
                        {"action": 1, "text": sign_text},
                        {"action": 4},
                        {"action": 5},
                    ],
                }
            ],
            "sign_at": sign_at,
        }


class UserFactory:
    """
    用户数据工厂

    用于生成后端 User 模型（认证用户）的测试数据。
    """

    _counter = 0

    @classmethod
    def _next_id(cls) -> int:
        cls._counter += 1
        return cls._counter

    @classmethod
    def build_dict(
        cls,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        password_hash: str = "$2b$12$test_hash_value_12345678",
        totp_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成用户字典"""
        uid = user_id if user_id is not None else cls._next_id()
        uname = username or f"testuser_{uid}"
        return {
            "id": uid,
            "username": uname,
            "password_hash": password_hash,
            "totp_secret": totp_secret,
            "created_at": utc_now_naive(),
        }

    @classmethod
    def build_orm(cls, session=None, **kwargs):
        """生成 ORM User 对象"""
        from backend.models.user import User

        data = cls.build_dict(**kwargs)
        user = User(
            username=data["username"],
            password_hash=data["password_hash"],
            totp_secret=data.get("totp_secret"),
        )
        if session is not None:
            session.add(user)
            session.flush()
        return user
