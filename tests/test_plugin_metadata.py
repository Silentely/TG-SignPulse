import tempfile
from datetime import datetime
from pathlib import Path

from tg_signer.core.plugins import PluginContext, PluginRegistry


def test_plugin_metadata_explicit_decorator():
    PluginRegistry.clear()

    @PluginRegistry.register(
        name="test_meta_explicit",
        version="2.1.0",
        updated_at="2026-08-15",
        author="Alice",
        description="Explicit test",
    )
    async def handler(ctx: PluginContext) -> bool:
        return True

    meta = PluginRegistry.get("test_meta_explicit")
    assert meta is not None
    assert meta.version == "2.1.0"
    assert meta.updated_at == "2026-08-15"
    assert meta.author == "Alice"


def test_plugin_metadata_module_globals():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmp_dir:
        plugin_file = Path(tmp_dir) / "sample_globals.py"
        plugin_file.write_text(
            '''
from tg_signer.core.plugins import PluginRegistry, PluginContext

VERSION = "1.3.0"
UPDATED_AT = "2026-09-01"
AUTHOR = "Bob Developer"

@PluginRegistry.register(name="sample_globals_plugin")
async def handle_sample(ctx: PluginContext):
    return True
''',
            encoding="utf-8",
        )
        loaded = PluginRegistry.load_plugins_from_dir(tmp_dir)
        assert loaded == 1
        meta = PluginRegistry.get("sample_globals_plugin")
        assert meta is not None
        assert meta.version == "1.3.0"
        assert meta.updated_at == "2026-09-01"
        assert meta.author == "Bob Developer"


def test_plugin_metadata_fallback_to_defaults_and_mtime():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmp_dir:
        plugin_file = Path(tmp_dir) / "sample_mtime.py"
        plugin_file.write_text(
            '''
from tg_signer.core.plugins import PluginRegistry, PluginContext

@PluginRegistry.register(name="sample_mtime_plugin")
async def handle_sample(ctx: PluginContext):
    return True
''',
            encoding="utf-8",
        )
        loaded = PluginRegistry.load_plugins_from_dir(tmp_dir)
        assert loaded == 1
        meta = PluginRegistry.get("sample_mtime_plugin")
        assert meta is not None
        assert meta.version == "1.0.0"
        assert meta.author == ""
        # updated_at should be formatted as YYYY-MM-DD from file mtime
        assert len(meta.updated_at) == 10
        assert meta.updated_at.count("-") == 2
        # verify it matches current or recent date
        now_str = datetime.now().strftime("%Y-%m-%d")
        assert meta.updated_at == now_str


def test_plugin_metadata_priority_decorator_over_globals():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmp_dir:
        plugin_file = Path(tmp_dir) / "sample_priority.py"
        plugin_file.write_text(
            """
from tg_signer.core.plugins import PluginRegistry, PluginContext

VERSION = "1.0.0"
UPDATED_AT = "2026-01-01"
AUTHOR = "Global Author"

@PluginRegistry.register(
    name="sample_priority_plugin",
    version="2.0.0",
    updated_at="2026-05-01",
    author="Decorator Author",
)
async def handle_sample(ctx: PluginContext):
    return True
""",
            encoding="utf-8",
        )
        loaded = PluginRegistry.load_plugins_from_dir(tmp_dir)
        assert loaded == 1
        meta = PluginRegistry.get("sample_priority_plugin")
        assert meta is not None
        assert meta.version == "2.0.0"
        assert meta.updated_at == "2026-05-01"
        assert meta.author == "Decorator Author"
