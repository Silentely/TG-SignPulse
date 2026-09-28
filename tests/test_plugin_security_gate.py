"""插件 AST 安全门禁绕过测试。

覆盖 compute_plugin_security_report 与 _SecurityVisitor 的失败关闭行为：
- 阻断判据基于告警严重度，不再按规则名子串匹配
- star-import / syntax-error / audit-error 一律失败关闭
- 赋值别名覆盖 Name 右值与多元组/多目标
"""

from __future__ import annotations

import pytest

from tg_signer.core.plugins import (
    _SecurityVisitor,
    audit_plugin_source,
    compute_plugin_security_report,
)


def _rules(source: str) -> set[str]:
    return {str(w.get("rule", "")) for w in audit_plugin_source(source)}


def _blocked(source: str) -> bool:
    return compute_plugin_security_report(source)["can_save_safely"] is False


class TestAliasBypassPayloads:
    """历史上 visit_Assign 只覆盖「单 Name 目标 + Attribute 右值」，以下载荷可绕过。"""

    PAYLOADS = [
        # 模块别名：sp = subprocess（Name 右值）
        "import subprocess\nsp = subprocess\nsp.run(['ls'])\n",
        # 函数别名链：s = os.system（Attribute 右值）
        "import os\ns = os.system\ns('id')\n",
        # 多目标赋值：f = g = os.system
        "import os\nf = g = os.system\nf('id')\n",
        # 元组解构目标
        "import os\n(a, b) = (os.system, os.popen)\na('id')\n",
        # 星号导入使命名空间不可追踪
        "from shutil import *\nmove('/a', '/b')\n",
        # 语法错误：审计本身没跑成
        "def broken(:\n    pass\n",
    ]

    @pytest.mark.parametrize("source", PAYLOADS)
    def test_payload_is_blocked(self, source):
        assert _blocked(source) is True, source

    def test_name_right_value_module_alias_is_flagged(self):
        assert "dangerous-alias:subprocess.run" in _rules(
            "import subprocess\nsp = subprocess.run\nsp(['ls'])\n"
        )

    def test_multi_target_alias_records_every_name(self):
        rules = _rules("import os\nf = g = os.system\nf('id')\n")
        assert any(r.startswith("dangerous-alias:os.system") for r in rules)

    def test_tuple_target_alias_is_flagged(self):
        rules = _rules("import os\n(a, b) = (os.system, os.popen)\na('id')\n")
        assert any(r.startswith("dangerous-alias:") for r in rules)


class TestFailClosedRules:
    def test_star_import_is_blocked_even_without_dangerous_call(self):
        """星号导入本身就必须阻断，不依赖后续出现高危调用。"""
        source = "from os import *\nvalue = 1\n"
        report = compute_plugin_security_report(source)
        assert report["can_save_safely"] is False
        assert any(w["rule"].startswith("star-import") for w in report["warnings"])

    def test_syntax_error_is_blocked(self):
        report = compute_plugin_security_report("def f(:\n")
        assert report["can_save_safely"] is False
        assert any(w["rule"] == "syntax-error" for w in report["warnings"])

    def test_high_severity_warning_blocks_regardless_of_rule_name(self):
        """阻断判据按严重度走：high 一律阻断，不靠规则名子串。"""

        class _FakeVisitor(_SecurityVisitor):
            def visit_Module(self, node):  # pragma: no cover - 仅注入告警
                self.warnings.append(
                    {
                        "line": 1,
                        "column": 0,
                        "severity": "high",
                        "rule": "brand-new-rule-with-no-known-keyword",
                        "message": "synthetic high severity",
                    }
                )
                self.generic_visit(node)

        import tg_signer.core.plugins as plugins_mod

        original = plugins_mod._SecurityVisitor
        plugins_mod._SecurityVisitor = _FakeVisitor
        try:
            report = compute_plugin_security_report("x = 1\n")
        finally:
            plugins_mod._SecurityVisitor = original
        assert report["can_save_safely"] is False

    def test_clean_source_is_allowed(self):
        source = (
            "from tg_signer.core.plugins import PluginRegistry, BasePlugin\n\n\n"
            "@PluginRegistry.register('ok_plugin', name='Ok', mode='reactive')\n"
            "class OkPlugin(BasePlugin):\n"
            "    async def run(self, event, context):\n"
            "        return True\n"
        )
        report = compute_plugin_security_report(source)
        assert report["can_save_safely"] is True
        assert report["risk_level"] == "safe"
