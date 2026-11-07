# 小程序自动签到 (mini_app_claim)

[English](#english) | 简体中文

主动动作插件。自动获取 Telegram 机器人的小程序（Mini App）凭据并提交给打卡接口，完成每日签到与领奖，无需每天手动打开手机点进小程序。

## 功能介绍

- **自动获取凭据**：自动向 Telegram 申请当前账号在目标小程序中的合法登录凭证。
- **免人工打开**：在后台直接向签到服务器发送打卡请求，全流程无需人工点进界面。
- **遇到限流自动排队**：如果连续签到触发了 Telegram 官方操作限流（FloodWait），插件会自动等待官方规定的秒数，保障账号安全。
- **记录打卡日志**：每次签到结果、服务器回执与时间均会保存在本地，方便随时排查。

## 如何配置

在任务的动作列表中选择该插件后，只需简单填写以下内容：

| 配置项 | 参数名 | 类型 | 必填 | 默认值 | 如何填写与说明 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **目标机器人用户名** | `bot_peer` | 字符串 | 否 | 留空 | 小程序属于哪个机器人（例如 `@xxx_bot`）。如果当前打卡任务本身就是发给该机器人的，**直接留空即可**。 |
| **签到请求地址** | `claim_url` | 字符串 | **是** | `https://api.example.com/v1/claim` | 小程序完成签到的网络地址（通常由抓包或官方分享提供）。 |
| **从菜单按钮启动** | `from_bot_menu` | 开关 | 否 | `开启` | 小程序是否是点击聊天界面左下角的“Menu / 打开应用”按钮启动。默认开启即可。 |
| **遇到限流最大等待秒数** | `max_flood_wait` | 数字 | 否 | `300` | 如果账号请求频繁被限频，最多愿意等待多少秒。默认 300 秒（5分钟），超过则本次任务安全放弃。 |

---

<span id="english"></span>
# Telegram Mini App Auto Checkin (mini_app_claim)

English | [简体中文](#小程序自动签到-mini_app_claim)

Active action plugin. Automatically requests Telegram Mini App launch credentials and submits daily check-in claims without manually opening the web view.

## Features

- **Automated Claims**: Requests official WebApp launch auth data and submits check-in requests directly in the background.
- **Hands-Free**: No need to open apps on your phone or desktop client.
- **Smart Rate-Limit Backoff**: Automatically respects Telegram FloodWait rules and waits safely.
- **Local Logs & Status**: Saves claim responses and timestamps locally for debugging and history tracking.

## Configuration Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `bot_peer` | string | No | `""` | Target bot username (e.g. `@sample_bot`). Leave empty if task targets this bot. |
| `claim_url` | string | **Yes** | `https://...` | The HTTP endpoint for claiming daily rewards. |
| `from_bot_menu` | boolean | No | `true` | Whether the Mini App is launched from the bot's menu button. |
| `max_flood_wait` | number | No | `300` | Maximum seconds to wait if rate-limited by Telegram. |
