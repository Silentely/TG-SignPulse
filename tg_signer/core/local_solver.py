from __future__ import annotations

import ast
import logging
import re
from typing import Optional

logger = logging.getLogger("tg_signer.local_solver")

_CANDIDATE_REGEX = re.compile(
    r"(?<![\d\-])(\d{1,8})\s*([\+\-\*\/\u00d7\u00f7])\s*(\d{1,8})(?![\d\-])"
)


class ArithmeticFastSolver:
    MAX_EXPR_LEN = 32
    MAX_RESULT = 10**8

    @classmethod
    def solve(cls, text: str) -> Optional[int]:
        if not text:
            return None

        match = _CANDIDATE_REGEX.search(text)
        if not match:
            return None

        left, op, right = match.groups()
        if op == "\u00d7":
            op = "*"
        elif op in ("\u00f7", "/"):
            op = "//"

        expr = f"{left} {op} {right}".strip()
        if len(expr) > cls.MAX_EXPR_LEN:
            return None

        try:
            tree = ast.parse(expr, mode="eval")
        except Exception:
            return None

        for node in ast.walk(tree):
            if isinstance(node, ast.Expression):
                continue
            # 允许运算符节点 (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv 等)
            if isinstance(node, (ast.operator, ast.unaryop)):
                continue
            if isinstance(node, ast.Constant):
                # 严防 bool 穿透：Python 中 isinstance(True, int) 为真！
                if type(node.value) is not int:
                    return None
                continue
            if isinstance(node, ast.BinOp):
                if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)):
                    return None
                continue
            if isinstance(node, ast.UnaryOp):
                if not isinstance(node.op, ast.USub):
                    return None
                continue
            # 其他任何未知或危险节点一律拒绝
            return None

        try:
            code = compile(tree, "<local_solver>", "eval")
            res = eval(code, {"__builtins__": {}}, {})  # nosec
            if type(res) is int and abs(res) <= cls.MAX_RESULT:
                return res
        except ZeroDivisionError:
            return None
        except Exception as e:
            logger.debug("本地算术解析失败: %s", e)
            return None
        return None
