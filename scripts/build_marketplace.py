#!/usr/bin/env python3
"""Build and validate TG-SignPulse community plugins and generate marketplace catalog.

Usage:
  python scripts/build_marketplace.py --check
  python scripts/build_marketplace.py --output-dir dist/marketplace
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from tg_signer.core.plugins import audit_plugin_source
except ImportError:
    class _SecurityVisitor(ast.NodeVisitor):  # type: ignore
        def __init__(self) -> None:
            self.warnings: List[Dict[str, Any]] = []

        def visit_Call(self, node: ast.Call) -> None:
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                func_name = f"{node.func.value.id}.{node.func.attr}"
            if func_name in ("eval", "exec", "compile", "__import__"):
                self.warnings.append({
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": "forbidden_dynamic_execution",
                    "message": f"禁止调用动态执行函数: {func_name}()",
                })
            self.generic_visit(node)

    def audit_plugin_source(source: str) -> List[Dict[str, Any]]:
        tree = ast.parse(source)
        v = _SecurityVisitor()
        v.visit(tree)
        return v.warnings


PLUGIN_ID_REGEX = re.compile(r"^[a-z0-9_]{3,32}$")
SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+$")
VALID_MODES = {"reactive", "active"}
VALID_CATEGORIES = {"utility", "notification", "message", "captcha", "helper", "entertainment"}


def validate_plugin(plugin_dir: Path) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Validate a community plugin directory. Returns (is_valid, errors, manifest)."""
    errors: List[str] = []
    manifest: Dict[str, Any] = {}
    folder_name = plugin_dir.name

    if not PLUGIN_ID_REGEX.match(folder_name):
        errors.append(f"目录名称 '{folder_name}' 不符合规范，必须为 3-32 位小写字母、数字或下划线")

    plugin_json_file = plugin_dir / "plugin.json"
    if not plugin_json_file.is_file():
        errors.append("缺少必选元数据文件: plugin.json")
    else:
        try:
            manifest = json.loads(plugin_json_file.read_text(encoding="utf-8"))
            pid = manifest.get("id")
            if pid != folder_name:
                errors.append(f"plugin.json 中的 id '{pid}' 与目录名 '{folder_name}' 不一致")
            if not manifest.get("name") or len(str(manifest.get("name")).strip()) < 2:
                errors.append("plugin.json 缺少有效的 'name' 属性")
            ver = str(manifest.get("version", ""))
            if not SEMVER_REGEX.match(ver):
                errors.append(f"plugin.json 中的 'version' '{ver}' 不符合语义化版本格式 (如 1.0.0)")
            mode = manifest.get("mode")
            if mode not in VALID_MODES:
                errors.append(f"plugin.json 中的 'mode' '{mode}' 无效，必须为 reactive 或 active")
            cat = manifest.get("category")
            if cat not in VALID_CATEGORIES:
                errors.append(f"plugin.json 中的 'category' '{cat}' 无效，可用分类: {VALID_CATEGORIES}")
            if not manifest.get("description"):
                errors.append("plugin.json 缺少 'description' 属性")
            if not manifest.get("author"):
                errors.append("plugin.json 缺少 'author' 属性")

            schema_file = plugin_dir.parent / "schema.json"
            if schema_file.is_file():
                try:
                    import jsonschema
                    schema = json.loads(schema_file.read_text(encoding="utf-8"))
                    jsonschema.validate(instance=manifest, schema=schema)
                except ImportError:
                    pass
                except Exception as exc:
                    errors.append(f"plugin.json 未通过 schema.json 规范校验: {exc}")
        except json.JSONDecodeError as exc:
            errors.append(f"plugin.json 不是合法的 JSON 格式: {exc}")

    main_py_file = plugin_dir / "main.py"
    if not main_py_file.is_file():
        errors.append("缺少必选入口代码文件: main.py")

    # 递归审计插件包内的所有 Python 模块源码，严禁在 helper 模块中隐藏高危系统调用
    for py_file in sorted(plugin_dir.glob("**/*.py")):
        rel_name = py_file.relative_to(plugin_dir).as_posix()
        try:
            code_text = py_file.read_text(encoding="utf-8")
            warnings = audit_plugin_source(code_text)
            forbidden = [
                w for w in warnings
                if w.get("severity") in ("high", "critical")
                or "subprocess" in str(w.get("message", "")).lower()
                or "os.system" in str(w.get("message", "")).lower()
            ]
            if forbidden:
                for w in forbidden:
                    errors.append(f"{rel_name} 触发安全审计规则 (第 {w.get('line', 1)} 行): {w.get('message', '')}")
        except UnicodeDecodeError:
            errors.append(f"{rel_name} 编码错误，必须使用 UTF-8 编码")
        except SyntaxError as exc:
            errors.append(f"{rel_name} 存在 Python 语法错误: {exc}")

    readme_file = plugin_dir / "README.md"
    if not readme_file.is_file():
        errors.append("建议补充 README.md 说明文档")

    is_valid = len(errors) == 0
    return is_valid, errors, manifest


def package_plugin(plugin_dir: Path, output_plugins_dir: Path, version: str) -> Tuple[Path, str, int]:
    """Package plugin directory into zip and return (zip_path, sha256, file_size)."""
    pid = plugin_dir.name
    zip_name = f"{pid}-{version}.zip"
    zip_path = output_plugins_dir / zip_name

    sha256_hash = hashlib.sha256()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(plugin_dir):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache") and not d.startswith(".")]
            for file in sorted(files):
                if file.startswith(".") or file.endswith(".pyc"):
                    continue
                file_path = Path(root) / file
                arcname = file_path.relative_to(plugin_dir).as_posix()
                zf.write(file_path, arcname=arcname)

    # Compute hash
    data = zip_path.read_bytes()
    sha256_hash.update(data)
    checksum = sha256_hash.hexdigest()
    size = len(data)

    return zip_path, checksum, size


def main() -> int:
    parser = argparse.ArgumentParser(description="TG-SignPulse Marketplace Builder")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("community_plugins"),
        help="Path to community_plugins directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist/marketplace"),
        help="Path to output directory for marketplace assets",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://raw.githubusercontent.com/Silentely/TG-SignPulse/dev/dist/marketplace/plugins/",
        help="Base URL prefix for plugin downloads",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check and validate plugins without building artifacts (useful in CI)",
    )
    parser.add_argument(
        "--ai-enrich",
        action="store_true",
        help="Use AI to automatically enrich missing English descriptions and tags during catalog build",
    )
    args = parser.parse_args()

    source_dir: Path = args.source_dir.resolve()
    if not source_dir.is_dir():
        print(f"[ERROR] Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    plugin_dirs = [
        d for d in sorted(source_dir.iterdir())
        if d.is_dir() and not d.name.startswith(("_", "."))
    ]

    print(f"[*] Found {len(plugin_dirs)} community plugin(s) to inspect in: {source_dir}")

    total_valid = 0
    has_critical_errors = False
    catalog_items: List[Dict[str, Any]] = []

    output_dir: Path = args.output_dir.resolve()
    plugins_output_dir = output_dir / "plugins"

    if not args.check:
        plugins_output_dir.mkdir(parents=True, exist_ok=True)

    for pdir in plugin_dirs:
        is_valid, errors, manifest = validate_plugin(pdir)
        pid = pdir.name
        if not is_valid:
            has_critical_errors = True
            print(f"  ❌ [{pid}] 校验失败:")
            for err in errors:
                print(f"     - {err}")
        else:
            total_valid += 1
            print(f"  ✅ [{pid}] 校验通过 (v{manifest.get('version', '1.0.0')})")

            if not args.check:
                ver = manifest["version"]
                zip_path, checksum, size = package_plugin(pdir, plugins_output_dir, ver)

                # Read readme if present
                readme_text = ""
                readme_file = pdir / "README.md"
                if readme_file.is_file():
                    readme_text = readme_file.read_text(encoding="utf-8")

                description_en = manifest.get("description_en", "")
                features = manifest.get("features", [])
                tags = manifest.get("tags", [])
                if args.ai_enrich and (not description_en or not features):
                    try:
                        try:
                            from scripts.ai_review_plugin import review_plugin_directory
                        except ImportError:
                            from ai_review_plugin import review_plugin_directory
                        has_key = bool(os.environ.get("PLUGIN_REVIEW_GEMINI_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("PLUGIN_REVIEW_API_KEY") or os.environ.get("OPENAI_API_KEY"))
                        ok, review_meta, _ = review_plugin_directory(pdir, mock_mode=not has_key)
                        if ok and "enriched_metadata" in review_meta:
                            ai_meta = review_meta["enriched_metadata"]
                            if not description_en and ai_meta.get("description_en"):
                                description_en = ai_meta["description_en"]
                            if not features and ai_meta.get("features"):
                                features = ai_meta["features"]
                            if ai_meta.get("tags"):
                                tags = sorted(set(tags).union(set(ai_meta["tags"])))
                            print(f"     ✨ AI 补全元数据: en-US 简介与 {len(tags)} 个标签")
                    except Exception as exc:
                        print(f"     ⚠️ AI 补全跳过: {exc}")
                item: Dict[str, Any] = {
                    "id": manifest["id"],
                    "name": manifest["name"],
                    "version": ver,
                    "mode": manifest.get("mode", "reactive"),
                    "category": manifest.get("category", "utility"),
                    "description": manifest.get("description", ""),
                    "description_en": description_en,
                    "features": features,
                    "author": manifest.get("author", "Community"),
                    "homepage": manifest.get("homepage", ""),
                    "icon": manifest.get("icon", "puzzle"),
                    "tags": tags,
                    "min_app_version": manifest.get("min_app_version", "1.8.0"),
                    "permissions": manifest.get("permissions", []),
                    "params_schema": manifest.get("params_schema", []),
                    "download_url": f"{args.base_url.rstrip('/')}/{zip_path.name}",
                    "sha256": checksum,
                    "size": size,
                    "readme": readme_text,
                    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
                catalog_items.append(item)

    if has_critical_errors:
        print("\n[FAILED] One or more plugins failed validation!", file=sys.stderr)
        return 1

    if args.check:
        print(f"\n[SUCCESS] All {total_valid} community plugin(s) passed validation!")
        return 0

    # Write marketplace.json
    catalog: Dict[str, Any] = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_plugins": len(catalog_items),
        "plugins": catalog_items,
    }

    marketplace_json = output_dir / "marketplace.json"
    marketplace_json.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SUCCESS] Built {len(catalog_items)} marketplace plugin(s) into: {output_dir}")
    print(f"          - Catalog: {marketplace_json}")
    print(f"          - Archives: {plugins_output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
