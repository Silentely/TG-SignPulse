import re
from datetime import time
from enum import Enum
from functools import cached_property
from typing import (
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    Union,
)

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    ValidationError,
    root_validator,
    validator,
)
from typing_extensions import Self, TypeAlias

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    ConfigDict = None

from tg_signer.pydantic_compat import IS_V2 as _PYDANTIC_V2
from tg_signer.pydantic_compat import model_dump as _compat_model_dump
from tg_signer.pydantic_compat import model_validate as _compat_model_validate

try:
    from pyrogram.types import Chat, Message
except Exception:  # pragma: no cover - import fallback for unsupported runtimes

    class Chat:  # type: ignore[no-redef]
        pass

    class Message:  # type: ignore[no-redef]
        pass


class BaseJSONConfig(BaseModel):
    version: ClassVar[Union[str, int]] = 0
    olds: ClassVar[Optional[List[Type["BaseJSONConfig"]]]] = None
    is_current: ClassVar[bool] = False

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(
            ignored_types=(cached_property,),
            arbitrary_types_allowed=True,
        )
    else:

        class Config:
            keep_untouched = (cached_property,)
            arbitrary_types_allowed = True

    @classmethod
    def valid(cls, d):
        try:
            return _compat_model_validate(cls, d)
        except (ValidationError, TypeError):
            return None

    def to_jsonable(self):
        return _compat_model_dump(self)

    @classmethod
    def to_current(cls, obj: Self):
        return obj

    @classmethod
    def load(cls, d: dict) -> Optional[Tuple[Self, bool]]:
        if instance := cls.valid(d):
            return instance, False
        for old in cls.olds or []:
            if old_inst := old.valid(d):
                return old.to_current(old_inst), True
        return None


class SignConfigV1(BaseJSONConfig):
    version = 1

    chat_id: int
    sign_text: str
    sign_at: time
    random_seconds: int

    @classmethod
    def to_current(cls, obj: "SignConfigV1"):
        return SignConfigV2(
            chats=[
                SignChatV2(
                    chat_id=obj.chat_id,
                    sign_text=obj.sign_text,
                    delete_after=None,
                )
            ],
            sign_at=str(obj.sign_at),
            random_seconds=obj.random_seconds,
        )


class SignChatV2(BaseJSONConfig):
    version: ClassVar = 2
    chat_id: int
    delete_after: Optional[int] = None
    sign_text: Union[str, Literal["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"]]
    as_dice: bool = False  # 作为Dice类型的emoji进行发送
    text_of_btn_to_click: Optional[str] = None  # 需要点击的按钮的文本
    choose_option_by_image: bool = False  # 需要根据图片选择选项
    has_calculation_problem: bool = False  # 是否有计算题

    @property
    def need_response(self):
        return (
            bool(self.text_of_btn_to_click)
            or self.choose_option_by_image
            or self.has_calculation_problem
        )


class SignConfigV2(BaseJSONConfig):
    version: ClassVar = 2
    olds: ClassVar = [SignConfigV1]
    is_current: ClassVar = False

    chats: List[SignChatV2]
    sign_at: str  # 签到时间，time或crontab表达式
    random_seconds: int = 0
    sign_interval: int = 1  # 连续签到的间隔时间，单位秒

    @classmethod
    def to_current(cls, obj: Union["SignConfigV2", "SignConfigV1"]):
        if isinstance(obj, SignConfigV1):
            obj = SignConfigV1.to_current(obj)
        v3_chats = []
        for chat in obj.chats:
            actions = []
            if chat.sign_text:
                if chat.as_dice:
                    actions.append(SendDiceAction(dice=chat.sign_text))
                else:
                    actions.append(SendTextAction(text=chat.sign_text))
            if chat.text_of_btn_to_click:
                actions.append(
                    ClickKeyboardByTextAction(text=chat.text_of_btn_to_click)
                )
            if chat.choose_option_by_image:
                actions.append(ChooseOptionByImageAction())
            if chat.has_calculation_problem:
                actions.append(ReplyByCalculationProblemAction())
            v3_chats.append(
                SignChatV3(
                    chat_id=chat.chat_id,
                    delete_after=chat.delete_after,
                    actions=actions,
                )
            )
        return SignConfigV3(
            sign_at=obj.sign_at,
            random_seconds=obj.random_seconds,
            sign_interval=obj.sign_interval,
            chats=v3_chats,
        )


class SupportAction(int, Enum):
    SEND_TEXT = 1  # 发送普通文本
    SEND_DICE = 2  # 发送Dice类型的emoji
    CLICK_KEYBOARD_BY_TEXT = 3  # 根据文本点击键盘
    CHOOSE_OPTION_BY_IMAGE = 4  # 根据图片选择选项
    REPLY_BY_CALCULATION_PROBLEM = 5  # 回复计算题
    REPLY_BY_IMAGE_RECOGNITION = 6  # AI image recognition then send text
    CLICK_BUTTON_BY_CALCULATION_PROBLEM = 7  # AI calculation then click button
    KEYWORD_NOTIFY = 8  # Listen for keywords
    CUSTOM_PLUGIN = 99  # 自定义插件动作（10-98 预留给未来官方通用动作）

    @property
    def desc(self):
        return {
            SupportAction.SEND_TEXT: "发送普通文本",
            SupportAction.SEND_DICE: "发送Dice类型的emoji",
            SupportAction.CLICK_KEYBOARD_BY_TEXT: "根据文本点击键盘",
            SupportAction.CHOOSE_OPTION_BY_IMAGE: "根据图片选择选项",
            SupportAction.REPLY_BY_CALCULATION_PROBLEM: "回复计算题",
            SupportAction.REPLY_BY_IMAGE_RECOGNITION: "AI image recognition then send text",
            SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM: "AI calculation then click button",
            SupportAction.KEYWORD_NOTIFY: "关键词监听",
            SupportAction.CUSTOM_PLUGIN: "自定义插件",
        }[self]


class SignAction(BaseModel):
    action: SupportAction
    delay: Optional[str] = None
    continue_on_error: bool = False
    skip_if_matched: Optional[str] = None
    stop_flow_on_terminal: bool = False


class SendTextAction(SignAction):
    action: Literal[SupportAction.SEND_TEXT] = SupportAction.SEND_TEXT
    text: str


class SendDiceAction(SignAction):
    action: Literal[SupportAction.SEND_DICE] = SupportAction.SEND_DICE
    dice: Union[Literal["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"], str]


class ClickKeyboardByTextAction(SignAction):
    action: Literal[SupportAction.CLICK_KEYBOARD_BY_TEXT] = (
        SupportAction.CLICK_KEYBOARD_BY_TEXT
    )
    text: str


class ChooseOptionByImageAction(SignAction):
    action: Literal[SupportAction.CHOOSE_OPTION_BY_IMAGE] = (
        SupportAction.CHOOSE_OPTION_BY_IMAGE
    )
    ai_prompt: Optional[str] = None


class ReplyByCalculationProblemAction(SignAction):
    action: Literal[SupportAction.REPLY_BY_CALCULATION_PROBLEM] = (
        SupportAction.REPLY_BY_CALCULATION_PROBLEM
    )
    ai_prompt: Optional[str] = None


class ReplyByImageRecognitionAction(SignAction):
    action: Literal[SupportAction.REPLY_BY_IMAGE_RECOGNITION] = (
        SupportAction.REPLY_BY_IMAGE_RECOGNITION
    )
    ai_prompt: Optional[str] = None


class ClickButtonByCalculationProblemAction(SignAction):
    action: Literal[SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM] = (
        SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM
    )
    ai_prompt: Optional[str] = None


class KeywordNotifyAction(SignAction):
    action: Literal[SupportAction.KEYWORD_NOTIFY] = SupportAction.KEYWORD_NOTIFY
    keywords: List[str]
    match_mode: Literal["contains", "exact", "regex"] = "contains"
    ignore_case: bool = True
    # 默认忽略自己发送的消息，避免自动回复/后续动作死循环
    ignore_self: bool = True
    # 限定监听时间段（HH:MM，支持跨午夜）；均空表示全天
    active_time_start: Optional[str] = None
    active_time_end: Optional[str] = None
    push_channel: Literal["telegram", "forward", "bark", "custom", "continue"] = (
        "telegram"
    )
    bark_url: Optional[str] = None
    custom_url: Optional[str] = None
    forward_chat_id: Optional[Union[int, str]] = None
    forward_message_thread_id: Optional[int] = None
    continue_chat_id: Optional[Union[int, str]] = None
    continue_message_thread_id: Optional[int] = None
    continue_action_interval: float = 1
    continue_actions: List[Dict[str, Any]] = Field(default_factory=list)

    @root_validator
    def _check_keyword_regex_safety(cls, values):  # noqa: N805
        """阻断灾难性回溯（ReDoS）关键词正则。

        match_mode 定义在 keywords 之后，field validator 拿不到 match_mode，
        必须用 root_validator 在字段校验完成后统一判定。
        """
        from tg_signer.utils import is_unsafe_keyword_regex

        if not isinstance(values, dict):
            return values
        mode = str(values.get("match_mode") or "contains").strip()
        if mode != "regex":
            return values
        raw = values.get("keywords")
        items = raw if isinstance(raw, list) else [raw]
        unsafe = [
            str(k) for k in (items or []) if k and is_unsafe_keyword_regex(str(k))
        ]
        if unsafe:
            raise ValueError(
                "关键词正则存在灾难性回溯风险（可能导致服务无响应），请避免 "
                "「组内含可变长度且整体被重复」的写法，如 ^(\\w+\\s?)*$："
                + "; ".join(unsafe[:3])
            )
        return values


class PluginAction(SignAction):
    action: Literal[SupportAction.CUSTOM_PLUGIN] = SupportAction.CUSTOM_PLUGIN
    plugin_name: str
    mode: Literal["reactive", "active"] = "reactive"
    timeout: Optional[float] = None
    params: Dict[str, Any] = Field(default_factory=dict)


ActionT: TypeAlias = Union[
    SendTextAction,
    SendDiceAction,
    ClickKeyboardByTextAction,
    ChooseOptionByImageAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    ClickButtonByCalculationProblemAction,
    KeywordNotifyAction,
    PluginAction,
]


class WorkflowConfigError(ValueError):
    """工作流配置与拓扑结构异常基类"""


class WorkflowStepConfig(BaseModel):
    step_id: str
    action_type: SupportAction
    config: Dict[str, Any] = Field(default_factory=dict)
    next_step_id: Optional[str] = None
    on_failure_step_id: Optional[str] = None
    allow_loop: bool = False
    max_retries: Optional[int] = None

    @validator("action_type", pre=True)
    def _parse_action_type(cls, v):
        if isinstance(v, SupportAction):
            return v
        if isinstance(v, int):
            try:
                return SupportAction(v)
            except ValueError:
                return v
        if isinstance(v, str):
            v_clean = v.strip().upper()
            if hasattr(SupportAction, v_clean):
                return getattr(SupportAction, v_clean)
            try:
                return SupportAction(int(v))
            except (ValueError, TypeError):
                pass
        return v

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(
            use_enum_values=False,
            arbitrary_types_allowed=True,
        )

    @root_validator
    def _validate_step_config(cls, values):
        if not isinstance(values, dict):
            return values
        raw_id = values.get("step_id")
        step_id = str(raw_id or "").strip()
        if not step_id:
            raise WorkflowConfigError("step_id 不能为空")
        if step_id in {"COMPLETE", "FAIL"}:
            raise WorkflowConfigError(f"step_id 不能使用保留哨兵名: {step_id}")
        values["step_id"] = step_id

        allow_loop = bool(values.get("allow_loop", False))
        max_retries = values.get("max_retries")
        if allow_loop:
            if max_retries is None or max_retries < 0:
                raise WorkflowConfigError(
                    f"步骤 '{step_id}' 允许循环 (allow_loop=True) 时必须配置非负 max_retries"
                )
        else:
            if max_retries is not None:
                raise WorkflowConfigError(
                    f"步骤 '{step_id}' 未允许循环 (allow_loop=False)，max_retries 必须为 None"
                )

        cfg = values.get("config") or {}
        action_type = values.get("action_type")
        if "action" in cfg:
            raw_action = cfg["action"]
            raw_val = raw_action.value if hasattr(raw_action, "value") else raw_action
            act_val = (
                action_type.value if hasattr(action_type, "value") else action_type
            )
            if raw_val != act_val:
                raise WorkflowConfigError(
                    f"步骤 '{step_id}' config 中的 action ({raw_val}) 与 action_type ({act_val}) 不一致"
                )
        return values

    def to_workflow_step(self):
        from tg_signer.core.workflow_engine import WorkflowStep

        return WorkflowStep(
            step_id=self.step_id,
            action_type=self.action_type,
            next_step_id=self.next_step_id,
            on_failure_step_id=self.on_failure_step_id,
            allow_loop=self.allow_loop,
            max_retries=self.max_retries,
            config=self.config,
        )


ACTION_MODEL_MAP: Dict[SupportAction, Type[SignAction]] = {
    SupportAction.SEND_TEXT: SendTextAction,
    SupportAction.SEND_DICE: SendDiceAction,
    SupportAction.CLICK_KEYBOARD_BY_TEXT: ClickKeyboardByTextAction,
    SupportAction.CHOOSE_OPTION_BY_IMAGE: ChooseOptionByImageAction,
    SupportAction.REPLY_BY_CALCULATION_PROBLEM: ReplyByCalculationProblemAction,
    SupportAction.REPLY_BY_IMAGE_RECOGNITION: ReplyByImageRecognitionAction,
    SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM: ClickButtonByCalculationProblemAction,
    SupportAction.KEYWORD_NOTIFY: KeywordNotifyAction,
    SupportAction.CUSTOM_PLUGIN: PluginAction,
}


def action_from_step(step: WorkflowStepConfig) -> ActionT:
    model_cls = ACTION_MODEL_MAP.get(step.action_type)
    if model_cls is None:
        raise WorkflowConfigError(
            f"步骤 '{step.step_id}' 未知的动作类型: {step.action_type}"
        )
    data = dict(step.config or {})
    data["action"] = step.action_type
    try:
        return model_cls(**data)
    except (ValidationError, ValueError) as err:
        raise WorkflowConfigError(f"步骤 '{step.step_id}' 动作配置无效: {err}") from err


class SignChatV3(BaseJSONConfig):
    version: ClassVar = 3
    chat_id: int
    name: Optional[str] = None
    delete_after: Optional[int] = None
    actions: Optional[List[ActionT]] = None
    steps: Optional[List[WorkflowStepConfig]] = None
    initial_step_id: Optional[str] = None
    action_interval: float = 1  # actions的间隔时间，单位秒
    message_thread_id: Optional[int] = None
    next_task_on_success: Optional[str] = None
    next_task_delay_seconds: Optional[float] = None
    execution_engine: Optional[str] = None

    @root_validator
    def _validate_actions_or_steps(cls, values):
        if not isinstance(values, dict):
            return values
        actions = values.get("actions")
        steps = values.get("steps")
        initial_step_id = values.get("initial_step_id")

        if actions is None and steps is None:
            raise WorkflowConfigError("actions 与 steps 互斥，必须且只能配置其中之一")
        if actions is not None and steps is not None:
            raise WorkflowConfigError("actions 与 steps 互斥，不能同时配置")

        if actions is not None:
            return values

        if steps is not None:
            if len(steps) == 0:
                raise WorkflowConfigError("工作流 steps 列表不能为空")
            if not initial_step_id or not str(initial_step_id).strip():
                raise WorkflowConfigError("配置工作流 steps 时必须提供 initial_step_id")
            step_ids = []
            for s in steps:
                s_id = getattr(s, "step_id", None) or (
                    s.get("step_id") if isinstance(s, dict) else None
                )
                if not s_id:
                    raise WorkflowConfigError("步骤必须包含非空 step_id")
                if s_id in step_ids:
                    raise WorkflowConfigError(f"存在重复的 step_id: {s_id}")
                step_ids.append(s_id)
            if initial_step_id not in step_ids:
                raise WorkflowConfigError(
                    f"initial_step_id '{initial_step_id}' 不在 steps 列表中"
                )

            # 静态拓扑校验
            from tg_signer.core.workflow_engine import (
                WorkflowDefinition,
                WorkflowEngine,
            )

            wf_steps = [
                s.to_workflow_step()
                if hasattr(s, "to_workflow_step")
                else WorkflowStepConfig(**s).to_workflow_step()
                for s in steps
            ]
            wf_def = WorkflowDefinition(steps=wf_steps, initial_step_id=initial_step_id)
            try:
                WorkflowEngine.validate_topology(wf_def)
            except Exception as err:
                raise WorkflowConfigError(f"工作流拓扑结构无效: {err}") from err

        return values

    def to_jsonable(self):
        data = super().to_jsonable()
        if self.steps is None:
            data.pop("steps", None)
            data.pop("initial_step_id", None)
        elif self.actions is None:
            data.pop("actions", None)
        return data

    def __repr__(self) -> str:
        if self.steps is not None:
            return (
                f"SignChatV3(chat_id={self.chat_id}, "
                f"delete_after={self.delete_after}, "
                f"steps=[{len(self.steps)} steps], "
                f"initial_step_id='{self.initial_step_id}'),"
                f"action_interval={self.action_interval}"
            )
        act_len = len(self.actions) if self.actions is not None else 0
        return (
            f"SignChatV3(chat_id={self.chat_id}, "
            f"delete_after={self.delete_after}, "
            f"actions=[{act_len} actions]),"
            f"action_interval={self.action_interval}"
        )

    def __str__(self) -> str:
        from tg_signer.utils import format_sign_chat_box

        return format_sign_chat_box(self)

    @property
    def requires_ai(self) -> bool:
        ai_actions = {
            SupportAction.CHOOSE_OPTION_BY_IMAGE,
            SupportAction.REPLY_BY_CALCULATION_PROBLEM,
            SupportAction.REPLY_BY_IMAGE_RECOGNITION,
            SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM,
        }
        if self.steps is not None:
            return any(s.action_type in ai_actions for s in self.steps)
        if self.actions is not None:
            return any(action.action in ai_actions for action in self.actions)
        return False

    @property
    def requires_updates(self) -> bool:
        response_actions = {
            SupportAction.CLICK_KEYBOARD_BY_TEXT,
            SupportAction.CHOOSE_OPTION_BY_IMAGE,
            SupportAction.REPLY_BY_CALCULATION_PROBLEM,
            SupportAction.REPLY_BY_IMAGE_RECOGNITION,
            SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM,
            SupportAction.KEYWORD_NOTIFY,
        }
        if self.steps is not None:
            for s in self.steps:
                if s.action_type in response_actions:
                    return True
                if (
                    s.action_type == SupportAction.CUSTOM_PLUGIN
                    and (s.config or {}).get("mode", "reactive") == "reactive"
                ):
                    return True
            return False

        if self.actions is not None:
            for action in self.actions:
                if action.action in response_actions:
                    return True
                if (
                    action.action == SupportAction.CUSTOM_PLUGIN
                    and getattr(action, "mode", "reactive") == "reactive"
                ):
                    return True
        return False


class SignConfigV3(BaseJSONConfig):
    version: ClassVar = 3
    olds: ClassVar = [SignConfigV2]
    is_current: ClassVar = True

    _version: Literal[3] = 3
    chats: List[SignChatV3]
    sign_at: str  # 签到时间，time或crontab表达式
    random_seconds: int = 0
    sign_interval: int = 1  # 连续签到的间隔时间，单位秒

    @property
    def requires_ai(self) -> bool:
        return any(chat.requires_ai for chat in self.chats)

    @property
    def requires_updates(self) -> bool:
        return any(chat.requires_updates for chat in self.chats)


MatchRuleT: TypeAlias = Literal["exact", "contains", "regex", "all"]


class UDPForward(BaseModel):
    type: Literal["udp"] = "udp"
    host: str
    port: int


class HttpCallback(BaseModel):
    type: Literal["http"] = "http"
    url: AnyHttpUrl
    headers: Optional[Dict[str, str]] = None
    method: Literal["post"] = "post"


class MatchConfig(BaseJSONConfig):
    chat_id: Union[int, str] = None  # 聊天id或username
    rule: MatchRuleT = "exact"  # 匹配规则
    rule_value: Optional[str] = None  # 规则值
    from_user_ids: Optional[List[Union[int, str]]] = (
        None  # 发送者id或username，为空时，匹配所有人
    )
    always_ignore_me: bool = False  # 总是忽略自己发送的消息
    default_send_text: Optional[str] = None  # 默认发送内容
    ai_reply: bool = False  # 是否使用AI回复
    ai_prompt: Optional[str] = None
    send_text_search_regex: Optional[str] = None  # 用正则表达式从消息中提取发送内容
    delete_after: Optional[int] = None
    ignore_case: bool = True  # 忽略大小写
    forward_to_chat_id: Optional[Union[int, str]] = (
        None  # 转发消息到该聊天，默认为消息来源
    )
    external_forwards: Optional[List[Union[UDPForward, HttpCallback]]] = (
        None  # 转发到外部
    )
    push_via_server_chan: bool = False  # 将消息通过server酱推送
    server_chan_send_key: Optional[str] = None  # server酱的sendkey

    def __str__(self):
        return (
            f"{self.__class__.__name__}(chat_id={self.chat_id}, rule={self.rule}, rule_value={self.rule_value}),"
            f" default_send_text={self.default_send_text}, send_text_search_regex={self.send_text_search_regex}"
        )

    @cached_property
    def _compiled_rule_regex(self) -> "re.Pattern":
        """regex 规则的预编译 Pattern：消息热路径免逐条重编译。"""
        flags = re.IGNORECASE if self.ignore_case else 0
        return re.compile(self.rule_value, flags=flags)

    @cached_property
    def _compiled_send_text_regex(self) -> "re.Pattern":
        """send_text_search_regex 的预编译 Pattern，仅在该规则启用时使用。"""
        return re.compile(self.send_text_search_regex)

    @cached_property
    def from_user_set(self):
        return {
            (
                "me"
                if u in ["me", "self"]
                else u.lower().strip("@")
                if isinstance(u, str)
                else u
            )
            for u in self.from_user_ids
        }

    def match_user(self, message: "Message"):
        if not message.from_user:
            return True
        if self.always_ignore_me and message.from_user.is_self:
            return False
        if not self.from_user_ids:
            return True
        return (
            message.from_user.id in self.from_user_set
            or (
                message.from_user.username
                and message.from_user.username.lower() in self.from_user_set
            )
            or ("me" in self.from_user_set and message.from_user.is_self)
        )

    def match_text(self, text: str) -> bool:
        """
        根据`rule`校验`text`是否匹配
        """
        rule_value = self.rule_value
        if self.rule == "all":
            return True
        if self.rule == "exact":
            if self.ignore_case:
                return rule_value.lower() == text.lower()
            return rule_value == text
        elif self.rule == "contains":
            if self.ignore_case:
                return rule_value.lower() in text.lower()
            return rule_value in text
        elif self.rule == "regex":
            return bool(self._compiled_rule_regex.search(text))
        return False

    def match_chat(self, chat: "Chat"):
        if isinstance(self.chat_id, int):
            return self.chat_id == chat.id
        return self.chat_id == chat.username

    def match(self, message: "Message"):
        return self.match_chat(message.chat) and bool(
            self.match_user(message) and self.match_text(message.text)
        )

    def get_send_text(self, text: str) -> str:
        send_text = self.default_send_text
        if self.send_text_search_regex:
            m = self._compiled_send_text_regex.search(text)
            if not m:
                return send_text
            try:
                send_text = m.group(1)
            except IndexError as e:
                raise ValueError(
                    f"{self}: 消息文本: 「{text}」匹配成功但未能捕获关键词, 请检查正则表达式"
                ) from e
        return send_text

    @property
    def requires_ai(self) -> bool:
        return bool(self.ai_reply and self.ai_prompt)


class MonitorConfig(BaseJSONConfig):
    """监控配置"""

    version: ClassVar = 1
    is_current: ClassVar = True
    match_cfgs: List[MatchConfig]

    @property
    def chat_ids(self):
        return [cfg.chat_id for cfg in self.match_cfgs]

    @property
    def requires_ai(self) -> bool:
        return any(cfg.requires_ai for cfg in self.match_cfgs)
