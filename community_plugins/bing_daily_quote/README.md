# 必应每日一图与早安语 (bing_daily_quote)

[English](#english) | 简体中文

主动执行型插件。每天在定时打卡流中调用，自动获取微软必应 (Bing) 今日壁纸背景故事、地点与格言，并发送至指定 Telegram 会话。

## 适用场景

- 晨间自动打卡时，附带每日问候语，让打卡行为更自然，模拟真实用户的日常早起问候。
- 定时向群组播报每日一句名言或今日壁纸故事。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `greeting_prefix` | string | `☀️ 每日晨安名言：` | 否 | 消息顶部的问候引导语 |
| `include_copyright` | boolean | `true` | 否 | 是否在名言下方附加必应摄影地点与版权文字 |

---

<span id="english"></span>
# Bing Daily Quote (bing_daily_quote)

English | [简体中文](#必应每日一图与早安语-bing_daily_quote)

Active plugin. Fetches Microsoft Bing daily wallpaper stories and quotes, sending a photo message to the specified Telegram chat.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `greeting_prefix` | string | `☀️ 每日晨安名言：` | No | Greeting message prefix |
| `include_copyright` | boolean | `true` | No | Whether to include wallpaper copyright and location info |
