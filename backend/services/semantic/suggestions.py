from __future__ import annotations

import copy
import re
from typing import Any

ALLOWED_PATCH_LEAVES = {
    "success_text": ("reply_success_patterns", "success_patterns"),
    "button_label": ("text",),
    "monitor_intent": ("intent",),
}

ALL_ALLOWED_LEAF_NAMES = {
    leaf for leaves in ALLOWED_PATCH_LEAVES.values() for leaf in leaves
}


def build_literal_patch(
    *,
    kind: str,
    path: str,
    old_value: Any,
    observed_value: str,
    reviewer_intent: str | None = None,
) -> dict[str, Any]:
    """生成严格受限且无自由生成的字面补丁 (RFC 6901 JSON Patch)"""
    allowed_leaves = ALLOWED_PATCH_LEAVES.get(kind)
    if not allowed_leaves:
        raise ValueError(f"SEMANTIC_PATCH_UNSUPPORTED: 未知补丁类型 '{kind}'")

    leaf_name = path.rstrip("/").split("/")[-1]
    if leaf_name not in allowed_leaves:
        raise ValueError(
            f"SEMANTIC_PATCH_UNSUPPORTED: 路径 '{path}' 不允许被 '{kind}' 补丁修改"
        )

    # 严禁修改根配置、调度、密钥或账号字段
    forbidden_prefixes = (
        "/sign_at",
        "/random_seconds",
        "/sign_interval",
        "/account",
        "/session",
    )
    if any(path.startswith(prefix) for prefix in forbidden_prefixes):
        raise ValueError(
            f"SEMANTIC_PATCH_UNSUPPORTED: 禁止修改受保护的系统路径 '{path}'"
        )

    if kind == "success_text":
        new_val = list(old_value) if isinstance(old_value, list) else []
        literal = re.escape(observed_value.strip())
        if literal not in new_val:
            new_val.append(literal)
        return {
            "op": "replace",
            "path": path,
            "old": old_value,
            "value": new_val,
        }
    elif kind == "button_label":
        val = observed_value.strip()
        if not val:
            raise ValueError("SEMANTIC_PATCH_UNSUPPORTED: 按钮文本不可为空")
        return {
            "op": "replace",
            "path": path,
            "old": old_value,
            "value": val,
        }
    elif kind == "monitor_intent":
        if not reviewer_intent or not reviewer_intent.strip():
            raise ValueError(
                "REVIEWER_INTENT_REQUIRED: 监听意图改写必须由审核人明确指定"
            )
        return {
            "op": "replace",
            "path": path,
            "old": old_value,
            "value": reviewer_intent.strip(),
        }
    else:
        raise ValueError("SEMANTIC_PATCH_UNSUPPORTED")


def locate_rule(
    config: dict[str, Any],
    *,
    chat_id: int,
    thread_id: int | None = None,
    node_id: str,
    leaf: str = "text",
) -> str:
    """在任务配置中定位目标节点，生成不可变 JSON Pointer 路径"""
    chats = config.get("chats", [])
    target_c_idx = None
    target_chat = None

    for c_idx, chat in enumerate(chats):
        if str(chat.get("chat_id")) == str(chat_id):
            if thread_id is not None:
                if str(chat.get("message_thread_id")) == str(thread_id):
                    target_c_idx = c_idx
                    target_chat = chat
                    break
            else:
                target_c_idx = c_idx
                target_chat = chat
                break

    if target_c_idx is None or target_chat is None:
        raise ValueError(f"LOCATOR_NOT_FOUND: 未找到 chat_id={chat_id} 的目标会话")

    # 尝试在 actions 中定位
    actions = target_chat.get("actions") or []
    steps = target_chat.get("steps") or []

    # 解析 node_id 索引（如 step_1 -> index 1）
    idx = None
    if node_id.startswith("step_") and node_id[5:].isdigit():
        idx = int(node_id[5:])
    elif node_id.isdigit():
        idx = int(node_id)
    elif node_id.startswith("act_") and node_id[4:].isdigit():
        idx = int(node_id[4:])

    if idx is not None:
        if actions and 0 <= idx < len(actions):
            return f"/chats/{target_c_idx}/actions/{idx}/{leaf}"
        if steps and 0 <= idx < len(steps):
            return f"/chats/{target_c_idx}/steps/{idx}/{leaf}"

    raise ValueError(
        f"LOCATOR_NOT_FOUND: 无法在 chat[{target_c_idx}] 中定位 node_id={node_id}"
    )


def apply_checked_patch(
    config: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    """在保护边界内核验并安全应用单个 RFC 6901 补丁"""
    path = str(patch.get("path") or "").strip()
    if not path.startswith("/"):
        raise ValueError("SEMANTIC_PATCH_UNSUPPORTED: 路径必须为绝对 JSON Pointer")

    # 越权路径防护：严禁越出 /chats/
    forbidden_prefixes = (
        "/sign_at",
        "/random_seconds",
        "/sign_interval",
        "/account",
        "/session",
        "/credentials",
    )
    if any(
        path.startswith(prefix) for prefix in forbidden_prefixes
    ) or not path.startswith("/chats/"):
        raise ValueError(f"SEMANTIC_PATCH_UNSUPPORTED: 路径 '{path}' 超出允许修改范围")

    tokens = [
        t.replace("~1", "/").replace("~0", "~") for t in path.strip("/").split("/")
    ]
    if len(tokens) < 3:
        raise ValueError(f"SEMANTIC_PATCH_UNSUPPORTED: 路径深度不足 '{path}'")

    leaf_name = tokens[-1]
    if leaf_name not in ALL_ALLOWED_LEAF_NAMES:
        raise ValueError(
            f"SEMANTIC_PATCH_UNSUPPORTED: 叶子字段 '{leaf_name}' 不允许被修改"
        )

    op = patch.get("op", "replace")
    if op not in ("replace", "add"):
        raise ValueError(f"SEMANTIC_PATCH_UNSUPPORTED: 不支持的补丁操作 '{op}'")

    if "value" not in patch:
        raise ValueError("SEMANTIC_PATCH_UNSUPPORTED: 补丁缺少 value 字段")

    target = copy.deepcopy(config)
    curr: Any = target

    # 导航至叶子节点的父级
    for token in tokens[:-1]:
        if isinstance(curr, list):
            if not token.isdigit():
                raise ValueError(
                    f"PATCH_TARGET_NOT_FOUND: 预期数字列表索引，得到 '{token}'"
                )
            idx = int(token)
            if idx < 0 or idx >= len(curr):
                raise ValueError(f"PATCH_TARGET_NOT_FOUND: 列表索引越界 '{token}'")
            curr = curr[idx]
        elif isinstance(curr, dict):
            if token not in curr:
                raise ValueError(f"PATCH_TARGET_NOT_FOUND: 键不存在 '{token}'")
            curr = curr[token]
        else:
            raise ValueError(
                f"PATCH_TARGET_NOT_FOUND: 无法在非容器节点继续导航 '{token}'"
            )

    # 执行最终修改
    if isinstance(curr, dict):
        curr[leaf_name] = patch["value"]
    elif isinstance(curr, list):
        if leaf_name.isdigit():
            idx = int(leaf_name)
            if 0 <= idx < len(curr) and op == "replace":
                curr[idx] = patch["value"]
            else:
                raise ValueError(
                    f"PATCH_TARGET_NOT_FOUND: 列表替换索引越界 '{leaf_name}'"
                )
        elif leaf_name == "-" and op == "add":
            curr.append(patch["value"])
        else:
            raise ValueError(f"PATCH_TARGET_NOT_FOUND: 非法列表叶子操作 '{leaf_name}'")
    else:
        raise ValueError("PATCH_TARGET_NOT_FOUND: 父级不是有效容器")

    return target
