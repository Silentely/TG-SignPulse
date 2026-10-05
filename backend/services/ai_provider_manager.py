from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("backend.ai_provider_manager")


class AIAllProvidersFailedError(Exception):
    """所有可用 AI 节点均失败或预算耗尽"""


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
                raise ValueError(f"HTTP {resp.status_code} Unauthorized: {resp.text}")
            if resp.status_code == 404:
                raise ValueError(f"HTTP 404 Model Not Found: {resp.text}")
            resp.raise_for_status()
            return resp.json()

    async def dispatch_request(
        self, payload: Dict[str, Any], providers: List[ProviderConfig]
    ) -> Dict[str, Any]:
        start_time = time.monotonic()
        errors = []

        for provider in providers:
            elapsed = time.monotonic() - start_time
            remaining_time = self.total_deadline - elapsed
            if remaining_time <= 0.2:
                logger.warning(
                    "AI 请求剩余全局预算耗尽 (%.2fs)，终止故障转移", remaining_time
                )
                break

            sub_budget = min(provider.timeout, max(0.5, remaining_time - 0.2))
            logger.info(
                "正在尝试 AI 节点 %s (子预算 %.1fs, 剩余 %.1fs)",
                provider.id,
                sub_budget,
                remaining_time,
            )

            try:
                result = await asyncio.wait_for(
                    self._call_single_provider(provider, payload, timeout=sub_budget),
                    timeout=sub_budget,
                )
                return result
            except (TimeoutError, asyncio.TimeoutError) as e:
                logger.warning("AI 节点 %s 响应超时: %s", provider.id, e)
                errors.append(f"{provider.id}: timeout")
            except ValueError as e:
                logger.error("AI 节点 %s 配置异常，中断容灾: %s", provider.id, e)
                raise
            except Exception as e:
                logger.warning(
                    "AI 节点 %s 临时服务故障，进入下一候选: %s", provider.id, e
                )
                errors.append(f"{provider.id}: {str(e)}")

        raise AIAllProvidersFailedError(
            f"全部 AI 提供方均调用失败: {'; '.join(errors)}"
        )
