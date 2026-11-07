# Telegram Mini App 签到插件 (mini_app_claim)

通过 Telegram MTProto 底层接口获取合法带签名的 `initData`，并执行自动化签到流程。

## 功能特性

- **官方协议换取凭证**：调用 `messages.RequestWebView` 获取 Telegram 官方签发的合规 WebApp 凭证。
- **零篡改透传**：对 `initData` 原始载荷保持严格零篡改，确保服务端 HMAC 验签 100% 一致。
- **FloodWait 严格对齐**：遇到 Telegram 限流时，严格按服务端返回的真实秒数退避，不猜测、不硬编码。
- **状态持久化**：签到时间戳、执行状态及响应结果持久化至本地插件隔离存储库。

## 参数配置

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `bot_peer` | 字符串 | 否 | `""` | 目标 Bot 用户名或 ID（留空默认当前会话 chat_id） |
| `claim_url` | 字符串 | 是 | `https://api.example.com/v1/claim` | 接收 initData 凭证的目标 HTTP 签到接口 |
| `from_bot_menu` | 布尔值 | 否 | `true` | 是否以 Bot Menu 场景请求 WebApp |
| `max_flood_wait` | 数值 | 否 | `300` | 遇到 Telegram FloodWait 时最大允许等待秒数，超过则不重试 |

## 使用示例

在任务配置的 Action 列表中添加扩展插件，指定插件标识 `mini_app_claim` 并填入签到接口地址即可。
