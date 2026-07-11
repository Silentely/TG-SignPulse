"""
AI 服务 Mock 对象

提供 MockAITools 和模拟 OpenAI 客户端，用于测试 AI 图片识别、
计算题解答、选项选择等功能，而无需真实调用大模型 API。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple


class MockCompletionChoice:
    """模拟 OpenAI ChatCompletion 的 choice 对象"""

    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class MockCompletionResponse:
    """模拟 OpenAI ChatCompletion 响应"""

    def __init__(self, content: str):
        self.choices = [MockCompletionChoice(content=content)]
        self.usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )


class MockCompletions:
    """模拟 OpenAI chat.completions 接口"""

    def __init__(self, responses: Optional[List[Any]] = None):
        self.responses = list(responses or [])
        self.calls: List[Dict[str, Any]] = []
        self._default_response = MockCompletionResponse(
            content='{"options": [1]}'
        )

    def configure_responses(self, responses: List[Any]):
        """配置响应序列"""
        self.responses = list(responses)

    def set_default_response(self, content: str):
        """设置默认响应内容"""
        self._default_response = MockCompletionResponse(content=content)

    async def create(self, **kwargs) -> MockCompletionResponse:
        """模拟 completions.create 调用"""
        self.calls.append(kwargs)
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return self._default_response


class MockOpenAIClient:
    """模拟 OpenAI 异步客户端"""

    def __init__(self, responses: Optional[List[Any]] = None):
        self.completions = MockCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


class MockAITools:
    """
    模拟 AITools 实例

    封装常用的 AI 工具方法，返回预配置的结果，
    用于测试包含 AI 调用的签到流程。
    """

    def __init__(self, config: Optional[Dict[str, str]] = None):
        self.config = config or {"api_key": "test-key", "model": "gpt-4o"}
        self.client = MockOpenAIClient()

        # 可配置的返回值
        self._choose_option_result: List[int] = [1]
        self._calculate_result: str = "42"
        self._extract_text_result: str = "extracted text"
        self._choose_options_by_image_result: List[int] = [1]

        # 调用记录
        self.choose_option_calls: List[Dict[str, Any]] = []
        self.calculate_calls: List[Dict[str, Any]] = []
        self.extract_text_calls: List[Dict[str, Any]] = []
        self.choose_options_calls: List[Dict[str, Any]] = []

    def configure_choose_option(self, result: List[int]):
        """配置 choose_option_by_image 返回值"""
        self._choose_option_result = result

    def configure_calculate(self, result: str):
        """配置 calculate_problem 返回值"""
        self._calculate_result = result

    def configure_extract_text(self, result: str):
        """配置 extract_text_by_image 返回值"""
        self._extract_text_result = result

    def configure_choose_options(self, result: List[int]):
        """配置 choose_options_by_image 返回值"""
        self._choose_options_by_image_result = result

    async def choose_option_by_image(
        self,
        image: bytes,
        query: str,
        options: List[Tuple[int, str]],
        ai_prompt: Optional[str] = None,
    ) -> int:
        """模拟图片选项选择"""
        self.choose_option_calls.append({
            "image_size": len(image),
            "query": query,
            "options": options,
            "ai_prompt": ai_prompt,
        })
        result = self._choose_option_result[0] if self._choose_option_result else 1
        return result

    async def choose_options_by_image(
        self,
        image: bytes,
        query: str,
        options: List[Tuple[int, str]],
        ai_prompt: Optional[str] = None,
    ) -> List[int]:
        """模拟图片多选项选择"""
        self.choose_options_calls.append({
            "image_size": len(image),
            "query": query,
            "options": options,
            "ai_prompt": ai_prompt,
        })
        return self._choose_options_by_image_result

    async def reply_calculation_problem(
        self,
        text: str,
        ai_prompt: Optional[str] = None,
    ) -> str:
        """模拟计算题解答"""
        self.calculate_calls.append({
            "text": text,
            "ai_prompt": ai_prompt,
        })
        return self._calculate_result

    async def extract_text_by_image(
        self,
        image: bytes,
        ai_prompt: Optional[str] = None,
    ) -> str:
        """模拟图片文字提取"""
        self.extract_text_calls.append({
            "image_size": len(image),
            "ai_prompt": ai_prompt,
        })
        return self._extract_text_result

    async def calculate_and_click(
        self,
        text: str,
        options: List[Tuple[int, str]],
        ai_prompt: Optional[str] = None,
    ) -> int:
        """模拟计算后选择按钮"""
        self.calculate_calls.append({
            "text": text,
            "options": options,
            "ai_prompt": ai_prompt,
        })
        return self._choose_option_result[0] if self._choose_option_result else 1
