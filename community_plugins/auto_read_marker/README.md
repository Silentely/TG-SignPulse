# 会话智能已读标记器 (auto_read_marker)

[English](#english) | 简体中文

主动动作插件。在签到打卡动作执行前主动调用 Telegram `read_chat_history` 将指定会话未读红点清零，高度还原真人点进会话、浏览最新消息并进行签到的自然交互链路。

## 功能特性

- **红点智能消除**：调用 Telegram 官方协议将当前会话历史消息标为已读 (`max_id=0`)。
- **拟人阅读停顿**：支持配置 `delay_seconds`，模拟真人打开会话后停留阅读片刻的真实行为。
- **私聊作用域过滤**：可选仅在私聊会话中生效，避免误清空大型活跃群组的未读消息计数。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `delay_seconds` | number | `0.0` | 否 | 标记已读前等待的秒数 (0 为立即标记) |
| `private_only` | boolean | `false` | 否 | 是否仅对一对一私聊生效，群组和频道跳过 |

---

<span id="english"></span>
# Auto Read Marker (auto_read_marker)

English | [简体中文](#会话智能已读标记器-auto_read_marker)

Active action plugin. Proactively calls Telegram `read_chat_history` before executing sign-in tasks to clear unread badges, faithfully mimicking a human user opening the dialog, viewing recent messages, and performing sign-in.

## Features

- **Smart Badge Clearing**: Calls official Telegram protocol to mark the entire chat history as read (`max_id=0`).
- **Reading Pause Delay**: Configurable `delay_seconds` to replicate natural human reading time upon entering the chat.
- **Private Chat Filter**: Optionally limits execution strictly to private direct messages, preserving unread counts in active groups.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `delay_seconds` | number | `0.0` | No | Delay in seconds before marking chat history as read (0 for immediate) |
| `private_only` | boolean | `false` | No | Whether to execute only for one-on-one private chats |
