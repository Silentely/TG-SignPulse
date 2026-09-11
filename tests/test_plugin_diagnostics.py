import tempfile
from pathlib import Path

from tg_signer.core.plugins import PluginRegistry


def test_plugin_diagnostics_missing_dependency():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmp_dir:
        broken_plugin = Path(tmp_dir) / "broken_dep.py"
        broken_plugin.write_text(
            """
import non_existent_dummy_pkg_123456789
from tg_signer.core.plugins import PluginRegistry, PluginContext

@PluginRegistry.register("broken_dep")
async def handler(ctx: PluginContext):
    return True
""",
            encoding="utf-8",
        )
        loaded = PluginRegistry.load_plugins_from_dir(tmp_dir)
        assert loaded == 0
        errors = PluginRegistry.get_load_errors()
        assert len(errors) == 1
        err = errors[0]
        assert err.error_type == "missing_dependency"
        assert "non_existent_dummy_pkg_123456789" in err.missing_module
        assert err.suggested_command == "pip install non_existent_dummy_pkg_123456789"
        assert err.plugin_name == "broken_dep"


def test_plugin_diagnostics_syntax_error():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmp_dir:
        syntax_err_plugin = Path(tmp_dir) / "broken_syntax.py"
        syntax_err_plugin.write_text(
            """
def broken_syntax_func(
""",
            encoding="utf-8",
        )
        loaded = PluginRegistry.load_plugins_from_dir(tmp_dir)
        assert loaded == 0
        errors = PluginRegistry.get_load_errors()
        assert len(errors) == 1
        err = errors[0]
        assert err.error_type == "syntax_error"
        assert "broken_syntax" in err.plugin_name


def test_plugin_diagnostics_clear():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmp_dir:
        broken = Path(tmp_dir) / "bad.py"
        broken.write_text("import bad_module_abc\n", encoding="utf-8")
        PluginRegistry.load_plugins_from_dir(tmp_dir)
        assert len(PluginRegistry.get_load_errors()) == 1
        PluginRegistry.clear()
        assert len(PluginRegistry.get_load_errors()) == 0
