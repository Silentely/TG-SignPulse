# 自动标记会话已读 (auto_read_marker)

[English](#english) | 简体中文

主动动作插件。在执行签到前自动将目标会话未读消息标记为已读，模拟真人点进会话阅读消息的习惯。

## 功能特性

- **清除未读消息**：调用 Telegram 官方协议将当前会话历史消息标为已读 (`max_id=0`)。
- **模拟阅读停留**：支持配置 `delay_seconds`，在标记已读后等待指定秒数再继续后续操作。
- **私聊范围过滤**：可选仅在私聊会话中生效，避免误清空大型活跃群组的未读消息计数。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `delay_seconds` | number | `0.0` | 否 | 标记已读前等待的秒数 (0 为立即标记) |
| `private_only` | boolean | `false` | 否 | 是否仅对一对一私聊生效，群组和频道跳过 |

---

<span id="english"></span>
# Auto Read Marker (auto_read_marker)

English | [简体中文](#自动标记会话已读-auto_read_marker)

Active action plugin. Proactively calls Telegram `read_chat_history` before executing sign-in tasks to clear unread badges, mimicking a user opening the dialog and viewing messages.

## Features

- **Badge Clearing**: Calls official Telegram protocol to mark the chat history as read (`max_id=0`).
- **Reading Pause Delay**: Configurable `delay_seconds` to replicate natural reading time upon entering the chat.
- **Private Chat Filter**: Optionally limits execution strictly to private direct messages, preserving unread counts in active groups.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `delay_seconds` | number | `0.0` | No | Delay in seconds before marking chat history as read (0 for immediate) |
| `private_only` | boolean | `false` | No | Whether to execute only for one-on-one private chats |
