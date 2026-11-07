# 模拟打字输入状态 (typing_simulator)

[English](#english) | 简体中文

主动动作插件。在发送消息或执行签到前，向目标 Telegram 会话发送“正在输入”等状态，模拟真人打字过程。

## 功能特性

- **广播操作状态**：真实调用 Telegram `send_chat_action` 广播打字、挑选贴纸等状态。
- **持续时间保护**：限制持续时间在 `0.5s` 至 `15.0s` 范围内，防范异常超时。
- **随机浮动耗时**：可选启用随机浮动，模拟不同打字时长的自然波动。
- **限流自动等待**：遇到 Telegram 官方 FloodWait 限制时按要求等待，保障账号安全。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `duration_seconds` | number | `3.0` | 否 | 模拟打字持续时间 (0.5 - 15.0 秒) |
| `randomize` | boolean | `true` | 否 | 是否启用随机浮动（±30% 波动） |
| `action_type` | string | `typing` | 否 | 动作类型 (`typing`/`choose_sticker`/`record_voice`/`upload_photo`) |

---

<span id="english"></span>
# Typing Simulator (typing_simulator)

English | [简体中文](#模拟打字输入状态-typing_simulator)

Active action plugin. Simulates natural human chat interactions by broadcasting status actions (such as typing or choosing stickers) before sending messages.

## Features

- **Chat Action Broadcast**: Invokes Telegram `send_chat_action` to simulate typing and interaction states.
- **Duration Protection**: Enforces safe execution duration clamped between `0.5s` and `15.0s`.
- **Randomized Jitter**: Optional jitter to simulate natural human typing variance.
- **FloodWait Protection**: Safely respects Telegram rate limit penalties.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `duration_seconds` | number | `3.0` | No | Typing duration in seconds (0.5 - 15.0) |
| `randomize` | boolean | `true` | No | Whether to apply ±30% randomized variance |
| `action_type` | string | `typing` | No | Chat action type (`typing`, `choose_sticker`, etc.) |
