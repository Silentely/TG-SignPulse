"""多节点 AI 调用故障转移引擎（仅依赖 httpx，位于核心包供 CLI 与后端共用）。

同一份逻辑既服务后端的 AI 节点容灾，也服务 CLI 侧的多节点回退；
放在 tg_signer.core 下，避免核心包反向依赖 backend。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("tg_signer.ai_failover")


class AIAllProvidersFailedError(Exception):
    """所有可用 AI 节点均失败或预算耗尽"""


class AIProviderConfigError(ValueError):
    """节点配置类错误（认证失败 / 模型不存在）。

    刻意继承 ValueError：默认的 dispatch_request 对此类错误选择中断容灾，
    因为同一套配置下继续尝试后续节点通常只会重复失败。备用节点场景可通过
    abort_on_config_error=False 改为继续尝试所有候选。
    """


class AIProviderResponseError(Exception):
    """单节点瞬时故障（如 200 但响应体非 JSON）。

    不继承 ValueError，确保 dispatch_request 会降级到下一候选节点，
    而不是被当作配置异常直接中断整条容灾链。
    """


@dataclass
class ProviderConfig:
    id: str
    base_url: str
    api_key: str
    model: str
    timeout: float = 15.0


class AIProviderManager:
    def __init__(self, total_deadline: float = 35.0):
        self.total_deadline = total_deadline

    async def _call_single_provider(
        self, provider: ProviderConfig, payload: Dict[str, Any], timeout: float
    ) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in {401, 403}:
                raise AIProviderConfigError(
                    f"HTTP {resp.status_code} Unauthorized: {resp.text}"
                )
            if resp.status_code == 404:
                raise AIProviderConfigError(f"HTTP 404 Model Not Found: {resp.text}")
            resp.raise_for_status()
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                # 200 但响应体不是 JSON：属于该节点瞬时故障，交由上层故障转移，
                # 不能让 JSONDecodeError（ValueError 子类）误入配置异常分支中断容灾。
                raise AIProviderResponseError(
                    f"HTTP 200 响应体非 JSON: {resp.text[:200]}"
                ) from exc

    async def dispatch_request(
        self,
        payload: Dict[str, Any],
        providers: List[ProviderConfig],
        *,
        abort_on_config_error: bool = True,
    ) -> Dict[str, Any]:
        """按顺序尝试各节点；返回首个成功响应。

        abort_on_config_error=True（默认）：认证/模型等配置类错误立即中断，
        因为同一份配置下后续节点通常同样不可用。
        abort_on_config_error=False：配置类错误也仅记录并继续下一节点，
        适用于"备用节点列表"场景——不该因某个备用节点密钥失效而放弃其余节点。
        """
        start_time = time.monotonic()
        errors: List[str] = []

        if not providers:
            raise AIAllProvidersFailedError("未配置任何 AI 提供方")

        for provider in providers:
            elapsed = time.monotonic() - start_time
            remaining_time = self.total_deadline - elapsed
            if remaining_time <= 0.2:
                logger.warning(
                    "AI 请求剩余全局预算耗尽 (%.2fs)，终止故障转移", remaining_time
                )
                break

            # 子预算必须严格不超过剩余全局预算，避免单个慢节点拖穿总期限
            sub_budget = min(provider.timeout, max(0.1, remaining_time - 0.2))
            logger.info(
                "正在尝试 AI 节点 %s (子预算 %.1fs, 剩余 %.1fs)",
                provider.id,
                sub_budget,
                remaining_time,
            )

            # 让提供方配置的模型名参与请求，避免按节点选模型成为空操作
            call_payload = dict(payload)
            if provider.model:
                call_payload.setdefault("model", provider.model)

            try:
                result = await asyncio.wait_for(
                    self._call_single_provider(
                        provider, call_payload, timeout=sub_budget
                    ),
                    timeout=sub_budget,
                )
                return result
            except (TimeoutError, asyncio.TimeoutError) as e:
                logger.warning("AI 节点 %s 响应超时: %s", provider.id, e)
                errors.append(f"{provider.id}: timeout")
            except AIProviderConfigError as e:
                if abort_on_config_error:
                    logger.error("AI 节点 %s 配置异常，中断容灾: %s", provider.id, e)
                    raise
                logger.warning(
                    "AI 节点 %s 配置异常，跳过并尝试下一节点: %s", provider.id, e
                )
                errors.append(f"{provider.id}: config error")
            except ValueError as e:
                # 兼容直接抛 ValueError 的旧调用方
                if abort_on_config_error:
                    logger.error("AI 节点 %s 配置异常，中断容灾: %s", provider.id, e)
                    raise
                logger.warning("AI 节点 %s 配置异常，跳过: %s", provider.id, e)
                errors.append(f"{provider.id}: config error")
            except Exception as e:
                logger.warning(
                    "AI 节点 %s 临时服务故障，进入下一候选: %s", provider.id, e
                )
                errors.append(f"{provider.id}: {str(e)}")

        raise AIAllProvidersFailedError(
            f"全部 AI 提供方均调用失败: {'; '.join(errors)}"
        )


def as_attribute_object(value: Any) -> Any:
    """把 OpenAI 兼容响应的嵌套 dict 递归转换为属性可访问对象。

    ai_tools 现有代码以 `completion.choices[0].message.content` 的属性形式
    消费响应；原生 httpx 返回的是 dict，这里做一次等价适配，避免改动调用方。
    """
    from types import SimpleNamespace

    if isinstance(value, dict):
        return SimpleNamespace(**{k: as_attribute_object(v) for k, v in value.items()})
    if isinstance(value, list):
        return [as_attribute_object(v) for v in value]
    return value


def build_provider_configs(
    entries: List[Dict[str, Any]],
    *,
    default_model: Optional[str] = None,
    timeout: float = 15.0,
) -> List[ProviderConfig]:
    """把配置字典列表（base_url/api_key/model）转换为 ProviderConfig 列表。"""
    providers: List[ProviderConfig] = []
    for index, entry in enumerate(entries or []):
        api_key = str(entry.get("api_key") or "").strip()
        if not api_key:
            continue
        providers.append(
            ProviderConfig(
                id=str(entry.get("id") or f"provider-{index + 1}"),
                base_url=str(entry.get("base_url") or "").strip(),
                api_key=api_key,
                model=str(entry.get("model") or default_model or "").strip(),
                timeout=timeout,
            )
        )
    return providers
