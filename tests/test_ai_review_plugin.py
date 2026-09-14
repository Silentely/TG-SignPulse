import json
from pathlib import Path

from scripts.ai_review_plugin import (
    build_review_prompt,
    format_markdown_pr_comment,
    review_plugin_directory,
)


def test_build_review_prompt():
    manifest = {"id": "test_plugin", "name": "Test", "version": "1.0.0"}
    py_files = {"main.py": "print('hello')"}
    readme = "# Test Plugin"

    prompt = build_review_prompt(manifest, py_files, readme)
    assert "test_plugin" in prompt
    assert "print('hello')" in prompt
    assert "# Test Plugin" in prompt
    assert "STRICT JSON ONLY" in prompt


def test_ai_review_mock_mode():
    sample_dir = Path("community_plugins/bing_daily_quote")
    ok, result, backend = review_plugin_directory(sample_dir, mock_mode=True)
    assert ok is True
    assert backend == "mock"
    assert result["verdict"] == "APPROVED"
    assert result["risk_level"] == "SAFE"
    assert "enriched_metadata" in result
    assert result["enriched_metadata"]["description_en"] != ""


def test_ai_review_missing_manifest(tmp_path):
    empty_dir = tmp_path / "empty_plugin"
    empty_dir.mkdir()
    ok, result, backend = review_plugin_directory(empty_dir, mock_mode=True)
    assert ok is False
    assert backend == "missing_manifest"
    assert "Missing plugin.json" in result["error"]


def test_format_markdown_pr_comment():
    review_data = {
        "verdict": "APPROVED",
        "risk_level": "SAFE",
        "security_findings": ["No security issues detected."],
        "performance_diagnostics": ["Async event-loop clean."],
        "enriched_metadata": {
            "description_zh": "测试中文简介",
            "description_en": "Test English description",
            "tags": ["test", "demo"],
            "features": ["Feature A", "Feature B"],
            "suggested_category": "utility",
        },
        "review_summary_markdown": "LGTM!",
    }

    md = format_markdown_pr_comment("test_plugin", review_data, "gemini-1.5-flash")
    assert "## 🤖 TG-SignPulse AI 插件审查报告 (`test_plugin`)" in md
    assert "APPROVED" in md
    assert "🟢 安全 (Safe)" in md
    assert "测试中文简介" in md
    assert "Test English description" in md
    assert "`test`" in md
    assert "Feature A" in md


def test_ai_review_apply_metadata(tmp_path):
    # Setup temporary plugin
    plugin_dir = tmp_path / "mock_plugin"
    plugin_dir.mkdir()

    orig_manifest = {
        "id": "mock_plugin",
        "name": "Mock",
        "version": "1.0.0",
        "mode": "reactive",
        "category": "utility",
        "description": "原始中文描述",
        "author": "Tester",
        "tags": ["initial"],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(orig_manifest), encoding="utf-8")
    (plugin_dir / "main.py").write_text("# main.py\n", encoding="utf-8")

    import subprocess
    import sys

    # Run CLI with --mock and --apply
    cmd = [
        sys.executable,
        "scripts/ai_review_plugin.py",
        str(plugin_dir),
        "--mock",
        "--apply",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0

    # Verify plugin.json was enriched
    updated = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    assert "description_en" in updated
    assert len(updated["tags"]) >= 1
    assert "initial" in updated["tags"]
