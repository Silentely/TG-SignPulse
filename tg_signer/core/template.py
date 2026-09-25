from __future__ import annotations

import ast
import datetime
import random
import re
import uuid
from typing import Any, Dict, Optional

# 匹配 {{ expression }}
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*(.*?)\s*\}\}")

# 匹配 {dict:name} 或 {dict:name:round_robin}
_DICT_MACRO_PATTERN = re.compile(r"\{dict:([a-zA-Z0-9_-]+)(?::(random|round_robin))?\}")


def _render_dict_macros(template_str: str) -> str:
    """解析并替换字符串中的 {dict:name} 与 {dict:name:round_robin} 动态词条宏。"""
    if not isinstance(template_str, str) or "{dict:" not in template_str:
        return template_str

    def _replace_dict_macro(match: re.Match) -> str:
        name = match.group(1)
        mode = match.group(2) or "random"
        try:
            from backend.services.data_dict import get_data_dict_service

            svc = get_data_dict_service()
            return svc.get_entry(name, mode=mode)
        except Exception:
            return match.group(0)

    return _DICT_MACRO_PATTERN.sub(_replace_dict_macro, template_str)


class _SafeEvaluator(ast.NodeVisitor):
    """基于 AST 的安全表达式求值器，杜绝代码注入与属性逃逸。"""

    ALLOWED_NODE_TYPES = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Attribute,
        ast.Subscript,
        ast.Call,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Starred,
    )

    def __init__(self, context: Dict[str, Any]):
        self.context = context

    def evaluate(self, expr_str: str) -> Any:
        expr_str = expr_str.strip()
        if not expr_str:
            return ""
        parsed = ast.parse(expr_str, mode="eval")
        return self.visit(parsed)

    def generic_visit(self, node: ast.AST) -> Any:
        if not isinstance(node, self.ALLOWED_NODE_TYPES):
            raise ValueError(f"安全限制：不支持的表达式节点类型 {type(node).__name__}")
        return super().generic_visit(node)

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id.startswith("__"):
            raise ValueError(f"安全限制：禁止访问私有变量 {node.id}")
        if node.id in self.context:
            return self.context[node.id]
        raise NameError(f"未定义的模板变量: '{node.id}'")

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        attr_lower = node.attr.lower()
        if (
            node.attr.startswith("__")
            or attr_lower in (
                "format",
                "format_map",
                "__globals__",
                "__code__",
                "__closure__",
                "__func__",
                "__self__",
                "__subclasses__",
                "__bases__",
                "__mro__",
                "gi_frame",
                "cr_frame",
                "f_locals",
                "f_globals",
                "f_builtins",
            )
        ):
            raise ValueError(f"安全限制：禁止访问受保护属性或格式化方法 {node.attr}")
        obj = self.visit(node.value)
        if obj is None:
            return ""
        if isinstance(obj, dict):
            return obj.get(node.attr, "")
        if hasattr(obj, node.attr):
            attr_val = getattr(obj, node.attr)
            # 禁止调用危险的内置方法或模块属性
            if hasattr(attr_val, "__self__") and isinstance(
                attr_val.__self__, (type, type(object))
            ):
                raise ValueError(f"安全限制：禁止访问类型方法 {node.attr}")
            return attr_val
        return ""

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        obj = self.visit(node.value)
        # 针对 Python 3.8 的 ast.Index 兼容
        if hasattr(ast, "Index") and isinstance(node.slice, ast.Index):  # type: ignore[attr-defined]
            key = self.visit(node.slice.value)  # type: ignore[attr-defined]
        else:
            key = self.visit(node.slice)

        if obj is None:
            return ""
        try:
            return obj[key]
        except (KeyError, IndexError, TypeError):
            # 支持数字字符串作为 dict 键的灵活匹配
            if isinstance(obj, dict) and str(key) in obj:
                return obj[str(key)]
            return ""

    def visit_Starred(self, node: ast.Starred) -> Any:
        return self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> Any:
        func = self.visit(node.func)
        if not callable(func):
            raise TypeError(f"\x27{func}\x27 不是可调用对象")
        args = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                unpacked = self.visit(arg.value)
                if isinstance(unpacked, (list, tuple, set)):
                    args.extend(unpacked)
                else:
                    args.append(unpacked)
            else:
                args.append(self.visit(arg))
        kwargs = {}
        for kw in node.keywords:
            if kw.arg is None:
                unpacked = self.visit(kw.value)
                if isinstance(unpacked, dict):
                    kwargs.update(unpacked)
            else:
                kwargs[kw.arg] = self.visit(kw.value)
        return func(*args, **kwargs)

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        elif isinstance(node.op, ast.Sub):
            return left - right
        elif isinstance(node.op, ast.Mult):
            return left * right
        elif isinstance(node.op, ast.Div):
            return left / right
        elif isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError(f"不支持的运算符 {type(node.op).__name__}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        elif isinstance(node.op, ast.UAdd):
            return +operand
        raise ValueError(f"不支持的一元运算符 {type(node.op).__name__}")

    def visit_List(self, node: ast.List) -> Any:
        res = []
        for elt in node.elts:
            if isinstance(elt, ast.Starred):
                unpacked = self.visit(elt.value)
                if isinstance(unpacked, (list, tuple, set)):
                    res.extend(unpacked)
                else:
                    res.append(unpacked)
            else:
                res.append(self.visit(elt))
        return res

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        res = []
        for elt in node.elts:
            if isinstance(elt, ast.Starred):
                unpacked = self.visit(elt.value)
                if isinstance(unpacked, (list, tuple, set)):
                    res.extend(unpacked)
                else:
                    res.append(unpacked)
            else:
                res.append(self.visit(elt))
        return tuple(res)

    def visit_Dict(self, node: ast.Dict) -> Any:
        res = {}
        for k, v in zip(node.keys, node.values, strict=True):
            if k is None:
                unpacked = self.visit(v)
                if isinstance(unpacked, dict):
                    res.update(unpacked)
            else:
                res[self.visit(k)] = self.visit(v)
        return res


def _build_default_template_context(
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建默认的安全上下文函数与变量。"""
    now = datetime.datetime.now()
    utcnow = datetime.datetime.now(datetime.timezone.utc)

    def _random_int(a: int, b: int) -> int:
        return random.randint(int(a), int(b))

    def _random_choice(*choices: Any) -> Any:
        if not choices:
            return ""
        if len(choices) == 1 and isinstance(choices[0], (list, tuple)):
            choices = choices[0]
        return random.choice(choices)

    def _gen_uuid(short: bool = True) -> str:
        uid = str(uuid.uuid4())
        return uid.replace("-", "")[:8] if short else uid

    def _dict_entry(name: str, mode: str = "random") -> str:
        try:
            from backend.services.data_dict import get_data_dict_service

            svc = get_data_dict_service()
            return svc.get_entry(name, mode=mode)
        except Exception:
            return ""

    ctx: Dict[str, Any] = {
        "now": now,
        "utcnow": utcnow,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timestamp": int(now.timestamp()),
        "random_int": _random_int,
        "random_choice": _random_choice,
        "uuid": _gen_uuid,
        "dict_entry": _dict_entry,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "len": len,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
    }
    if extra_context:
        ctx.update(extra_context)
    return ctx


def render_template(
    template_str: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """对字符串中的 {{ expression }} 以及 {dict:...} 宏进行安全渲染。

    先计算 {{ expression }} 表达式，再替换 {dict:...} 词条宏，
    杜绝词条内容中包含的 {{ ... }} 发生二次求值注入。
    """
    if not isinstance(template_str, str):
        return template_str

    result_str = template_str
    if "{{" in result_str:
        full_context = _build_default_template_context(context)
        evaluator = _SafeEvaluator(full_context)

        def _replace_match(match: re.Match) -> str:
            raw_expr = match.group(1).strip()
            try:
                val = evaluator.evaluate(raw_expr)
                return "" if val is None else str(val)
            except Exception:
                return match.group(0)

        result_str = _TEMPLATE_PATTERN.sub(_replace_match, result_str)

    result_str = _render_dict_macros(result_str)
    return result_str


def render_template_recursive(
    data: Any,
    context: Optional[Dict[str, Any]] = None,
) -> Any:
    """递归渲染字典、列表或字符串中的模板宏变量。"""
    if isinstance(data, str):
        return render_template(data, context)
    elif isinstance(data, dict):
        return {
            k: render_template_recursive(v, context)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [render_template_recursive(item, context) for item in data]
    elif isinstance(data, tuple):
        return tuple(render_template_recursive(item, context) for item in data)
    return data
