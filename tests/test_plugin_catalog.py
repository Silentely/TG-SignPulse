import tempfile
from pathlib import Path
import pytest
from backend.services.plugin_catalog import StaticPluginCatalog, StaticPluginMetadata


def test_static_plugin_catalog_extracts_metadata_without_executing_code():
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_dir = Path(tmpdir) / "test_malicious"
        plugin_dir.mkdir()
        sentinel_file = Path(tmpdir) / "hacked.txt"

        # 插件顶层含有副作用代码，若被动态 import 会生成 hacked.txt
        code = f'''
from pathlib import Path
Path("{sentinel_file}").write_text("pwned")

VERSION = "1.2.3"
PARAMS_SCHEMA = [
    {{"name": "reply_prefix", "label": "回复前缀", "type": "string", "default": ""}}
]

def solve():
    return "ok"
'''
        (plugin_dir / "main.py").write_text(code, encoding="utf-8")

        catalog = StaticPluginCatalog(plugins_dir=Path(tmpdir))
        metadata = catalog.scan_plugin(plugin_dir)

        assert metadata is not None
        assert metadata.version == "1.2.3"
        # 必须兼容 List 结构的 params_schema
        assert isinstance(metadata.params_schema, list)
        assert metadata.params_schema[0]["name"] == "reply_prefix"
        # 核心安全断言：顶层代码绝对未在当前解释器进程中运行！
        assert not sentinel_file.exists(), "恶意顶层代码被宿主进程动态执行了！"


def test_static_plugin_catalog_refresh_and_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        p1 = root / "plug1"
        p1.mkdir()
        (p1 / "main.py").write_text(
            'VERSION = "2.0.0"\nDESCRIPTION = "Plugin One"\nPARAMS_SCHEMA = [{"name": "foo", "type": "string"}]\n',
            encoding="utf-8",
        )

        p2 = root / "plug2"
        p2.mkdir()
        (p2 / "main.py").write_text(
            'VERSION = "3.1.0"\nAUTHOR = "Dev"\nTAGS = ["tag1", "tag2"]\n',
            encoding="utf-8",
        )

        catalog = StaticPluginCatalog(plugins_dir=root)
        items = catalog.refresh_catalog()
        assert len(items) == 2
        names = {m.name for m in items}
        assert names == {"plug1", "plug2"}

        m1 = catalog.get("plug1")
        assert m1 is not None
        assert m1.version == "2.0.0"
        assert m1.description == "Plugin One"
        assert m1.params_schema == [{"name": "foo", "type": "string"}]

        m2 = catalog.get("plug2")
        assert m2 is not None
        assert m2.version == "3.1.0"
        assert m2.author == "Dev"
        assert m2.tags == ["tag1", "tag2"]


def test_static_plugin_catalog_handles_syntax_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        bad = root / "bad_syntax"
        bad.mkdir()
        (bad / "main.py").write_text("def broken_func(\n", encoding="utf-8")

        catalog = StaticPluginCatalog(plugins_dir=root)
        meta = catalog.scan_plugin(bad)
        assert meta is not None
        assert meta.name == "bad_syntax"
        assert meta.syntax_unverified is True
