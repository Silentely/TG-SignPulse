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

    def to_dict(self) -> Dict[str, Any]:
        """将上下文完整状态序列化为字典，支持断点备份与还原"""
        return {
            "system": dict(self.system),
            "account": dict(self.account),
            "vars": dict(self.vars),
            "last_output": self.last_output,
            "step_outcomes": {
                nid: so.to_dict() for nid, so in self.step_outcomes.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScopedFlowContext:
        """从字典无损还原上下文状态"""
        ctx = cls(
            system=dict(data.get("system", {})),
            account=dict(data.get("account", {})),
        )
        ctx.vars = dict(data.get("vars", {}))
        ctx.last_output = data.get("last_output", "")
        raw_outcomes = data.get("step_outcomes", {})
        for nid, o_dict in raw_outcomes.items():
            if isinstance(o_dict, StepOutcome):
                ctx.step_outcomes[nid] = o_dict
            elif isinstance(o_dict, dict):
                ctx.step_outcomes[nid] = StepOutcome.from_dict(o_dict)
        return ctx

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

    def _eval_operand(self, scope: Dict[str, Any], text: str) -> Any:
        """安全解析操作数：支持带引号字符串、布尔/空值、数值、或变量路径解析。"""
        text = text.strip()
        if not text:
            return ""
        # 1. 引号包裹的字符串字面量
        if (text.startswith("'") and text.endswith("'")) or (
            text.startswith('"') and text.endswith('"')
        ):
            return text[1:-1]
        # 2. 布尔与空值字面量
        low = text.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low in ("none", "null"):
            return None
        # 3. 整型或浮点数字面量
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            try:
                return int(text)
            except ValueError:
                pass
        try:
            return float(text)
        except ValueError:
            pass
        # 4. 尝试变量路径解析
        resolved = self._resolve_path(scope, text)
        if resolved is not None:
            return resolved
        return text

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

        # 1. 成员包含关系判定
        if " not in " in expr:
            parts = expr.split(" not in ", 1)
            target = self._eval_operand(scope, parts[0])
            src = self._eval_operand(scope, parts[1])
            if isinstance(src, (list, tuple, set)):
                return target not in src
            return str(target) not in str(src)
        elif " in " in expr:
            parts = expr.split(" in ", 1)
            target = self._eval_operand(scope, parts[0])
            src = self._eval_operand(scope, parts[1])
            if isinstance(src, (list, tuple, set)):
                return target in src
            return str(target) in str(src)

        # 2. 文本包含关系判定
        if " not contains " in expr:
            parts = expr.split(" not contains ", 1)
            src = self._eval_operand(scope, parts[0])
            target = self._eval_operand(scope, parts[1])
            if isinstance(src, (list, tuple, set)):
                return target not in src
            return str(target) not in str(src)
        elif " contains " in expr:
            parts = expr.split(" contains ", 1)
            src = self._eval_operand(scope, parts[0])
            target = self._eval_operand(scope, parts[1])
            if isinstance(src, (list, tuple, set)):
                return target in src
            return str(target) in str(src)

        # 3. 正则匹配
        if " matches " in expr:
            parts = expr.split(" matches ", 1)
            src_val = str(self._eval_operand(scope, parts[0]) or "")
            pattern = str(self._eval_operand(scope, parts[1]) or "")
            try:
                return bool(re.search(pattern, src_val))
            except re.error:
                return False

        # 4. 数值大小比较（优先检测复合比较符号）
        if " >= " in expr:
            parts = expr.split(" >= ", 1)
            v1 = self._eval_operand(scope, parts[0])
            v2 = self._eval_operand(scope, parts[1])
            try:
                return float(v1) >= float(v2)
            except (ValueError, TypeError):
                return False
        elif " <= " in expr:
            parts = expr.split(" <= ", 1)
            v1 = self._eval_operand(scope, parts[0])
            v2 = self._eval_operand(scope, parts[1])
            try:
                return float(v1) <= float(v2)
            except (ValueError, TypeError):
                return False
        elif " > " in expr:
            parts = expr.split(" > ", 1)
            v1 = self._eval_operand(scope, parts[0])
            v2 = self._eval_operand(scope, parts[1])
            try:
                return float(v1) > float(v2)
            except (ValueError, TypeError):
                return False
        elif " < " in expr:
            parts = expr.split(" < ", 1)
            v1 = self._eval_operand(scope, parts[0])
            v2 = self._eval_operand(scope, parts[1])
            try:
                return float(v1) < float(v2)
            except (ValueError, TypeError):
                return False

        # 5. 相等性判定
        if " == " in expr:
            parts = expr.split(" == ", 1)
            v1 = self._eval_operand(scope, parts[0])
            v2 = self._eval_operand(scope, parts[1])
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                return v1 == v2
            if isinstance(v1, bool) or isinstance(v2, bool):
                return bool(v1) is bool(v2)
            return str(v1) == str(v2)

        if " != " in expr:
            parts = expr.split(" != ", 1)
            v1 = self._eval_operand(scope, parts[0])
            v2 = self._eval_operand(scope, parts[1])
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                return v1 != v2
            if isinstance(v1, bool) or isinstance(v2, bool):
                return bool(v1) is not bool(v2)
            return str(v1) != str(v2)

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
