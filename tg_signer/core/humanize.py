from __future__ import annotations

import asyncio
import logging
import random
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger("tg_signer.humanize")


def is_cjk(char: str) -> bool:
    """判断字符是否属于 CJK 统一表意文字或日文假名（平假名/片假名）。"""
    if not isinstance(char, str) or len(char) != 1:
        return False
    try:
        name = unicodedata.name(char, "")
    except ValueError:
        return False
    return "CJK UNIFIED IDEOGRAPH" in name or "HIRAGANA" in name or "KATAKANA" in name


def calculate_typing_delay(text: str) -> float:
    """根据文本长度及字符类型（CJK 与非 CJK）计算拟人化打字耗时。

    - CJK CPM 范围：100.0 ~ 140.0 字符/分钟
    - Latin/其他 CPM 范围：240.0 ~ 320.0 字符/分钟
    - 高斯扰动：random.gauss(0, 0.35)
    - 边界限制：min_delay = 1.2s, max_delay = 8.0s
    """
    if not text:
        return 1.2

    cjk_count = sum(1 for c in text if is_cjk(c))
    other_count = len(text) - cjk_count

    cjk_cpm = random.uniform(100.0, 140.0)
    other_cpm = random.uniform(240.0, 320.0)

    expected_sec = (cjk_count / cjk_cpm * 60.0) + (other_count / other_cpm * 60.0)
    jitter = random.gauss(0, 0.35)
    total = expected_sec + jitter
    return max(1.2, min(8.0, total))


@asynccontextmanager
async def simulate_typing_action(
    client: Any, chat_id: Any, text: str, max_presend_delay: float = 2.0
) -> AsyncIterator[float]:
    """异步上下文管理器：在发送消息前模拟拟人打字行为及 periodic typing 状态心跳。

    在打字期间定期（每 4 秒）向目标会话发送 'typing' 聊天动作，并在退出上下文后干净取消后台心跳任务。
    若 client 不可用或 send_chat_action 抛出异常，支持优雅降级不阻断主流程。

    为避免超长文本把发送延迟拉到 8 秒，进入上下文时的等待被限制在 max_presend_delay 以内；
    `as` 拿到的返回值是**实际等待**的秒数（不再是未经限制的理论时长），调用方据此判断更可靠。
    文本越长，超出的拟人时长由心跳在消息发送前后继续覆盖。
    """
    duration = calculate_typing_delay(text)
    presend_delay = min(duration, max(0.0, max_presend_delay))
    stop_event = asyncio.Event()

    async def _keep_typing() -> None:
        try:
            while not stop_event.is_set():
                if client is not None:
                    send_fn = getattr(client, "send_chat_action", None)
                    if callable(send_fn):
                        try:
                            res = send_fn(chat_id, "typing")
                            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                                await res
                        except Exception as e:
                            logger.debug("发送 typing action 异常: %s", e)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=4.0)
                except (asyncio.TimeoutError, TimeoutError):
                    pass
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_keep_typing())
    try:
        await asyncio.sleep(presend_delay)
        yield presend_delay
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # 心跳任务内部已吞掉自身取消；此处若仍收到 CancelledError，
            # 说明是外层任务被取消，必须原样向上传播，不能吞掉取消信号。
            raise
        except Exception as e:
            logger.debug("typing 心跳任务异常退出: %s", e)
