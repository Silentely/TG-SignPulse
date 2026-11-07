# 签到积分记录与消息清理 (checkin_observer)

[English](#english) | 简体中文

响应式插件。自动解析签到回复中的积分变动与连续签到天数并保存到插件存储，同时支持延迟清理 Bot 回复与签到口令消息，保持会话整洁。

## 功能特性

- **积分变动解析**：根据正则表达式自动提取当前积分余额与单次获得分值，保存至插件存储（`ledger:latest_balance` 与 `ledger:last_gain`）。
- **连续签到记录**：自动提取回复中的连签天数校准 `streak:current` 与 `streak:last_date`，未提取到时根据自然日自动递增或重置。
- **消息自动清理**：在签到确认成功后，支持等待指定延迟后自动删除 Bot 回复消息与用户发送的触发口令。
- **防重复处理**：基于消息 ID 记录已处理状态（`seen:<msg_id>`），避免同一条签到回复被重复触发。
- **安全容错保护**：当消息未能匹配到签到成功状态时，保留原始消息不执行删除。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `balance_pattern` | string | 正则表达式 | 否 | 提取当前余额/总积分的正则（需包含数字捕获组） |
| `gain_pattern` | string | 正则表达式 | 否 | 提取单次获得积分的正则（需包含数字捕获组） |
| `streak_pattern` | string | 正则表达式 | 否 | 提取连续签到天数的正则（需包含整数捕获组） |
| `enable_points` | boolean | `true` | 否 | 是否启用积分变动持久化 |
| `enable_streak` | boolean | `true` | 否 | 是否启用连续签到自然日记录 |
| `enable_cleanup` | boolean | `false` | 否 | 签到完成后是否自动清理对话消息痕迹 |
| `delay_seconds` | number | `3.0` | 否 | 执行消息清理前的缓冲等待秒数 |

---

<span id="english"></span>
# Checkin Points Tracker & Cleaner (checkin_observer)

English | [简体中文](#签到积分记录与消息清理-checkin_observer)

Reactive plugin. Automatically extracts point changes and check-in streaks from bot replies into storage, with optional delayed message cleanup to keep chats tidy.

## Features

- **Points Parsing**: Extracts current balance into `ledger:latest_balance` and reward points into `ledger:last_gain` via regex.
- **Calendar Streak Tracking**: Tracks `streak:current` and `streak:last_date` from bot reply text, or automatically increments/resets according to natural calendar days.
- **Optional Message Cleanup**: Automatically deletes bot replies and user command messages after a configurable delay once check-in succeeds.
- **Idempotency Guard**: Guards executions with `seen:<msg_id>` keys to prevent duplicate event processing.
- **Safe Fallback**: If message text does not match check-in status, messages are preserved without deletion.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `balance_pattern` | string | regex | No | Regex to capture total points / balance (requires capture group) |
| `gain_pattern` | string | regex | No | Regex to capture gained points reward (requires capture group) |
| `streak_pattern` | string | regex | No | Regex to capture consecutive check-in days (requires capture group) |
| `enable_points` | boolean | `true` | No | Whether to persist parsed points |
| `enable_streak` | boolean | `true` | No | Whether to track calendar check-in streak |
| `enable_cleanup` | boolean | `false` | No | Whether to automatically delete messages upon success |
| `delay_seconds` | number | `3.0` | No | Buffer waiting time in seconds before cleaning messages |
