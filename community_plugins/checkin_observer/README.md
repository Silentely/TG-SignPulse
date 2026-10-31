# 签到全景观察与清理卫士 (checkin_observer)

[English](#english) | 简体中文

响应式观察者插件。原子聚合积分变动解析、自然日连续签到校准与可选延迟消息清理。解决多插件同时争抢处理打卡回复导致的重复解析或状态错乱问题。

## 功能特性

- **原子积分变动解析**：根据正则表达式安全提取当前积分余额并写入 `ledger:latest_balance`，记录单次获得分值至 `ledger:last_gain`。
- **自然日连续签到校准**：自动提取回复中的连签天数校准 `streak:current` 与 `streak:last_date`，缺失文本时按自然日自动递增或重置。
- **可选消息静默清理**：在打卡确认无误后，等待缓冲延迟清理 Bot 回复消息与用户触发口令消息。
- **幂等性防护**：基于消息 ID 生成 `seen:<msg_id>` 状态锁，杜绝同一打卡事件被重复消费。
- **非破坏性故障降级**：当消息未能成功解析出签到状态时，严格保留消息现场，不执行任何删除动作。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `balance_pattern` | string | 正则表达式 | 否 | 提取当前余额/总积分的正则（需包含数字捕获组） |
| `gain_pattern` | string | 正则表达式 | 否 | 提取单次获得积分的正则（需包含数字捕获组） |
| `streak_pattern` | string | 正则表达式 | 否 | 提取连续签到天数的正则（需包含整数捕获组） |
| `enable_points` | boolean | `true` | 否 | 是否启用积分变动持久化 |
| `enable_streak` | boolean | `true` | 否 | 是否启用连续签到自然日校准 |
| `enable_cleanup` | boolean | `false` | 否 | 打卡完成后是否自动清理对话消息痕迹 |
| `delay_seconds` | number | `3.0` | 否 | 执行消息清理前的缓冲等待秒数 |

---

<span id="english"></span>
# Checkin Observer & Cleaner Guard (checkin_observer)

English | [简体中文](#签到全景观察与清理卫士-checkin_observer)

Reactive observer plugin. Atomically aggregates point change extraction, calendar check-in streak calibration, and optional delayed message cleanup, preventing race conditions across multiple plugins.

## Features

- **Atomic Points Parsing**: Securely parses current balance into `ledger:latest_balance` and single-gain rewards into `ledger:last_gain` via regex.
- **Calendar Streak Calibration**: Calibrates `streak:current` and `streak:last_date` from bot reply text, or automatically increments/resets according to natural calendar days.
- **Optional Trace Cleanup**: Safely deletes both bot replies and user command messages after a configurable delay once check-in succeeds.
- **Idempotency Guard**: Guards event executions with `seen:<msg_id>` keys to prevent duplicate event consumption.
- **Non-destructive Safety**: If message text fails check-in parsing, message traces are strictly preserved without triggering deletion.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `balance_pattern` | string | regex | No | Regex to capture total points / balance (requires capture group) |
| `gain_pattern` | string | regex | No | Regex to capture gained points reward (requires capture group) |
| `streak_pattern` | string | regex | No | Regex to capture consecutive check-in days (requires capture group) |
| `enable_points` | boolean | `true` | No | Whether to persist parsed points |
| `enable_streak` | boolean | `true` | No | Whether to calibrate calendar check-in streak |
| `enable_cleanup` | boolean | `false` | No | Whether to automatically delete messages upon success |
| `delay_seconds` | number | `3.0` | No | Buffer waiting time in seconds before cleaning messages |
