# 拟人打字状态模拟器 (typing_simulator)

[English](#english) | 简体中文

主动动作插件。在打卡指令执行前，向目标 Telegram 会话发送拟人化的操作状态动画（如正在打字、挑选贴纸等），并持续拟人化时间，消除机器人瞬间响应与直发行为特征，提升账号防封等级。

## 功能特性

- **拟人化打字广播**：真实调用 Telegram `send_chat_action` 广播打字、挑选贴纸等状态。
- **安全持续时间钳制**：底层严格限制持续时间在 `0.5s` 至 `15.0s` 范围内，防范异常超时。
- **随机抖动浮动**：可选启用随机浮动，还原真人打字耗时波动。
- **FloodWait 机制贯通**：严格遵循官方限流惩罚规范，触发限频立即安全透传。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `duration_seconds` | number | `3.0` | 否 | 模拟打字持续时间 (范围 0.5s ~ 15.0s) |
| `randomize` | boolean | `true` | 否 | 是否启用 +/-20% 随机浮动抖动 |
| `action_type` | select | `typing` | 否 | Telegram 动作类型 (`typing`, `choose_sticker`, `record_voice`, `upload_photo`) |

---

<span id="english"></span>
# Humanized Typing Simulator (typing_simulator)

English | [简体中文](#拟人打字状态模拟器-typing_simulator)

Active action plugin. Proactively sends realistic chat status indicators (such as typing or choosing a sticker) to the target Telegram chat before signing actions, eliminating robotic instant-messaging fingerprints and significantly enhancing anti-ban safety.

## Features

- **Realistic Chat Action Simulation**: Broadcasts genuine Telegram `send_chat_action` indicators (typing, choosing sticker, etc.).
- **Safe Duration Clamping**: Strictly clamps simulation duration between `0.5s` and `15.0s`.
- **Randomized Jitter**: Optional +/-20% variation to mimic human typing rhythm variations.
- **FloodWait Propagation**: Honors Telegram rate limit exceptions and safely propagates backpressure.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `duration_seconds` | number | `3.0` | No | Duration of typing animation in seconds (0.5s - 15.0s) |
| `randomize` | boolean | `true` | No | Whether to apply randomized jitter variation |
| `action_type` | select | `typing` | No | Telegram chat action (`typing`, `choose_sticker`, `record_voice`, `upload_photo`) |
