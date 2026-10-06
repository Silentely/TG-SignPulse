from __future__ import annotations

import ast
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

try:
    from tg_signer.core.plugins import is_builtin_plugin_path
except ImportError:

    def is_builtin_plugin_path(path: Any) -> bool:
        return False


logger = logging.getLogger("backend.plugin_catalog")


@dataclass(frozen=True)
class StaticPluginMetadata:
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    mode: Literal["reactive", "active"] = "reactive"
    params_schema: Optional[List[Dict[str, Any]]] = None  # 真实对齐现有 PluginMeta
    source_path: str = ""
    source_sha256: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    icon: str = ""
    homepage: str = ""
    doc: str = ""
    builtin: bool = False
    isolation_mode: Literal["subprocess"] = "subprocess"
    permissions: List[str] = field(default_factory=list)
    syntax_unverified: bool = False

    def __post_init__(self) -> None:
        # plugin.json 的 mode 是不可信输入，这里做运行时收敛，避免非法取值向下游扩散
        if self.mode not in ("reactive", "active"):
            object.__setattr__(self, "mode", "reactive")


class StaticPluginCatalog:
    """基于 AST 静态分析的插件目录元数据解析器。

    完全在宿主进程中解析插件元数据（版本、参数模式、标签等），零代码执行，杜绝模块顶层恶意副作用。
    """

    def __init__(self, plugins_dir: Union[str, Path, List[Union[str, Path]]]):
        if isinstance(plugins_dir, (list, tuple)):
            self.plugins_dirs = [Path(d) for d in plugins_dir]
            self.plugins_dir = self.plugins_dirs[0] if self.plugins_dirs else Path(".")
        else:
            self.plugins_dir = Path(plugins_dir)
            self.plugins_dirs = [self.plugins_dir]
        self._cache: Dict[str, StaticPluginMetadata] = {}

    def get(self, name: str) -> Optional[StaticPluginMetadata]:
        return self._cache.get(name)

    def list_plugins(self) -> Dict[str, StaticPluginMetadata]:
        return dict(self._cache)

    def _safe_eval_literal(self, node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except Exception:
            return None

    def scan_plugin(self, plugin_path: Path) -> Optional[StaticPluginMetadata]:
        path = Path(plugin_path)
        if path.is_file() and path.suffix == ".py":
            main_py = path
            plugin_dir = path.parent
            default_name = path.stem
        elif path.is_dir():
            plugin_dir = path
            if (path / "main.py").is_file():
                main_py = path / "main.py"
            elif (path / "__init__.py").is_file():
                main_py = path / "__init__.py"
            else:
                return None
            default_name = path.name
        else:
            return None

        content = main_py.read_text(encoding="utf-8", errors="replace")
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

        try:
            tree = ast.parse(content, filename=str(main_py))
        except SyntaxError as e:
            logger.warning("插件 %s AST 解析语法错误: %s", default_name, e)
            return StaticPluginMetadata(
                name=default_name,
                source_path=str(main_py),
                source_sha256=sha256,
                syntax_unverified=True,
                builtin=is_builtin_plugin_path(main_py),
            )

        extracted: Dict[str, Any] = {
            "name": default_name,
            "source_path": str(main_py),
            "source_sha256": sha256,
            "builtin": is_builtin_plugin_path(main_py),
        }

        # 检查目录下是否存在 plugin.json 描述文件
        pjson_file = plugin_dir / "plugin.json"
        if pjson_file.is_file():
            try:
                pjson_data = json.loads(pjson_file.read_text(encoding="utf-8"))
                for k in (
                    "name",
                    "version",
                    "description",
                    "author",
                    "mode",
                    "category",
                    "icon",
                    "homepage",
                ):
                    if pjson_data.get(k):
                        extracted[k] = str(pjson_data[k]).strip()
                if isinstance(pjson_data.get("tags"), list):
                    extracted["tags"] = [str(x) for x in pjson_data["tags"]]
                if isinstance(pjson_data.get("permissions"), list):
                    extracted["permissions"] = [
                        str(x) for x in pjson_data["permissions"]
                    ]
                if isinstance(pjson_data.get("params_schema"), list):
                    extracted["params_schema"] = pjson_data["params_schema"]
            except Exception:
                pass

        # 提取模块文档字符串作为候选 doc / description
        docstring = ast.get_docstring(tree)
        if docstring:
            extracted["doc"] = docstring
            if not extracted.get("description"):
                first_line = docstring.strip().split("\n")[0].strip()
                if first_line:
                    extracted["description"] = first_line

        # 1. 扫描顶层全局变量赋值（支持 Assign 与 AnnAssign）
        for stmt in tree.body:
            target_names = []
            val_node = None
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        target_names.append(target.id)
                val_node = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.target, ast.Name) and stmt.value is not None:
                    target_names.append(stmt.target.id)
                    val_node = stmt.value

            if val_node is not None:
                val = self._safe_eval_literal(val_node)
                if val is not None:
                    for tname in target_names:
                        key = tname.lower()
                        if key in {
                            "version",
                            "description",
                            "author",
                            "mode",
                            "category",
                            "icon",
                            "homepage",
                            "doc",
                        }:
                            extracted[key] = str(val)
                        elif key == "params_schema" and isinstance(val, list):
                            extracted["params_schema"] = val
                        elif key == "tags" and isinstance(val, list):
                            extracted["tags"] = [str(x) for x in val]
                        elif key == "permissions" and isinstance(val, list):
                            extracted["permissions"] = [str(x) for x in val]

        # 2. 扫描函数装饰器中的显式注册参数（优先级高于全局变量）
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in stmt.decorator_list:
                    if isinstance(deco, ast.Call):
                        # 判断是否为 PluginRegistry.register 或 register_plugin
                        is_reg = False
                        if (
                            isinstance(deco.func, ast.Attribute)
                            and deco.func.attr == "register"
                        ):
                            is_reg = True
                        elif (
                            isinstance(deco.func, ast.Name)
                            and "register" in deco.func.id
                        ):
                            is_reg = True

                        if is_reg:
                            # 提取位置参数 (例如 @PluginRegistry.register("name"))
                            if deco.args:
                                first_arg = self._safe_eval_literal(deco.args[0])
                                if first_arg and isinstance(first_arg, str):
                                    extracted["name"] = first_arg

                            # 提取关键字参数
                            for kw in deco.keywords:
                                if not kw.arg:
                                    continue
                                kw_val = self._safe_eval_literal(kw.value)
                                if kw_val is not None:
                                    k = kw.arg.lower()
                                    if k in {
                                        "name",
                                        "version",
                                        "description",
                                        "author",
                                        "mode",
                                        "category",
                                        "icon",
                                        "homepage",
                                        "doc",
                                    }:
                                        extracted[k] = str(kw_val)
                                    elif k == "params_schema" and isinstance(
                                        kw_val, list
                                    ):
                                        extracted["params_schema"] = kw_val
                                    elif k == "tags" and isinstance(kw_val, list):
                                        extracted["tags"] = [str(x) for x in kw_val]
                                    elif k == "permissions" and isinstance(
                                        kw_val, list
                                    ):
                                        extracted["permissions"] = [
                                            str(x) for x in kw_val
                                        ]

        return StaticPluginMetadata(**extracted)

    def refresh_catalog(self) -> List[StaticPluginMetadata]:
        results = []
        for pdir in self.plugins_dirs:
            if not pdir.exists() or not pdir.is_dir():
                continue
            for item in sorted(pdir.iterdir()):
                if item.name.startswith((".", "_")):
                    continue
                meta: Optional[StaticPluginMetadata] = None
                if item.is_dir() and (
                    (item / "main.py").exists() or (item / "__init__.py").exists()
                ):
                    meta = self.scan_plugin(item)
                elif item.is_file() and item.suffix == ".py":
                    meta = self.scan_plugin(item)
                if meta:
                    self._cache[meta.name] = meta
                    results.append(meta)
        return results
