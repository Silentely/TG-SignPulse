import asyncio
import base64
import io
import json
import logging
import os
import pathlib
import re
import time
from typing import TYPE_CHECKING, Any, Union

import json_repair
from typing_extensions import Optional, Required, TypedDict

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is optional at runtime
    Image = None

if TYPE_CHECKING:
    from openai import AsyncOpenAI  # 在性能弱的机器上导入openai包实在有些慢

from cryptography.fernet import InvalidToken

from tg_signer.log_utils import safe_text_preview
from tg_signer.security import decrypt_secret, encrypt_secret
from tg_signer.utils import UserInput, print_to_user

DEFAULT_MODEL = "gpt-4o"

DEFAULT_CHOOSE_OPTION_BY_IMAGE_PROMPT = (
    "You are a low-latency visual matcher for Telegram sign-in challenges. "
    "Choose exactly one option whose text best matches the main object or "
    "concept shown in the image and the question. Ignore retry warnings, "
    "time-limit reminders, and other unrelated footer text. Return JSON only: "
    '{"option":1}. The option value must be one of the provided indexes, '
    "starting at 1. If JSON mode is unavailable, return only the chosen option "
    "index or option text."
)

DEFAULT_CHOOSE_OPTIONS_BY_IMAGE_PROMPT = (
    "You solve Telegram bot image or text challenges. Read only the actual "
    "question and the button list. Use the image when the question refers to "
    "the picture. Unless the question explicitly asks for multiple clicks or "
    "building a phrase, return exactly one option. Ignore retry warnings, "
    "time-limit reminders, and unrelated footer text. Return JSON only: "
    '{"options":[1]}. '
    "The options field must be a list of option indexes starting at 1. "
    "If only one click is needed, return a one-item list. If JSON mode is "
    "unavailable, return only the chosen option index or option text."
)

DEFAULT_SINGLE_OBJECT_CHOICE_PROMPT = (
    "You are a fast image classifier for a Telegram sign-in button challenge. "
    "The image usually contains one main object on a clean background. Pick "
    "the single button whose text best names that object. Do not explain. "
    'Return JSON only: {"options":[1]}. '
    "The option indexes start at 1. If JSON mode is unavailable, return only "
    "the chosen option index or option text."
)

DEFAULT_EXTRACT_TEXT_BY_IMAGE_PROMPT = (
    "You are an OCR assistant. Extract the most relevant text from the image. "
    "Return plain text only, no markdown, no explanation."
)

DEFAULT_CALCULATE_PROBLEM_PROMPT = (
    "你是一个**答题助手**，可以根据用户的问题给出正确的回答，只需要回复答案，不要解释，不要输出任何其他内容。"
)


def encode_image(image: bytes):
    return base64.b64encode(image).decode("utf-8")


logger = logging.getLogger("tg-signer")


class OpenAIConfig(TypedDict, total=False):
    api_key: Required[str]
    base_url: Optional[str]
    model: Optional[str]


class OpenAIConfigManager:
    def __init__(self, workdir: Union[str, pathlib.Path]):
        self.workdir = pathlib.Path(workdir)

    def get_config_file(self) -> pathlib.Path:
        return self.workdir / ".openai_config.json"

    def has_env_config(self):
        return bool(os.environ.get("OPENAI_API_KEY"))

    def has_config(self) -> bool:
        return bool(self.load_config())

    def load_file_config(self) -> Optional[dict]:
        config_file = self.get_config_file()
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as fp:
                c = json.load(fp)
            # 简单验证必需字段
            if "api_key" in c:
                # 解密 API key
                try:
                    c["api_key"] = decrypt_secret(c["api_key"])
                except InvalidToken:
                    logger.warning("Failed to decrypt stored API key, returning None")
                    return None
                return c
        return None

    def save_config(self, api_key: str, base_url: str = None, model: str = None):
        config_file = self.get_config_file()
        encrypted_key = encrypt_secret(api_key)
        config = OpenAIConfig(api_key=encrypted_key, base_url=base_url, model=model)
        with open(config_file, "w", encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False, indent=2)

    def load_config(self) -> Optional[OpenAIConfig]:
        # 环境变量优先
        if self.has_env_config():
            return OpenAIConfig(
                api_key=os.environ["OPENAI_API_KEY"],
                base_url=os.environ.get("OPENAI_BASE_URL"),
                model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            )
        return self.load_file_config()

    def ask_for_config(self):
        print_to_user("开始配置OpenAI API并保存至本地。")
        input_ = UserInput()
        api_key = input_("请输入 OPENAI_API_KEY: ").strip()
        while not api_key:
            print_to_user("API Key不能为空！")
            api_key = input_("请输入 OPENAI_API_KEY: ").strip()

        base_url = (
            input_(
                "请输入 OPENAI_BASE_URL (可选，直接回车使用默认OpenAI地址): "
            ).strip()
            or None
        )
        model = (
            input_(
                f"请输入 OPENAI_MODEL (可选，直接回车使用默认模型({DEFAULT_MODEL})): "
            ).strip()
            or None
        )
        self.save_config(api_key, base_url=base_url, model=model)
        print_to_user("OpenAI配置已保存。")
        return self.load_config()


def get_openai_client(
    api_key: str = None,
    base_url: str = None,
    **kwargs,
) -> Optional["AsyncOpenAI"]:
    from openai import AsyncOpenAI, OpenAIError

    try:
        return AsyncOpenAI(api_key=api_key, base_url=base_url, **kwargs)
    except OpenAIError:
        return None


class AITools:
    _QUESTION_LINE_HINTS = (
        "点击",
        "选择",
        "选出",
        "找出",
        "识别",
        "图中",
        "图片",
        "图里",
        "图上的",
        "图示",
        "image",
        "photo",
        "picture",
        "shown",
        "select",
        "choose",
        "click",
    )

    def __init__(self, cfg: OpenAIConfig):
        self.client = get_openai_client(
            api_key=cfg["api_key"], base_url=cfg.get("base_url")
        )
        self.default_model = cfg.get("model") or DEFAULT_MODEL

    @staticmethod
    def _normalize_option_text(text: Any) -> str:
        return "".join(str(text).split()).lower()

    @staticmethod
    def _ai_timeout() -> float:
        try:
            timeout = float(os.environ.get("AI_VISION_TIMEOUT", "20"))
        except ValueError:
            return 20.0
        return max(3.0, timeout)

    @staticmethod
    def _read_positive_int_env(name: str, default: int, minimum: int) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    @classmethod
    def _extract_relevant_query(cls, query: str) -> str:
        if not query:
            return ""
        lines = []
        for raw_line in str(query).splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if line:
                lines.append(line)
        if not lines:
            return ""

        for line in lines:
            lowered = line.lower()
            if any(hint in line or hint in lowered for hint in cls._QUESTION_LINE_HINTS):
                return line[:160]
        return lines[0][:160]

    @classmethod
    def _looks_like_single_object_choice(
        cls, query: str, options: list[tuple[int, str]]
    ) -> bool:
        if not options or len(options) > 8:
            return False
        normalized_query = cls._extract_relevant_query(query).lower()
        if not any(
            keyword in normalized_query
            for keyword in ("图", "图片", "image", "photo", "picture", "object")
        ):
            return False
        short_label_count = sum(
            1
            for _, option_text in options
            if 0 < len(cls._normalize_option_text(option_text)) <= 16
        )
        return short_label_count == len(options)

    @classmethod
    def _crop_light_border(cls, image: "Image.Image") -> "Image.Image":
        white_threshold = cls._read_positive_int_env(
            "AI_VISION_WHITE_THRESHOLD", 245, 200
        )
        mask = image.convert("L").point(lambda px: 255 if px < white_threshold else 0)
        bbox = mask.getbbox()
        if not bbox or bbox == (0, 0, image.width, image.height):
            return image

        padding = max(12, min(image.size) // 32)
        left = max(0, bbox[0] - padding)
        top = max(0, bbox[1] - padding)
        right = min(image.width, bbox[2] + padding)
        bottom = min(image.height, bbox[3] + padding)
        return image.crop((left, top, right, bottom))

    @classmethod
    def _prepare_vision_image(cls, image: bytes) -> bytes:
        if Image is None:
            return image

        original_size = len(image)
        try:
            with Image.open(io.BytesIO(image)) as raw_image:
                prepared = raw_image.convert("RGB")
        except Exception:
            return image

        prepared = cls._crop_light_border(prepared)
        max_edge = cls._read_positive_int_env("AI_VISION_MAX_EDGE", 640, 224)
        if max(prepared.size) > max_edge:
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            prepared.thumbnail((max_edge, max_edge), resampling)

        quality = cls._read_positive_int_env("AI_VISION_JPEG_QUALITY", 85, 40)
        output = io.BytesIO()
        prepared.save(output, format="JPEG", quality=quality, optimize=True)
        result = output.getvalue()
        logger.debug(f"AI 图片预处理 | 原始: {original_size} bytes | 处理后: {len(result)} bytes | 尺寸: {prepared.size}")
        return result

    @staticmethod
    def _format_option_lines(options: list[tuple[int, str]]) -> str:
        return "\n".join(f"{index}. {text}" for index, text in options)

    @classmethod
    def _coerce_option_index(cls, result: Any, options: list[tuple[int, str]]) -> int:
        if isinstance(result, list):
            result = next((item for item in result if item is not None), None)

        if isinstance(result, dict):
            if isinstance(result.get("options"), list) and result["options"]:
                result = result["options"][0]
            else:
                for key in ("option", "index", "choice", "answer", "button", "text"):
                    if key in result:
                        result = result[key]
                        break

        if isinstance(result, dict):
            logger.error(f"AI 返回结果中未找到选项字段 | result_type={type(result).__name__} keys={list(result.keys())}")
            raise ValueError(f"AI result does not contain an option: {safe_text_preview(result, 100)}")

        if isinstance(result, int):
            return result

        if isinstance(result, str):
            stripped = result.strip()
            if stripped.lstrip("+-").isdigit():
                return int(stripped)
            normalized_result = cls._normalize_option_text(stripped)
            for index, option_text in options:
                normalized_option = cls._normalize_option_text(option_text)
                if normalized_result == normalized_option:
                    return index
            for index, option_text in options:
                normalized_option = cls._normalize_option_text(option_text)
                if normalized_option and normalized_option in normalized_result:
                    return index

        logger.error(f"AI 返回结果无法解析为选项索引 | result_type={type(result).__name__} result_chars={len(str(result))} options_count={len(options)}")
        raise ValueError(f"Could not parse AI option result: {safe_text_preview(result, 100)}")

    @classmethod
    def _coerce_option_indexes(cls, result: Any, options: list[tuple[int, str]]) -> list[int]:
        if isinstance(result, list):
            if len(result) == 1 and isinstance(result[0], dict):
                result = result[0]
            else:
                return [cls._coerce_option_index(item, options) for item in result]

        if isinstance(result, dict):
            raw_options = result.get("options")
            if raw_options is None:
                raw_options = result.get("option")
            if raw_options is not None:
                if not isinstance(raw_options, list):
                    raw_options = [raw_options]
                return [cls._coerce_option_index(item, options) for item in raw_options]

        return [cls._coerce_option_index(result, options)]

    @staticmethod
    def _should_retry_without_json_mode(exc: Exception) -> bool:
        text = str(exc).lower()
        indicators = (
            "response_format",
            "json_object",
            "bad_response_status_code",
            "openai_error",
            "unsupported",
        )
        return any(indicator in text for indicator in indicators)

    @staticmethod
    def _get_exception_status_code(exc: Exception) -> int | None:
        """从异常对象或错误文本中提取 HTTP 状态码。"""
        for attr in ("status_code", "code"):
            value = getattr(exc, attr, None)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)

        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value

        text = str(exc)
        for pattern in (r"Error code:\s*(\d{3})", r"['\"]code['\"]:\s*(\d{3})"):
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def _should_retry_transient_ai_error(cls, exc: Exception) -> bool:
        """判断 AI 视觉请求错误是否为瞬时故障（可重试）。
        配额耗尽（RESOURCE_EXHAUSTED / free_tier）不视为瞬时故障。
        """
        if isinstance(exc, TimeoutError):
            return True

        text = str(exc).lower()
        # 配额耗尽不可重试，避免无意义请求
        quota_markers = (
            "quota exceeded",
            "resource_exhausted",
            "free_tier",
            "check your plan and billing",
        )
        if any(marker in text for marker in quota_markers):
            return False

        status_code = cls._get_exception_status_code(exc)
        if status_code in {429, 500, 502, 503, 504}:
            return True

        transient_markers = (
            "unavailable",
            "high demand",
            "rate limit",
            "rate_limit",
            "temporarily unavailable",
            "try again later",
            "server error",
            "bad gateway",
            "gateway timeout",
        )
        return any(marker in text for marker in transient_markers)

    @classmethod
    def _vision_retry_attempts(cls) -> int:
        """AI 视觉请求最大重试次数，默认 2。"""
        return cls._read_positive_int_env("AI_VISION_RETRY_ATTEMPTS", 2, 1)

    @staticmethod
    def _vision_retry_delay(attempt: int) -> float:
        """AI 视觉请求重试延迟（秒），线性递增。"""
        try:
            base_delay = float(os.environ.get("AI_VISION_RETRY_DELAY", "0.6"))
        except ValueError:
            base_delay = 0.6
        return max(0.0, base_delay) * attempt

    async def _create_visual_completion(
        self,
        *,
        client: "AsyncOpenAI",
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        expect_json: bool,
    ):
        kwargs = {
            "messages": messages,
            "model": model,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if expect_json:
            kwargs["response_format"] = {"type": "json_object"}

        attempts = self._vision_retry_attempts()
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            _start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    client.chat.completions.create(**kwargs),
                    timeout=self._ai_timeout(),
                )
                _elapsed = (time.monotonic() - _start) * 1000
                _usage = getattr(result, "usage", None)
                _tokens = ""
                if _usage:
                    _tokens = f" | tokens: prompt={getattr(_usage, 'prompt_tokens', '?')} completion={getattr(_usage, 'completion_tokens', '?')}"
                logger.debug(f"AI API 调用完成 | model={model} elapsed_ms={_elapsed:.0f}{_tokens}")
                return result
            except Exception as exc:
                _elapsed = (time.monotonic() - _start) * 1000
                last_error = exc

                # JSON mode 降级：首次失败时去掉 response_format 重试
                if expect_json and self._should_retry_without_json_mode(exc):
                    logger.warning(
                        "AI provider 不支持 JSON mode，降级重试: %s",
                        safe_text_preview(exc, 200),
                    )
                    kwargs.pop("response_format", None)
                    expect_json = False
                    continue

                # 瞬时错误重试：503/429/500/502/504/超时
                if self._should_retry_transient_ai_error(exc) and attempt < attempts:
                    delay = self._vision_retry_delay(attempt)
                    logger.warning(
                        "AI 视觉请求瞬时错误，%g 秒后重试 (%d/%d): %s: %s",
                        delay, attempt, attempts,
                        type(exc).__name__,
                        safe_text_preview(exc, 200),
                    )
                    await asyncio.sleep(delay)
                    continue

                # 不可重试的错误或已达最大重试次数
                raise

        raise last_error

    async def choose_option_by_image(
        self,
        image: bytes,
        query: str,
        options: list[tuple[int, str]],
        client: "AsyncOpenAI" = None,
        model: str = None,
        system_prompt: str | None = None,
        temperature=0.1,
    ) -> int:
        sys_prompt = (system_prompt or "").strip() or DEFAULT_CHOOSE_OPTION_BY_IMAGE_PROMPT
        client = client or self.client
        model = model or self.default_model
        image = self._prepare_vision_image(image)
        query = self._extract_relevant_query(query) or "选择最符合图片的选项"
        text_query = (
            f"Question:\n{query}\n\n"
            f"Options:\n{self._format_option_lines(options)}"
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_query},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encode_image(image)}"
                        },
                    },
                ],
            },
        ]
        completion = await self._create_visual_completion(
            client=client,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=24,
            expect_json=True,
        )
        message = completion.choices[0].message
        result = json_repair.loads(message.content)
        return self._coerce_option_index(result, options)

    async def choose_options_by_image(
        self,
        image: bytes,
        query: str,
        options: list[tuple[int, str]],
        client: "AsyncOpenAI" = None,
        model: str = None,
        system_prompt: str | None = None,
        temperature=0.1,
    ) -> list[int]:
        if (system_prompt or "").strip():
            sys_prompt = system_prompt.strip()
        elif self._looks_like_single_object_choice(query, options):
            sys_prompt = DEFAULT_SINGLE_OBJECT_CHOICE_PROMPT
        else:
            sys_prompt = DEFAULT_CHOOSE_OPTIONS_BY_IMAGE_PROMPT
        client = client or self.client
        model = model or self.default_model
        image = self._prepare_vision_image(image)
        query = self._extract_relevant_query(query) or "Choose the correct option"
        text_query = (
            f"Question:\n{query}\n\n"
            f"Button options in row order:\n{self._format_option_lines(options)}"
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_query},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encode_image(image)}"
                        },
                    },
                ],
            },
        ]
        completion = await self._create_visual_completion(
            client=client,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=32,
            expect_json=True,
        )
        result = json_repair.loads(completion.choices[0].message.content)
        return self._coerce_option_indexes(result, options)

    async def extract_text_by_image(
        self,
        image: bytes,
        query: str = "",
        client: "AsyncOpenAI" = None,
        model: str = None,
        system_prompt: str | None = None,
        temperature=0.1,
    ) -> str:
        sys_prompt = (system_prompt or "").strip() or DEFAULT_EXTRACT_TEXT_BY_IMAGE_PROMPT
        client = client or self.client
        model = model or self.default_model
        text_query = query or "Extract the key text from this image."
        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_query},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encode_image(image)}"
                        },
                    },
                ],
            },
        ]
        completion = await client.chat.completions.create(
            messages=messages,
            model=model,
            stream=False,
            temperature=temperature,
        )
        return (completion.choices[0].message.content or "").strip()

    async def calculate_problem(
        self,
        query: str,
        client: "AsyncOpenAI" = None,
        model: str = None,
        system_prompt: str | None = None,
        temperature=0.1,
    ) -> str:
        sys_prompt = (system_prompt or "").strip() or DEFAULT_CALCULATE_PROBLEM_PROMPT
        model = model or self.default_model
        client = client or self.client
        text = f"问题是: {query}\n\n只需要给出答案，不要解释，不要输出任何其他内容。The answer is:"
        # noinspection PyTypeChecker
        completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            model=model,
            stream=False,
            temperature=temperature,
        )
        return completion.choices[0].message.content.strip()

    async def get_reply(
        self,
        prompt: str,
        query: str,
        client: "AsyncOpenAI" = None,
        model: str = None,
    ) -> str:
        model = model or self.default_model
        client = client or self.client
        messages = [
            {
                "role": "system",
                "content": prompt,
            },
            {"role": "user", "content": f"{query}"},
        ]
        # noinspection PyTypeChecker
        completion = await client.chat.completions.create(
            messages=messages,
            model=model,
            stream=False,
        )
        message = completion.choices[0].message
        return message.content
