# tg_signer/core/flow_context.py
from __future__ import annotations

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
        if outcome.output_text:
            self.last_output = outcome.output_text
        if outcome.extracted_vars:
            self.vars.update(outcome.extracted_vars)

    def build_scope_dict(self, default_output: str = "") -> Dict[str, Any]:
        prev_out = self.last_output or default_output
        steps_dict = {}
        for sid, sc in self.step_outcomes.items():
            s_data = {"output": sc.output_text, "status": sc.status.value}
            s_data.update(sc.extracted_vars)
            steps_dict[sid] = s_data

        return {
            "system": self.system,
            "account": self.account,
            "vars": self.vars,
            "steps": steps_dict,
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
        if " in " in expr:
            parts = expr.split(" in ", 1)
            target = parts[0].strip().strip("'\"")
            src_val = str(self._resolve_path(scope, parts[1].strip()) or "")
            return target in src_val
        elif " contains " in expr:
            parts = expr.split(" contains ", 1)
            src_val = str(self._resolve_path(scope, parts[0].strip()) or "")
            target = parts[1].strip().strip("'\"")
            return target in src_val
        elif " > " in expr:
            parts = expr.split(" > ", 1)
            v1 = float(self._resolve_path(scope, parts[0].strip()) or 0)
            v2 = float(parts[1].strip())
            return v1 > v2
        elif " == " in expr:
            parts = expr.split(" == ", 1)
            v1 = str(self._resolve_path(scope, parts[0].strip()))
            v2 = str(parts[1].strip().strip("'\""))
            return v1 == v2
        return True

    def _resolve_path(self, data: Dict[str, Any], path: str) -> Any:
        tokens = path.split(".")
        cur: Any = data
        for t in tokens:
            if isinstance(cur, dict):
                cur = cur.get(t)
            else:
                return None
        return cur
