"""Tests for plugins API endpoints: GET /api/plugins, POST /api/plugins/reload, POST /api/plugins/{name}/test."""

from __future__ import annotations

from pathlib import Path
from tests.test_api import _auth, _login
from tg_signer.core.plugins import PluginContext, PluginRegistry, is_builtin_plugin_path

pytest_plugins = ("tests.test_api",)


# Module-level registration so that worker subprocess can resolve plugins when loading this file
def _register_sandbox_worker_fixtures():
    PluginRegistry._plugins.pop("test_sync_hang_sandbox", None)

    @PluginRegistry.register(
        name="test_sync_hang_sandbox",
        mode="reactive",
        description="沙箱同步死循环挂起测试插件",
    )
    def hang_sandbox_handler(ctx: PluginContext):
        import time

        while True:
            time.sleep(0.05)

    PluginRegistry._plugins.pop("test_crashing_plugin", None)

    @PluginRegistry.register(
        name="test_crashing_plugin",
        mode="reactive",
    )
    def crash_handler(ctx: PluginContext):
        raise RuntimeError("模拟插件执行崩溃")


_register_sandbox_worker_fixtures()


def test_list_plugins_requires_auth(api_client):
    """未认证访问 /api/plugins 应返回 401"""
    resp = api_client.get("/api/plugins")
    assert resp.status_code == 401


def test_list_and_reload_plugins(api_client):
    """测试已认证用户获取插件列表与重新加载插件"""
    token = _login(api_client)
    headers = _auth(token)

    # 注册一个临时插件
    @PluginRegistry.register(
        name="test_api_plugin",
        mode="active",
        description="用于测试 API 的插件",
        params_schema=[{"name": "foo", "label": "Foo", "type": "string"}],
    )
    def dummy_handler(ctx: PluginContext):
        return True

    # 测试 GET /api/plugins
    resp = api_client.get("/api/plugins", headers=headers)
    assert resp.status_code == 200
    plugins = resp.json()
    assert isinstance(plugins, list)
    names = [p["name"] for p in plugins]
    assert "test_api_plugin" in names

    target = next(p for p in plugins if p["name"] == "test_api_plugin")
    assert target["mode"] == "active"
    assert target["description"] == "用于测试 API 的插件"
    assert len(target["params_schema"]) == 1
    assert target["params_schema"][0]["name"] == "foo"
    assert target["source_path"] is None or not target["source_path"].startswith("/")

    # 测试 POST /api/plugins/reload
    reload_resp = api_client.post("/api/plugins/reload", headers=headers)
    assert reload_resp.status_code == 200
    data = reload_resp.json()
    assert "count" in data
    assert "plugins" in data
    assert isinstance(data["plugins"], list)


def test_test_plugin_endpoint(api_client):
    """测试 Web 调试沙箱接口 POST /api/plugins/{name}/test"""
    token = _login(api_client)
    headers = _auth(token)

    # 404 测试
    resp_404 = api_client.post(
        "/api/plugins/non_existent_plugin/test",
        headers=headers,
        json={"text": "hello"},
    )
    assert resp_404.status_code == 404

    # 注册响应型计算插件
    @PluginRegistry.register(
        name="test_calculator_sandbox",
        mode="reactive",
        description="计算器沙箱测试",
    )
    async def calc_handler(ctx: PluginContext):
        if "1+1" in ctx.message.text:
            ctx.log("计算表达式 1+1")
            await ctx.reply("2")
            return True
        return False

    # 命中测试
    resp_match = api_client.post(
        "/api/plugins/test_calculator_sandbox/test",
        headers=headers,
        json={"text": "请回答 1+1=?"},
    )
    assert resp_match.status_code == 200
    data = resp_match.json()
    assert data["success"] is True
    assert data["handled"] is True
    assert data["reply_text"] == "2"
    assert data["isolation"] == "in_process"
    assert data["killed"] is False
    assert any("计算表达式 1+1" in log for log in data["logs"])
    assert data["duration_ms"] >= 0

    # 未命中测试
    resp_no_match = api_client.post(
        "/api/plugins/test_calculator_sandbox/test",
        headers=headers,
        json={"text": "无关消息"},
    )
    assert resp_no_match.status_code == 200
    data_no_match = resp_no_match.json()
    assert data_no_match["success"] is True
    assert data_no_match["handled"] is False
    assert data_no_match["reply_text"] is None
    assert data_no_match["isolation"] == "in_process"
    assert data_no_match["killed"] is False


def test_test_plugin_endpoint_error_and_timeout(api_client):
    """测试 Web 调试沙箱接口捕获异常与超时"""
    token = _login(api_client)
    headers = _auth(token)
    _register_sandbox_worker_fixtures()

    resp_crash = api_client.post(
        "/api/plugins/test_crashing_plugin/test",
        headers=headers,
        json={"text": "boom"},
    )
    assert resp_crash.status_code == 200
    data = resp_crash.json()
    assert data["success"] is False
    assert data["handled"] is False
    assert "模拟插件执行崩溃" in data["error"]
    assert any("模拟插件执行崩溃" in log for log in data["logs"])


def test_test_plugin_endpoint_sync_hang_killed(api_client, monkeypatch):
    """测试同步死循环插件在沙箱中被进程组硬杀，返回 isolation=subprocess 与 killed=True"""
    _register_sandbox_worker_fixtures()
    token = _login(api_client)
    headers = _auth(token)
    monkeypatch.setenv("PLUGIN_TEST_TIMEOUT", "0.2")

    resp = api_client.post(
        "/api/plugins/test_sync_hang_sandbox/test",
        headers=headers,
        json={"text": "ping"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["isolation"] == "subprocess"
    assert data["killed"] is True
    assert "超时" in data["error"]


def test_toggle_plugin_endpoint(api_client):
    """测试插件启用/停用软开关切换接口"""
    token = _login(api_client)
    headers = _auth(token)

    @PluginRegistry.register(
        name="test_toggle_candidate",
        mode="reactive",
        description="测试软开关切换",
    )
    def toggle_handler(ctx: PluginContext):
        return True

    # 初始状态应为启用
    resp_init = api_client.get("/api/plugins", headers=headers)
    assert resp_init.status_code == 200
    item = next(p for p in resp_init.json() if p["name"] == "test_toggle_candidate")
    assert item["enabled"] is True

    # 第一次 toggle: 变为停用
    resp_toggle1 = api_client.post("/api/plugins/test_toggle_candidate/toggle", headers=headers)
    assert resp_toggle1.status_code == 200
    data1 = resp_toggle1.json()
    assert data1["name"] == "test_toggle_candidate"
    assert data1["enabled"] is False

    # 再次查询列表验证
    resp_list1 = api_client.get("/api/plugins", headers=headers)
    item1 = next(p for p in resp_list1.json() if p["name"] == "test_toggle_candidate")
    assert item1["enabled"] is False

    # 第二次 toggle: 恢复启用
    resp_toggle2 = api_client.post("/api/plugins/test_toggle_candidate/toggle", headers=headers)
    assert resp_toggle2.status_code == 200
    assert resp_toggle2.json()["enabled"] is True

    # 测试对不存在的插件 toggle 返回 404
    resp_404 = api_client.post("/api/plugins/non_existent_xyz/toggle", headers=headers)
    assert resp_404.status_code == 404


def test_test_plugin_reaction(api_client):
    """测试在沙箱演练场中使用 ctx.react 并返回 reacted_emojis"""
    token = _login(api_client)
    headers = _auth(token)

    @PluginRegistry.register(
        name="test_reaction_plugin",
        mode="reactive",
    )
    async def reaction_handler(ctx: PluginContext):
        await ctx.react("🎉")
        return True

    resp = api_client.post(
        "/api/plugins/test_reaction_plugin/test",
        headers=headers,
        json={"text": "congrats"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["handled"] is True
    assert "🎉" in data["reacted_emojis"]


def test_is_builtin_plugin_path_edge_cases(monkeypatch, tmp_path):
    """测试 is_builtin_plugin_path 的路径层级与防误判逻辑。"""
    # 1. 空值或 None
    assert is_builtin_plugin_path(None) is False
    assert is_builtin_plugin_path("") is False

    builtin_root = tmp_path / "sys_plugins"
    builtin_root.mkdir()
    monkeypatch.setenv("BUILTIN_PLUGINS_DIR", str(builtin_root))

    # 2. 真实内置目录下的单文件与目录型插件文件
    single_file = builtin_root / "builtin_single.py"
    single_file.write_text("# dummy", encoding="utf-8")
    assert is_builtin_plugin_path(single_file) is True

    dir_plugin = builtin_root / "my_dir_plugin" / "main.py"
    dir_plugin.parent.mkdir(parents=True)
    dir_plugin.write_text("# dummy", encoding="utf-8")
    assert is_builtin_plugin_path(dir_plugin) is True

    # 3. 相似前缀误判防护：如 sys_plugins-copy 或 sys_plugins_custom
    similar_prefix_dir = tmp_path / "sys_plugins-copy"
    similar_prefix_dir.mkdir()
    similar_file = similar_prefix_dir / "evil.py"
    similar_file.write_text("# dummy", encoding="utf-8")
    assert is_builtin_plugin_path(similar_file) is False

    # 4. 自定义外部目录
    custom_dir = tmp_path / "user_custom_plugins"
    custom_dir.mkdir()
    custom_file = custom_dir / "user.py"
    custom_file.write_text("# dummy", encoding="utf-8")
    assert is_builtin_plugin_path(custom_file) is False


def test_repo_builtin_plugins_marked_builtin():
    """测试官方仓库中的 plugins/ 目录插件被正确识别为 builtin=True。"""
    repo_plugins = Path(__file__).resolve().parent.parent / "plugins"
    if not repo_plugins.is_dir():
        return
    for sub in repo_plugins.iterdir():
        if sub.is_dir() and (sub / "main.py").is_file():
            assert is_builtin_plugin_path(sub / "main.py") is True


def test_builtin_plugins_real_directory_load_and_api(api_client, monkeypatch, tmp_path):
    """测试通过真实目录加载插件并验证 PluginMeta.builtin 及 API 序列化输出。"""
    token = _login(api_client)
    headers = _auth(token)

    PluginRegistry.clear()

    # 创建真实内置插件目录
    builtin_dir = tmp_path / "builtin_plugins"
    builtin_dir.mkdir()
    math_dir = builtin_dir / "test_builtin_math"
    math_dir.mkdir()
    math_code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('test_real_builtin_pkg', mode='reactive')\n"
        "def pkg_handler(ctx):\n"
        "    return True\n"
    )
    (math_dir / "main.py").write_text(math_code, encoding="utf-8")

    single_code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('test_real_builtin_single', mode='active')\n"
        "def single_handler(ctx):\n"
        "    return True\n"
    )
    (builtin_dir / "test_builtin_single.py").write_text(single_code, encoding="utf-8")

    # 创建真实自定义外部插件目录
    custom_dir = tmp_path / "custom_plugins"
    custom_dir.mkdir()
    custom_pkg = custom_dir / "test_custom_pkg"
    custom_pkg.mkdir()
    custom_pkg_code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('test_real_custom_pkg', mode='reactive')\n"
        "def custom_pkg_handler(ctx):\n"
        "    return True\n"
    )
    (custom_pkg / "main.py").write_text(custom_pkg_code, encoding="utf-8")

    custom_single_code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('test_real_custom_single', mode='active')\n"
        "def custom_single_handler(ctx):\n"
        "    return True\n"
    )
    (custom_dir / "test_custom_single.py").write_text(custom_single_code, encoding="utf-8")

    # 设置环境变量
    monkeypatch.setenv("BUILTIN_PLUGINS_DIR", str(builtin_dir))
    monkeypatch.setenv("PLUGINS_DIR", str(custom_dir))

    # 1. 验证真实从目录扫描加载后的 PluginMeta 核心属性
    loaded_builtin = PluginRegistry.load_plugins_from_dir(builtin_dir)
    assert loaded_builtin == 2
    meta_builtin_pkg = PluginRegistry.get("test_real_builtin_pkg")
    assert meta_builtin_pkg is not None
    assert meta_builtin_pkg.builtin is True

    meta_builtin_single = PluginRegistry.get("test_real_builtin_single")
    assert meta_builtin_single is not None
    assert meta_builtin_single.builtin is True

    loaded_custom = PluginRegistry.load_plugins_from_dir(custom_dir)
    assert loaded_custom == 2
    meta_custom_pkg = PluginRegistry.get("test_real_custom_pkg")
    assert meta_custom_pkg is not None
    assert meta_custom_pkg.builtin is False

    meta_custom_single = PluginRegistry.get("test_real_custom_single")
    assert meta_custom_single is not None
    assert meta_custom_single.builtin is False

    # 2. 验证 GET /api/plugins 返回的 JSON 序列化结果
    resp = api_client.get("/api/plugins", headers=headers)
    assert resp.status_code == 200
    plugins = {p["name"]: p for p in resp.json()}
    assert plugins["test_real_builtin_pkg"]["builtin"] is True
    assert plugins["test_real_builtin_single"]["builtin"] is True
    assert plugins["test_real_custom_pkg"]["builtin"] is False
    assert plugins["test_real_custom_single"]["builtin"] is False

    # 3. 验证 POST /api/plugins/reload 后重新扫描的 builtin 字段与计数
    resp_reload = api_client.post("/api/plugins/reload", headers=headers)
    assert resp_reload.status_code == 200
    reload_data = resp_reload.json()
    assert reload_data["count"] >= 4
    reloaded_plugins = {p["name"]: p for p in reload_data["plugins"]}
    assert reloaded_plugins["test_real_builtin_pkg"]["builtin"] is True
    assert reloaded_plugins["test_real_builtin_single"]["builtin"] is True
    assert reloaded_plugins["test_real_custom_pkg"]["builtin"] is False
    assert reloaded_plugins["test_real_custom_single"]["builtin"] is False
