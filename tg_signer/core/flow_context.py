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

        # 5. 等值/不等值比较
        if " != " in expr:
            parts = expr.split(" != ", 1)
            raw_v1 = self._resolve_path(scope, parts[0].strip())
            v2_str = parts[1].strip().strip("'\"")
            if v2_str.lower() in ("true", "false") and isinstance(raw_v1, bool):
                return raw_v1 != (v2_str.lower() == "true")
            v1 = "" if raw_v1 is None else str(raw_v1)
            return v1 != v2_str
        elif " == " in expr:
            parts = expr.split(" == ", 1)
            raw_v1 = self._resolve_path(scope, parts[0].strip())
            v2_str = parts[1].strip().strip("'\"")
            if v2_str.lower() in ("true", "false") and isinstance(raw_v1, bool):
                return raw_v1 == (v2_str.lower() == "true")
            v1 = "" if raw_v1 is None else str(raw_v1)
            return v1 == v2_str

        # 6. 单一变量真值判断或取反
        if expr.startswith("!"):
            target_path = expr[1:].strip()
            return not bool(self._resolve_path(scope, target_path))
        if expr.startswith("not "):
            target_path = expr[4:].strip()
            return not bool(self._resolve_path(scope, target_path))
        if " " not in expr:
            return bool(self._resolve_path(scope, expr))

        return True

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
