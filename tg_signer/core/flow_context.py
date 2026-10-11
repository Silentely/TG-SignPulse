# tg_signer/core/flow_context.py
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from tg_signer.core.flow_models import StepOutcome
from tg_signer.core.template import render_template


class ScopedFlowContext:
    """四级作用域上下文管理器：system -> account -> vars -> steps"""

    def __init__(
        self,
        system: Optional[Dict[str, Any]] = None,
        account: Optional[Dict[str, Any]] = None,
    ):
        self.system = system or {}
        self.account = account or {}
        self.vars: Dict[str, Any] = {}
        self.step_outcomes: Dict[str, StepOutcome] = {}
        self.last_output: str = ""

    def set_var(self, key: str, value: Any) -> None:
        self.vars[key] = value

    def get_var(self, key: str, default: Any = None) -> Any:
        return self.vars.get(key, default)

    def has_var(self, key: str) -> bool:
        return key in self.vars

    def get(self, path: str, default: Any = None) -> Any:
        """支持点号路径安全读取任意作用域变量（如 vars.token、account.name 等）"""
        scope = self.build_scope_dict()
        val = self._resolve_path(scope, path)
        return val if val is not None else default

    def record_step_outcome(self, outcome: StepOutcome) -> None:
        self.step_outcomes[outcome.node_id] = outcome
        if outcome.output_text and outcome.updates_last_output:
            self.last_output = outcome.output_text
        if outcome.extracted_vars:
            self.vars.update(outcome.extracted_vars)

    def build_scope_dict(self, default_output: str = "") -> Dict[str, Any]:
        prev_out = self.last_output or default_output
        steps_dict: Dict[Any, Any] = {}
        for sid, sc in self.step_outcomes.items():
            s_data = {"output": sc.output_text, "status": sc.status.value}
            s_data.update(sc.extracted_vars)
            steps_dict[sid] = s_data

        # 增加 1-based 数字索引别名，使 steps.1 与 step.1 保持一致性
        for index, sid in enumerate(self.step_outcomes, start=1):
            s_data = steps_dict.get(sid)
            if s_data is not None:
                steps_dict.setdefault(str(index), s_data)
                steps_dict.setdefault(index, s_data)

        return {
            "system": self.system,
            "account": self.account,
            "vars": self.vars,
            "steps": steps_dict,
            "step": steps_dict,
            "prev": {"output": prev_out},
            "last_output": prev_out,
        }

    def render(self, template_str: str) -> str:
        if not template_str:
            return ""
        return render_template(template_str, self.build_scope_dict())

    def eval_condition(self, expr: str, default_output: str = "") -> bool:
        if not expr:
            return True
        scope = self.build_scope_dict(default_output)
        expr = expr.strip()

        # 0. 复合逻辑或/与判定（支持表达式组合）
        if " or " in expr:
            sub_exprs = expr.split(" or ")
            return any(
                self.eval_condition(sub.strip(), default_output) for sub in sub_exprs
            )
        if " and " in expr:
            sub_exprs = expr.split(" and ")
            return all(
                self.eval_condition(sub.strip(), default_output) for sub in sub_exprs
            )

        # 1. 成员包含关系判定（优先检测非包含）
        if " not in " in expr:
            parts = expr.split(" not in ", 1)
            target = parts[0].strip().strip("'\"")
            src_val = str(self._resolve_path(scope, parts[1].strip()) or "")
            return target not in src_val
        elif " in " in expr:
            parts = expr.split(" in ", 1)
            target = parts[0].strip().strip("'\"")
            src_val = str(self._resolve_path(scope, parts[1].strip()) or "")
            return target in src_val

        # 2. 文本包含关系判定
        if " not contains " in expr:
            parts = expr.split(" not contains ", 1)
            src_val = str(self._resolve_path(scope, parts[0].strip()) or "")
            target = parts[1].strip().strip("'\"")
            return target not in src_val
        elif " contains " in expr:
            parts = expr.split(" contains ", 1)
            src_val = str(self._resolve_path(scope, parts[0].strip()) or "")
            target = parts[1].strip().strip("'\"")
            return target in src_val

        # 3. 正则匹配
        if " matches " in expr:
            parts = expr.split(" matches ", 1)
            src_val = str(self._resolve_path(scope, parts[0].strip()) or "")
            pattern = parts[1].strip().strip("'\"")
            try:
                return bool(re.search(pattern, src_val))
            except re.error:
                return False

        # 4. 数值大小比较（优先检测复合比较符号）
        if " >= " in expr:
            parts = expr.split(" >= ", 1)
            raw_val = self._resolve_path(scope, parts[0].strip())
            if raw_val is None:
                return False
            try:
                return float(raw_val) >= float(parts[1].strip())
            except (ValueError, TypeError):
                return False
        elif " <= " in expr:
            parts = expr.split(" <= ", 1)
            raw_val = self._resolve_path(scope, parts[0].strip())
            if raw_val is None:
                return False
            try:
                return float(raw_val) <= float(parts[1].strip())
            except (ValueError, TypeError):
                return False
        elif " > " in expr:
            parts = expr.split(" > ", 1)
            raw_val = self._resolve_path(scope, parts[0].strip())
            if raw_val is None:
                return False
            try:
                return float(raw_val) > float(parts[1].strip())
            except (ValueError, TypeError):
                return False
        elif " < " in expr:
            parts = expr.split(" < ", 1)
            raw_val = self._resolve_path(scope, parts[0].strip())
            if raw_val is None:
                return False
            try:
                return float(raw_val) < float(parts[1].strip())
            except (ValueError, TypeError):
                return False

        # 5. 相等性判定
        if " == " in expr:
            parts = expr.split(" == ", 1)
            left = self._resolve_path(scope, parts[0].strip())
            right_str = parts[1].strip()
            if right_str.lower() == "true":
                return bool(left is True or str(left).lower() == "true")
            if right_str.lower() == "false":
                return bool(left is False or str(left).lower() == "false")
            if right_str.isdigit():
                return left == int(right_str) or str(left) == right_str
            return str(left) == right_str.strip("'\"")

        if " != " in expr:
            parts = expr.split(" != ", 1)
            left = self._resolve_path(scope, parts[0].strip())
            right_str = parts[1].strip()
            if right_str.lower() == "true":
                return not (left is True or str(left).lower() == "true")
            if right_str.lower() == "false":
                return not (left is False or str(left).lower() == "false")
            if right_str.isdigit():
                return left != int(right_str) and str(left) != right_str
            return str(left) != right_str.strip("'\"")

        # 6. 单一变量真值或取反（如 !vars.disabled, not vars.disabled, vars.enabled）
        if expr.startswith("!"):
            var_path = expr[1:].strip()
            return not bool(self._resolve_path(scope, var_path))
        if expr.startswith("not "):
            var_path = expr[4:].strip()
            return not bool(self._resolve_path(scope, var_path))

        # 7. 单一变量真值直接判定
        if expr:
            return bool(self._resolve_path(scope, expr))

        return True

    # 别名，保持与引擎调用语义一致
    evaluate_condition = eval_condition

    def _resolve_path(self, data: Dict[str, Any], path: str) -> Any:
        tokens = path.split(".")
        cur: Any = data
        for t in tokens:
            if isinstance(cur, dict):
                if t in cur:
                    cur = cur[t]
                elif t.isdigit() and int(t) in cur:
                    cur = cur[int(t)]
                else:
                    return None
            elif isinstance(cur, (list, tuple)) and t.isdigit():
                idx = int(t)
                if 0 <= idx < len(cur):
                    cur = cur[idx]
                else:
                    return None
            else:
                return None
        return cur
