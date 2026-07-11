"""
增强版 conftest.py

提供全测试套件共享的 fixtures，包括：
- 环境隔离（临时目录、环境变量）
- 数据库测试（内存 SQLite、会话管理）
- FastAPI 测试客户端
- Telegram 客户端 Mock
- AI 服务 Mock
- 测试数据工厂集成
"""

from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Dict

import pytest


@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """确保测试前后都有可用的事件循环。
    IsolatedAsyncioTestCase 会在 teardown 时关闭循环，
    导致后续同步测试中 Pyrogram BaseClient.__init__ 获取不到循环而失败。
    """
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fixtures.accounts import (
    make_account_data,
    make_account_dict_list,
)
from tests.fixtures.messages import (
    make_inline_keyboard_message,
    make_photo_message,
    make_sign_success_message,
    make_text_message,
)
from tests.fixtures.tasks import (
    SIGN_CONFIG_V3_BASIC,
    SIGN_CONFIG_V3_MULTI_ACTION,
    SIGN_CONFIG_V3_WITH_AI,
    make_task_data,
    make_task_data_list,
)
from tests.mocks.ai_service import MockAITools, MockOpenAIClient
from tests.mocks.database import MockDBSession
from tests.mocks.telegram import (
    MockChat,
    MockDialog,
    MockMessage,
    MockTelegramClient,
)
from tests.utils.helpers import (
    create_temp_config_file,
)

# ============================================================================
# 环境隔离 Fixtures
# ============================================================================


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """创建临时数据目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, temp_data_dir: Path) -> Iterator[Path]:
    """
    隔离的环境变量

    设置所有必要的环境变量指向临时目录，确保测试不读写真实配置。
    """
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("APP_DB_PATH", str(temp_data_dir / "test.sqlite"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "test-api-hash")
    yield temp_data_dir


@pytest.fixture(autouse=True)
def no_external_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    全局自动 fixture：阻止测试意外连接真实 Telegram API

    设置环境变量强制使用内存模式和超短超时。
    """
    monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "1")
    monkeypatch.setenv("SIGN_TASK_EXECUTION_TIMEOUT", "5")
    monkeypatch.setenv("AI_REQUEST_TIMEOUT", "5")
    # 测试中拉长内存检查间隔，避免干扰 lifespan 相关用例
    monkeypatch.setenv("MEMORY_CHECK_INTERVAL_S", "3600")
    monkeypatch.setenv("MEMORY_THRESHOLD_MB", "8192")
    os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


@pytest.fixture(autouse=True)
def ensure_event_loop() -> Iterator[None]:
    """
    保证同步测试始终有可用的事件循环。

    pytest-asyncio 在 async 用例结束后会关闭 loop，随后同步创建
    Pyrogram Client / asyncio.Lock 会触发
    “There is no current event loop in thread 'MainThread'”。
    """
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_closed():
            raise RuntimeError("event loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield


# ============================================================================
# 数据库 Fixtures
# ============================================================================


@pytest.fixture
def memory_session_local(isolated_env: Path):
    """
    内存 SQLite 数据库会话工厂

    创建内存数据库，初始化所有表结构，测试结束后自动清理。
    用于后端服务层和 API 层的集成测试。
    """
    from backend.core import config as config_module
    from backend.core import database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None

    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
    )
    database_module.Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    database_module._engine = engine
    database_module._SessionLocal = testing_session_local
    try:
        yield testing_session_local
    finally:
        database_module.Base.metadata.drop_all(bind=engine)
        engine.dispose()
        database_module._engine = None
        database_module._SessionLocal = None
        config_module.get_settings.cache_clear()


@pytest.fixture
def db_session(memory_session_local):
    """
    单个数据库会话实例

    自动在测试结束后关闭，适用于需要直接操作数据库的测试。
    """
    session = memory_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def mock_db_session() -> MockDBSession:
    """
    模拟数据库会话（不依赖真实数据库）

    适用于纯单元测试，不需要真实的数据库交互。
    """
    return MockDBSession()


# ============================================================================
# FastAPI 测试客户端 Fixtures
# ============================================================================


@pytest.fixture
def client(isolated_env: Path, memory_session_local) -> Iterator[TestClient]:
    """
    FastAPI 测试客户端

    使用内存数据库覆盖后端依赖注入，适用于 API 端点测试。
    """
    from backend.core import database as database_module

    main = importlib.import_module("backend.main")

    def override_get_db():
        db = memory_session_local()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[database_module.get_db] = override_get_db
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.clear()


# ============================================================================
# Telegram Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_telegram_client() -> MockTelegramClient:
    """
    模拟 Telegram 客户端

    预配置默认对话和消息历史，适用于签到和监控相关测试。
    """
    client = MockTelegramClient()
    client.configure_dialogs([
        MockDialog(MockChat(chat_id=-1001234567890, title="测试签到群")),
        MockDialog(MockChat(chat_id=-1009876543210, title="测试群2")),
    ])
    return client


@pytest.fixture
def mock_message() -> MockMessage:
    """基础文本消息 fixture"""
    return make_text_message()


@pytest.fixture
def mock_sign_success_message() -> MockMessage:
    """签到成功消息 fixture"""
    return make_sign_success_message()


@pytest.fixture
def mock_inline_keyboard_message() -> MockMessage:
    """带 InlineKeyboard 的消息 fixture"""
    return make_inline_keyboard_message()


@pytest.fixture
def mock_photo_message() -> MockMessage:
    """图片消息 fixture"""
    return make_photo_message()


# ============================================================================
# AI 服务 Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_ai_tools() -> MockAITools:
    """
    模拟 AI 工具实例

    默认配置返回成功结果，可在测试中通过 configure_* 方法调整。
    """
    return MockAITools()


@pytest.fixture
def mock_openai_client() -> MockOpenAIClient:
    """模拟 OpenAI 客户端"""
    return MockOpenAIClient()


# ============================================================================
# 测试数据 Fixtures
# ============================================================================


@pytest.fixture
def sample_account_data() -> Dict[str, Any]:
    """示例账号数据字典"""
    return make_account_data()


@pytest.fixture
def sample_account_list() -> list:
    """示例账号列表"""
    return make_account_dict_list(3)


@pytest.fixture
def sample_task_data() -> Dict[str, Any]:
    """示例任务数据字典"""
    return make_task_data()


@pytest.fixture
def sample_task_list() -> list:
    """示例任务列表"""
    return make_task_data_list(3)


@pytest.fixture
def sample_sign_config_v3() -> Dict[str, Any]:
    """示例 SignConfigV3 字典"""
    return SIGN_CONFIG_V3_BASIC.copy()


@pytest.fixture
def sample_sign_config_multi_action() -> Dict[str, Any]:
    """多动作 SignConfigV3 字典"""
    return SIGN_CONFIG_V3_MULTI_ACTION.copy()


@pytest.fixture
def sample_sign_config_with_ai() -> Dict[str, Any]:
    """带 AI 动作的 SignConfigV3 字典"""
    return SIGN_CONFIG_V3_WITH_AI.copy()


# ============================================================================
# 临时配置文件 Fixtures
# ============================================================================


@pytest.fixture
def temp_sign_config_file(tmp_path: Path, sample_sign_config_v3: Dict[str, Any]) -> Path:
    """创建临时签到配置文件"""
    config_dir = tmp_path / "signs" / "test_account" / "test_task"
    config_dir.mkdir(parents=True, exist_ok=True)
    return create_temp_config_file(sample_sign_config_v3, config_dir, "config.json")


@pytest.fixture
def temp_openai_config_file(tmp_path: Path) -> Path:
    """创建临时 OpenAI 配置文件"""
    config = {
        "api_key": "test-openai-key",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    }
    return create_temp_config_file(config, tmp_path, ".openai_config.json")
