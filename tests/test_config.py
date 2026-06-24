"""
tg_signer/config.py 单元测试

覆盖范围：
- 工具函数：get_display_width、pad_text_to_width
- BaseJSONConfig：序列化、加载、版本迁移
- SupportAction 枚举
- 动作类型：SendTextAction、SendDiceAction、ClickKeyboardByTextAction 等
- SignChatV3：创建、多动作配置、requires_ai/requires_updates 属性
- SignConfigV3：创建、序列化、反序列化、版本迁移
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from tg_signer.config import (
    ActionT,
    BaseJSONConfig,
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickKeyboardByTextAction,
    KeywordNotifyAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignAction,
    SignChatV3,
    SignConfigV1,
    SignConfigV2,
    SignConfigV3,
    SupportAction,
    get_display_width,
    pad_text_to_width,
)
from tests.fixtures.tasks import (
    SIGN_CONFIG_V3_BASIC,
    SIGN_CONFIG_V3_DICE,
    SIGN_CONFIG_V3_MULTI_ACTION,
    SIGN_CONFIG_V3_MULTI_CHAT,
    SIGN_CONFIG_V3_WITH_AI,
    SIGN_CONFIG_V3_WITH_KEYWORD,
    make_sign_config_v3_dict,
)


# ============================================================================
# 工具函数测试
# ============================================================================


class TestGetDisplayWidth:
    """get_display_width 函数测试"""

    def test_ascii_only(self):
        """纯 ASCII 字符宽度等于字符数"""
        assert get_display_width("hello") == 5

    def test_chinese_characters(self):
        """中文字符宽度为 2"""
        assert get_display_width("你好") == 4

    def test_mixed_content(self):
        """中英文混合计算"""
        assert get_display_width("hi你好") == 6  # 2 + 4

    def test_empty_string(self):
        """空字符串宽度为 0"""
        assert get_display_width("") == 0

    def test_non_ascii_non_chinese(self):
        """非 ASCII 非中文字符（如 emoji）也占 2 宽度"""
        # emoji 的 ord > 127，所以也算 2
        assert get_display_width("aé") == 3  # 'a' = 1, 'é' (é) = 2


class TestPadTextToWidth:
    """pad_text_to_width 函数测试"""

    def test_left_align(self):
        """左对齐填充"""
        result = pad_text_to_width("hi", 5, align="left")
        assert result == "hi   "

    def test_right_align(self):
        """右对齐填充"""
        result = pad_text_to_width("hi", 5, align="right")
        assert result == "   hi"

    def test_center_align(self):
        """居中对齐填充"""
        result = pad_text_to_width("hi", 6, align="center")
        assert result == "  hi  "

    def test_no_padding_needed(self):
        """文本宽度已达到目标，不填充"""
        result = pad_text_to_width("hello", 3, align="left")
        assert result == "hello"

    def test_chinese_padding(self):
        """中文字符填充正确计算宽度"""
        result = pad_text_to_width("你好", 8, align="left")
        # "你好" 宽度=4，需要填充 4 个空格
        assert result == "你好    "
        assert len(result) == 6  # 2 中文字符 + 4 空格

    def test_default_align_is_left(self):
        """默认对齐方式为左对齐"""
        result = pad_text_to_width("ab", 5)
        assert result == "ab   "


# ============================================================================
# SupportAction 枚举测试
# ============================================================================


class TestSupportAction:
    """SupportAction 枚举测试"""

    def test_enum_values(self):
        """枚举值正确"""
        assert SupportAction.SEND_TEXT == 1
        assert SupportAction.SEND_DICE == 2
        assert SupportAction.CLICK_KEYBOARD_BY_TEXT == 3
        assert SupportAction.CHOOSE_OPTION_BY_IMAGE == 4
        assert SupportAction.REPLY_BY_CALCULATION_PROBLEM == 5
        assert SupportAction.REPLY_BY_IMAGE_RECOGNITION == 6
        assert SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM == 7
        assert SupportAction.KEYWORD_NOTIFY == 8

    def test_desc_property(self):
        """desc 属性返回中文描述"""
        assert SupportAction.SEND_TEXT.desc == "发送普通文本"
        assert SupportAction.SEND_DICE.desc == "发送Dice类型的emoji"
        assert SupportAction.CLICK_KEYBOARD_BY_TEXT.desc == "根据文本点击键盘"
        assert SupportAction.KEYWORD_NOTIFY.desc == "关键词监听"

    def test_all_actions_have_desc(self):
        """所有枚举成员都有 desc 属性"""
        for action in SupportAction:
            assert isinstance(action.desc, str)
            assert len(action.desc) > 0

    def test_int_enum_behavior(self):
        """SupportAction 继承 int，可用于数值比较"""
        assert SupportAction(1) == SupportAction.SEND_TEXT
        assert int(SupportAction.SEND_DICE) == 2


# ============================================================================
# 动作类型测试
# ============================================================================


class TestSendTextAction:
    """SendTextAction 测试"""

    def test_create_basic(self):
        """创建基本文本动作"""
        action = SendTextAction(text="签到")
        assert action.text == "签到"
        assert action.action == SupportAction.SEND_TEXT
        assert action.delay is None

    def test_create_with_delay(self):
        """创建带延迟的文本动作"""
        action = SendTextAction(text="打卡", delay="1-3")
        assert action.text == "打卡"
        assert action.delay == "1-3"

    def test_serialization(self):
        """序列化为字典"""
        action = SendTextAction(text="签到")
        if hasattr(action, "model_dump"):
            d = action.model_dump()
        else:
            d = action.dict()
        assert d["action"] == 1
        assert d["text"] == "签到"

    def test_deserialization(self):
        """从字典反序列化"""
        data = {"action": 1, "text": "签到"}
        action = SendTextAction(**data)
        assert action.text == "签到"
        assert action.action == SupportAction.SEND_TEXT

    def test_missing_text_raises(self):
        """缺少 text 字段抛出验证错误"""
        with pytest.raises(ValidationError):
            SendTextAction()

    def test_action_type_is_literal(self):
        """action 字段是固定的 SEND_TEXT"""
        action = SendTextAction(text="test")
        assert action.action is SupportAction.SEND_TEXT


class TestSendDiceAction:
    """SendDiceAction 测试"""

    @pytest.mark.parametrize("dice_emoji", ["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"])
    def test_valid_dice_emojis(self, dice_emoji):
        """支持所有标准骰子 emoji"""
        action = SendDiceAction(dice=dice_emoji)
        assert action.dice == dice_emoji
        assert action.action == SupportAction.SEND_DICE

    def test_custom_dice_string(self):
        """支持自定义骰子字符串"""
        action = SendDiceAction(dice="custom")
        assert action.dice == "custom"

    def test_serialization(self):
        """序列化为字典"""
        action = SendDiceAction(dice="🎲")
        if hasattr(action, "model_dump"):
            d = action.model_dump()
        else:
            d = action.dict()
        assert d["action"] == 2
        assert d["dice"] == "🎲"

    def test_deserialization(self):
        """从字典反序列化"""
        data = {"action": 2, "dice": "🎯"}
        action = SendDiceAction(**data)
        assert action.dice == "🎯"


class TestClickKeyboardByTextAction:
    """ClickKeyboardByTextAction 测试"""

    def test_create_basic(self):
        """创建键盘点击动作"""
        action = ClickKeyboardByTextAction(text="确认")
        assert action.text == "确认"
        assert action.action == SupportAction.CLICK_KEYBOARD_BY_TEXT

    def test_serialization(self):
        """序列化为字典"""
        action = ClickKeyboardByTextAction(text="确定")
        if hasattr(action, "model_dump"):
            d = action.model_dump()
        else:
            d = action.dict()
        assert d["action"] == 3
        assert d["text"] == "确定"

    def test_deserialization(self):
        """从字典反序列化"""
        data = {"action": 3, "text": "提交"}
        action = ClickKeyboardByTextAction(**data)
        assert action.text == "提交"
        assert action.action == SupportAction.CLICK_KEYBOARD_BY_TEXT

    def test_missing_text_raises(self):
        """缺少 text 字段抛出验证错误"""
        with pytest.raises(ValidationError):
            ClickKeyboardByTextAction()


class TestChooseOptionByImageAction:
    """ChooseOptionByImageAction 测试"""

    def test_create_default(self):
        """创建图片选择动作（默认无 ai_prompt）"""
        action = ChooseOptionByImageAction()
        assert action.action == SupportAction.CHOOSE_OPTION_BY_IMAGE
        assert action.ai_prompt is None

    def test_create_with_prompt(self):
        """创建带 AI 提示的图片选择动作"""
        action = ChooseOptionByImageAction(ai_prompt="选择正确答案")
        assert action.ai_prompt == "选择正确答案"


class TestReplyByCalculationProblemAction:
    """ReplyByCalculationProblemAction 测试"""

    def test_create_default(self):
        """创建计算题动作（默认无 ai_prompt）"""
        action = ReplyByCalculationProblemAction()
        assert action.action == SupportAction.REPLY_BY_CALCULATION_PROBLEM
        assert action.ai_prompt is None

    def test_create_with_prompt(self):
        """创建带 AI 提示的计算题动作"""
        action = ReplyByCalculationProblemAction(ai_prompt="计算结果")
        assert action.ai_prompt == "计算结果"


class TestReplyByImageRecognitionAction:
    """ReplyByImageRecognitionAction 测试"""

    def test_create_default(self):
        """创建图片识别动作"""
        action = ReplyByImageRecognitionAction()
        assert action.action == SupportAction.REPLY_BY_IMAGE_RECOGNITION
        assert action.ai_prompt is None


class TestClickButtonByCalculationProblemAction:
    """ClickButtonByCalculationProblemAction 测试"""

    def test_create_default(self):
        """创建计算题按钮点击动作"""
        action = ClickButtonByCalculationProblemAction()
        assert action.action == SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM
        assert action.ai_prompt is None


class TestKeywordNotifyAction:
    """KeywordNotifyAction 测试"""

    def test_create_basic(self):
        """创建关键词通知动作"""
        action = KeywordNotifyAction(keywords=["紧急", "通知"])
        assert action.action == SupportAction.KEYWORD_NOTIFY
        assert action.keywords == ["紧急", "通知"]
        assert action.match_mode == "contains"
        assert action.ignore_case is True
        assert action.push_channel == "telegram"

    def test_create_with_all_options(self):
        """创建全参数关键词通知动作"""
        action = KeywordNotifyAction(
            keywords=["alert"],
            match_mode="regex",
            ignore_case=False,
            push_channel="bark",
            bark_url="https://api.day.app/test",
        )
        assert action.match_mode == "regex"
        assert action.ignore_case is False
        assert action.push_channel == "bark"
        assert action.bark_url == "https://api.day.app/test"


class TestSignActionBase:
    """SignAction 基类测试"""

    def test_delay_field_default(self):
        """delay 字段默认为 None"""
        action = SendTextAction(text="test")
        assert action.delay is None

    def test_delay_field_with_value(self):
        """delay 字段可设置字符串值"""
        action = SendTextAction(text="test", delay="2-5")
        assert action.delay == "2-5"


# ============================================================================
# BaseJSONConfig 测试
# ============================================================================


class TestBaseJSONConfig:
    """BaseJSONConfig 基类测试"""

    def test_valid_with_valid_data(self):
        """valid() 对有效数据返回实例"""
        data = SIGN_CONFIG_V3_BASIC
        result = SignConfigV3.valid(data)
        assert result is not None
        assert isinstance(result, SignConfigV3)

    def test_valid_with_invalid_data(self):
        """valid() 对无效数据返回 None"""
        result = SignConfigV3.valid({"invalid": "data"})
        assert result is None

    def test_valid_with_type_error(self):
        """valid() 对类型错误数据返回 None"""
        result = SignConfigV3.valid("not a dict")
        assert result is None

    def test_to_jsonable(self):
        """to_jsonable() 返回可 JSON 序列化的字典"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        result = config.to_jsonable()
        assert isinstance(result, dict)
        # 可以被 json.dumps 序列化
        json_str = json.dumps(result, ensure_ascii=False)
        assert isinstance(json_str, str)

    def test_to_jsonable_roundtrip(self):
        """to_jsonable -> 重新构造可恢复数据"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        d = config.to_jsonable()
        config2 = SignConfigV3(**d)
        assert config.sign_at == config2.sign_at
        assert len(config.chats) == len(config2.chats)

    def test_to_current_returns_self(self):
        """to_current() 默认返回自身"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        result = SignConfigV3.to_current(config)
        assert result is config

    def test_load_current_version(self):
        """load() 加载当前版本返回 (instance, False)"""
        result = SignConfigV3.load(SIGN_CONFIG_V3_BASIC)
        assert result is not None
        instance, was_migrated = result
        assert isinstance(instance, SignConfigV3)
        assert was_migrated is False

    def test_load_returns_none_for_invalid(self):
        """load() 对无效数据返回 None"""
        result = SignConfigV3.load({"completely": "invalid"})
        assert result is None

    def test_version_class_var(self):
        """BaseJSONConfig 版本 ClassVar 默认值"""
        assert BaseJSONConfig.version == 0
        assert BaseJSONConfig.is_current is False

    def test_sign_config_v3_class_vars(self):
        """SignConfigV3 类变量正确"""
        assert SignConfigV3.version == 3
        assert SignConfigV3.is_current is True
        assert SignConfigV2 in SignConfigV3.olds


# ============================================================================
# SignChatV3 测试
# ============================================================================


class TestSignChatV3:
    """SignChatV3 测试"""

    def test_create_basic(self):
        """创建基本聊天配置"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text="签到")],
        )
        assert chat.chat_id == -1001234567890
        assert chat.name is None
        assert chat.delete_after is None
        assert len(chat.actions) == 1
        assert chat.action_interval == 1

    def test_create_with_all_fields(self):
        """创建全字段聊天配置"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            name="测试群",
            delete_after=60,
            actions=[
                SendTextAction(text="签到"),
                ClickKeyboardByTextAction(text="确认"),
            ],
            action_interval=2.5,
            message_thread_id=42,
        )
        assert chat.name == "测试群"
        assert chat.delete_after == 60
        assert len(chat.actions) == 2
        assert chat.action_interval == 2.5
        assert chat.message_thread_id == 42

    def test_repr(self):
        """__repr__ 输出包含关键信息"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text="签到")],
        )
        repr_str = repr(chat)
        assert "SignChatV3" in repr_str
        assert "-1001234567890" in repr_str
        assert "1 actions" in repr_str

    def test_str_contains_box_drawing(self):
        """__str__ 输出包含边框字符和关键信息"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            name="测试群",
            actions=[SendTextAction(text="签到")],
        )
        str_output = str(chat)
        assert "╔" in str_output
        assert "╚" in str_output
        assert "-1001234567890" in str_output
        assert "测试群" in str_output

    def test_str_with_send_text_action(self):
        """__str__ 正确展示 SendTextAction 细节"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text="签到打卡")],
        )
        str_output = str(chat)
        assert "签到打卡" in str_output

    def test_str_with_long_text_truncated(self):
        """__str__ 截断长文本"""
        long_text = "a" * 20
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text=long_text)],
        )
        str_output = str(chat)
        # 15 chars + "..." 应出现
        assert "a" * 15 + "..." in str_output

    def test_str_with_dice_action(self):
        """__str__ 正确展示 SendDiceAction 细节"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendDiceAction(dice="🎲")],
        )
        str_output = str(chat)
        assert "🎲" in str_output

    def test_str_with_click_keyboard_action(self):
        """__str__ 正确展示 ClickKeyboardByTextAction 细节"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[ClickKeyboardByTextAction(text="确认")],
        )
        str_output = str(chat)
        assert "确认" in str_output

    def test_multiple_actions_display(self):
        """__str__ 展示多个动作"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[
                SendTextAction(text="签到"),
                ClickKeyboardByTextAction(text="确认"),
                SendDiceAction(dice="🎯"),
            ],
        )
        str_output = str(chat)
        assert "1." in str_output
        assert "2." in str_output
        assert "3." in str_output

    def test_requires_ai_false_for_text_only(self):
        """纯文本动作不需要 AI"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text="签到")],
        )
        assert chat.requires_ai is False

    def test_requires_ai_true_for_choose_image(self):
        """ChooseOptionByImageAction 需要 AI"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[ChooseOptionByImageAction()],
        )
        assert chat.requires_ai is True

    def test_requires_ai_true_for_calculation(self):
        """ReplyByCalculationProblemAction 需要 AI"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[ReplyByCalculationProblemAction()],
        )
        assert chat.requires_ai is True

    def test_requires_ai_true_for_image_recognition(self):
        """ReplyByImageRecognitionAction 需要 AI"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[ReplyByImageRecognitionAction()],
        )
        assert chat.requires_ai is True

    def test_requires_ai_true_for_button_calc(self):
        """ClickButtonByCalculationProblemAction 需要 AI"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[ClickButtonByCalculationProblemAction()],
        )
        assert chat.requires_ai is True

    def test_requires_updates_false_for_text_only(self):
        """纯文本动作不需要 updates"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text="签到")],
        )
        assert chat.requires_updates is False

    def test_requires_updates_true_for_click_keyboard(self):
        """ClickKeyboardByTextAction 需要 updates"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[ClickKeyboardByTextAction(text="确认")],
        )
        assert chat.requires_updates is True

    def test_requires_updates_true_for_keyword_notify(self):
        """KeywordNotifyAction 需要 updates"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[KeywordNotifyAction(keywords=["test"])],
        )
        assert chat.requires_updates is True

    def test_requires_ai_mixed_actions(self):
        """混合动作中只要有一个 AI 动作就返回 True"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[
                SendTextAction(text="签到"),
                ChooseOptionByImageAction(),
            ],
        )
        assert chat.requires_ai is True

    def test_multi_action_config(self):
        """多动作配置正确创建"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[
                SendTextAction(text="签到"),
                ClickKeyboardByTextAction(text="确认"),
            ],
            action_interval=2,
        )
        assert len(chat.actions) == 2
        assert isinstance(chat.actions[0], SendTextAction)
        assert isinstance(chat.actions[1], ClickKeyboardByTextAction)
        assert chat.action_interval == 2

    def test_serialization_roundtrip(self):
        """序列化 -> 反序列化数据一致"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            name="测试群",
            actions=[
                SendTextAction(text="签到"),
                ClickKeyboardByTextAction(text="确认"),
            ],
        )
        d = chat.to_jsonable()
        chat2 = SignChatV3(**d)
        assert chat.chat_id == chat2.chat_id
        assert chat.name == chat2.name
        assert len(chat.actions) == len(chat2.actions)

    def test_empty_actions_list(self):
        """空动作列表可以创建"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[],
        )
        assert len(chat.actions) == 0
        assert chat.requires_ai is False
        assert chat.requires_updates is False


# ============================================================================
# SignConfigV3 测试
# ============================================================================


class TestSignConfigV3:
    """SignConfigV3 测试"""

    def test_create_basic(self):
        """创建基本配置"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        assert len(config.chats) == 1
        assert config.sign_at == "0 6 * * *"
        assert config.random_seconds == 0
        assert config.sign_interval == 1

    def test_create_multi_chat(self):
        """创建多聊天配置"""
        config = SignConfigV3(**SIGN_CONFIG_V3_MULTI_CHAT)
        assert len(config.chats) == 2
        assert config.chats[0].chat_id == -1001234567890
        assert config.chats[1].chat_id == -1009876543210

    def test_create_with_dice_action(self):
        """创建骰子动作配置"""
        config = SignConfigV3(**SIGN_CONFIG_V3_DICE)
        assert len(config.chats) == 1
        action = config.chats[0].actions[0]
        assert isinstance(action, SendDiceAction)
        assert action.dice == "🎲"

    def test_create_multi_action(self):
        """创建多动作配置"""
        config = SignConfigV3(**SIGN_CONFIG_V3_MULTI_ACTION)
        chat = config.chats[0]
        assert len(chat.actions) == 2
        assert isinstance(chat.actions[0], SendTextAction)
        assert isinstance(chat.actions[1], ClickKeyboardByTextAction)

    def test_create_with_ai_actions(self):
        """创建带 AI 动作的配置"""
        config = SignConfigV3(**SIGN_CONFIG_V3_WITH_AI)
        chat = config.chats[0]
        assert len(chat.actions) == 3
        assert isinstance(chat.actions[0], SendTextAction)
        assert isinstance(chat.actions[1], ChooseOptionByImageAction)
        assert isinstance(chat.actions[2], ReplyByCalculationProblemAction)

    def test_create_with_keyword_action(self):
        """创建带关键词监听动作的配置"""
        config = SignConfigV3(**SIGN_CONFIG_V3_WITH_KEYWORD)
        chat = config.chats[0]
        assert len(chat.actions) == 1
        action = chat.actions[0]
        assert isinstance(action, KeywordNotifyAction)
        assert action.keywords == ["紧急", "通知"]

    def test_requires_ai_delegates_to_chats(self):
        """requires_ai 属性委托给子聊天"""
        config = SignConfigV3(**SIGN_CONFIG_V3_WITH_AI)
        assert config.requires_ai is True

    def test_requires_ai_false_for_text_only(self):
        """纯文本配置不需要 AI"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        assert config.requires_ai is False

    def test_requires_updates_delegates_to_chats(self):
        """requires_updates 属性委托给子聊天"""
        config = SignConfigV3(**SIGN_CONFIG_V3_MULTI_ACTION)
        assert config.requires_updates is True

    def test_requires_updates_false_for_text_only(self):
        """纯文本配置不需要 updates"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        assert config.requires_updates is False

    def test_requires_updates_true_for_keyword(self):
        """关键词监听配置需要 updates"""
        config = SignConfigV3(**SIGN_CONFIG_V3_WITH_KEYWORD)
        assert config.requires_updates is True

    def test_serialization_roundtrip(self):
        """完整配置序列化 -> 反序列化数据一致"""
        config = SignConfigV3(**SIGN_CONFIG_V3_MULTI_ACTION)
        d = config.to_jsonable()
        config2 = SignConfigV3(**d)
        assert config.sign_at == config2.sign_at
        assert config.random_seconds == config2.random_seconds
        assert config.sign_interval == config2.sign_interval
        assert len(config.chats) == len(config2.chats)

    def test_json_serializable(self):
        """配置可直接 JSON 序列化"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        d = config.to_jsonable()
        json_str = json.dumps(d, ensure_ascii=False)
        assert isinstance(json_str, str)
        # 反序列化后可以重新构造
        d2 = json.loads(json_str)
        config2 = SignConfigV3(**d2)
        assert config.sign_at == config2.sign_at

    def test_valid_from_dict(self):
        """valid() 从字典创建实例"""
        result = SignConfigV3.valid(SIGN_CONFIG_V3_BASIC)
        assert result is not None
        assert isinstance(result, SignConfigV3)

    def test_load_current_version(self):
        """load() 加载当前版本"""
        result = SignConfigV3.load(SIGN_CONFIG_V3_BASIC)
        assert result is not None
        instance, was_migrated = result
        assert isinstance(instance, SignConfigV3)
        assert was_migrated is False

    def test_default_values(self):
        """默认值正确设置"""
        config = SignConfigV3(
            chats=[SignChatV3(chat_id=1, actions=[SendTextAction(text="t")])],
            sign_at="0 6 * * *",
        )
        assert config.random_seconds == 0
        assert config.sign_interval == 1

    def test_version_field(self):
        """_version 字段固定为 3"""
        config = SignConfigV3(**SIGN_CONFIG_V3_BASIC)
        assert config._version == 3


# ============================================================================
# 版本迁移测试
# ============================================================================


class TestVersionMigration:
    """版本迁移测试"""

    def test_sign_config_v2_to_v3_basic(self):
        """SignConfigV2 迁移到 SignConfigV3"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                    "as_dice": False,
                }
            ],
            "sign_at": "0 6 * * *",
            "random_seconds": 30,
            "sign_interval": 2,
        }
        v2 = SignConfigV2.valid(v2_data)
        assert v2 is not None
        v3 = SignConfigV2.to_current(v2)
        assert isinstance(v3, SignConfigV3)
        assert len(v3.chats) == 1
        assert v3.sign_at == "0 6 * * *"
        assert v3.random_seconds == 30
        assert v3.sign_interval == 2
        # 应转换为 SendTextAction
        assert isinstance(v3.chats[0].actions[0], SendTextAction)
        assert v3.chats[0].actions[0].text == "签到"

    def test_sign_config_v2_to_v3_dice(self):
        """SignConfigV2 骰子迁移"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "🎲",
                    "as_dice": True,
                }
            ],
            "sign_at": "0 9 * * *",
        }
        v2 = SignConfigV2.valid(v2_data)
        v3 = SignConfigV2.to_current(v2)
        assert isinstance(v3.chats[0].actions[0], SendDiceAction)
        assert v3.chats[0].actions[0].dice == "🎲"

    def test_sign_config_v2_to_v3_with_button_click(self):
        """SignConfigV2 按钮点击迁移"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                    "text_of_btn_to_click": "确认",
                }
            ],
            "sign_at": "0 6 * * *",
        }
        v2 = SignConfigV2.valid(v2_data)
        v3 = SignConfigV2.to_current(v2)
        assert len(v3.chats[0].actions) == 2
        assert isinstance(v3.chats[0].actions[0], SendTextAction)
        assert isinstance(v3.chats[0].actions[1], ClickKeyboardByTextAction)

    def test_sign_config_v2_to_v3_with_image(self):
        """SignConfigV2 图片识别迁移"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                    "choose_option_by_image": True,
                }
            ],
            "sign_at": "0 6 * * *",
        }
        v2 = SignConfigV2.valid(v2_data)
        v3 = SignConfigV2.to_current(v2)
        assert len(v3.chats[0].actions) == 2
        assert isinstance(v3.chats[0].actions[1], ChooseOptionByImageAction)

    def test_sign_config_v2_to_v3_with_calculation(self):
        """SignConfigV2 计算题迁移"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                    "has_calculation_problem": True,
                }
            ],
            "sign_at": "0 6 * * *",
        }
        v2 = SignConfigV2.valid(v2_data)
        v3 = SignConfigV2.to_current(v2)
        assert len(v3.chats[0].actions) == 2
        assert isinstance(v3.chats[0].actions[1], ReplyByCalculationProblemAction)

    def test_sign_config_v2_to_v3_multi_chat(self):
        """SignConfigV2 多聊天迁移"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                },
                {
                    "chat_id": -1009876543210,
                    "sign_text": "打卡",
                },
            ],
            "sign_at": "0 6 * * *",
        }
        v2 = SignConfigV2.valid(v2_data)
        v3 = SignConfigV2.to_current(v2)
        assert len(v3.chats) == 2
        assert v3.chats[0].actions[0].text == "签到"
        assert v3.chats[1].actions[0].text == "打卡"

    def test_load_v2_data_returns_v3(self):
        """load() 自动将 V2 数据迁移到 V3"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                }
            ],
            "sign_at": "0 6 * * *",
        }
        result = SignConfigV3.load(v2_data)
        assert result is not None
        instance, was_migrated = result
        assert isinstance(instance, SignConfigV3)
        assert was_migrated is True

    def test_sign_config_v1_to_v2(self):
        """SignConfigV1 迁移到 SignConfigV2"""
        v1_data = {
            "version": 1,
            "chat_id": -1001234567890,
            "sign_text": "签到",
            "sign_at": "06:00:00",
            "random_seconds": 30,
        }
        v1 = SignConfigV1.valid(v1_data)
        assert v1 is not None
        v2 = SignConfigV1.to_current(v1)
        assert isinstance(v2, SignConfigV2)
        assert len(v2.chats) == 1
        assert v2.chats[0].chat_id == -1001234567890
        assert v2.chats[0].sign_text == "签到"

    def test_load_v1_data_requires_manual_chain(self):
        """load() 不支持跨两代迁移（V1 -> V3 需手动经过 V2）"""
        v1_data = {
            "version": 1,
            "chat_id": -1001234567890,
            "sign_text": "签到",
            "sign_at": "06:00:00",
            "random_seconds": 30,
        }
        # load() 只检查一层 olds（SignConfigV2），V1 数据不匹配 V2 格式
        result = SignConfigV3.load(v1_data)
        assert result is None

    def test_v1_to_v3_full_chain(self):
        """V1 -> V2 -> V3 完整迁移链"""
        v1_data = {
            "version": 1,
            "chat_id": -1001234567890,
            "sign_text": "签到",
            "sign_at": "06:00:00",
            "random_seconds": 30,
        }
        v1 = SignConfigV1.valid(v1_data)
        assert v1 is not None
        # V1 -> V2 -> V3 完整迁移
        v2 = SignConfigV1.to_current(v1)
        v3 = SignConfigV2.to_current(v2)
        assert isinstance(v3, SignConfigV3)
        assert len(v3.chats) == 1
        assert v3.chats[0].actions[0].text == "签到"
        assert v3.random_seconds == 30

    def test_v2_delete_after_preserved(self):
        """V2 迁移保留 delete_after 字段"""
        v2_data = {
            "version": 2,
            "chats": [
                {
                    "chat_id": -1001234567890,
                    "sign_text": "签到",
                    "delete_after": 60,
                }
            ],
            "sign_at": "0 6 * * *",
        }
        v2 = SignConfigV2.valid(v2_data)
        v3 = SignConfigV2.to_current(v2)
        assert v3.chats[0].delete_after == 60


# ============================================================================
# 工具函数集成测试
# ============================================================================


class TestUtilityFunctions:
    """工具函数在配置展示中的应用"""

    def test_pad_text_to_width_with_sign_chat(self):
        """pad_text_to_width 在 SignChatV3.__str__ 中正确工作"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            name="测试群",
            actions=[SendTextAction(text="签到")],
        )
        # __str__ 内部使用 pad_text_to_width，不应该抛出异常
        output = str(chat)
        assert len(output) > 0


# ============================================================================
# 边界条件和异常测试
# ============================================================================


class TestEdgeCases:
    """边界条件测试"""

    def test_sign_chat_with_all_action_types(self):
        """包含所有动作类型的聊天配置"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[
                SendTextAction(text="签到"),
                SendDiceAction(dice="🎲"),
                ClickKeyboardByTextAction(text="确认"),
                ChooseOptionByImageAction(),
                ReplyByCalculationProblemAction(),
                ReplyByImageRecognitionAction(),
                ClickButtonByCalculationProblemAction(),
            ],
        )
        assert len(chat.actions) == 7
        assert chat.requires_ai is True
        assert chat.requires_updates is True

    def test_sign_config_with_zero_interval(self):
        """sign_interval 为 0 的配置"""
        config = SignConfigV3(
            chats=[SignChatV3(chat_id=1, actions=[SendTextAction(text="t")])],
            sign_at="0 6 * * *",
            sign_interval=0,
        )
        assert config.sign_interval == 0

    def test_sign_config_with_large_random_seconds(self):
        """大 random_seconds 值"""
        config = SignConfigV3(
            chats=[SignChatV3(chat_id=1, actions=[SendTextAction(text="t")])],
            sign_at="0 6 * * *",
            random_seconds=3600,
        )
        assert config.random_seconds == 3600

    def test_negative_chat_id(self):
        """负数 chat_id（群组）"""
        chat = SignChatV3(
            chat_id=-1001234567890,
            actions=[SendTextAction(text="test")],
        )
        assert chat.chat_id == -1001234567890

    def test_positive_chat_id(self):
        """正数 chat_id（私聊）"""
        chat = SignChatV3(
            chat_id=123456789,
            actions=[SendTextAction(text="test")],
        )
        assert chat.chat_id == 123456789

    def test_send_text_action_with_empty_text(self):
        """空字符串文本动作"""
        action = SendTextAction(text="")
        assert action.text == ""

    def test_send_dice_action_with_empty_string(self):
        """空字符串骰子动作"""
        action = SendDiceAction(dice="")
        assert action.dice == ""

    def test_make_sign_config_v3_dict_default(self):
        """make_sign_config_v3_dict 工厂函数默认值"""
        d = make_sign_config_v3_dict()
        config = SignConfigV3(**d)
        assert len(config.chats) == 1
        assert config.sign_at == "0 6 * * *"

    def test_make_sign_config_v3_dict_custom(self):
        """make_sign_config_v3_dict 工厂函数自定义值"""
        d = make_sign_config_v3_dict(
            chat_ids=[-111, -222],
            sign_at="30 8 * * *",
            send_text="打卡",
        )
        config = SignConfigV3(**d)
        assert len(config.chats) == 2
        assert config.sign_at == "30 8 * * *"
        assert config.chats[0].actions[0].text == "打卡"
