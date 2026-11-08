<span id="chinese"></span>

# 会话消息自动清理 (chat_cleaner)

[English](#english) | [简体中文](#chinese)

响应式消息插件。在签到任务完成后，按配置延迟自动删除触发指令与 Bot 回复消息，保持个人或群聊会话的整洁与隐私。

## 功能特性

- **可配置清理延迟**：支持设定缓冲时间，确保用户有足够时间确认打卡结果后再执行删除。
- **双向消息清理**：同时支持删除 Bot 的回复消息以及关联触发的原始命令消息。
- **安全防崩容错**：当原始消息已被删除或不存在（`PluginMessageNotFoundError`）时安全忽略，不影响整体流程。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `delay_seconds` | number | `3.0` | 否 | 清理消息前的缓冲等待时间（秒） |
| `delete_bot_reply` | boolean | `true` | 否 | 是否删除 Bot 发出的响应消息 |
| `delete_trigger_command` | boolean | `true` | 否 | 是否删除用户发送的触发口令消息 |

---

<span id="english"></span>
# Auto Chat Cleaner (chat_cleaner)

English | [简体中文](#chinese)

Reactive message plugin. Automatically delays and cleans up both user command messages and bot replies after check-in, keeping chat history clean and private.

## Features

- **Configurable Cleanup Delay**: Configurable buffer wait time allowing users to view check-in results before deletion.
- **Bidirectional Cleaning**: Deletes both bot replies and the original command messages that triggered them.
- **Robust Error Handling**: Safely handles already deleted or missing messages (`PluginMessageNotFoundError`) without interrupting workflows.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `delay_seconds` | number | `3.0` | No | Buffer wait time in seconds before deleting messages |
| `delete_bot_reply` | boolean | `true` | No | Whether to delete the bot's reply message |
| `delete_trigger_command` | boolean | `true` | No | Whether to delete the original trigger command message |
