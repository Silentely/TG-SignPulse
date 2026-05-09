# 关键词监听

## 什么是关键词监听

关键词监听用于长期监听某个聊天、群组或频道中的新消息，一旦命中指定关键词，就立即执行通知、转发或后续动作。

这类任务通常使用执行模式 `listen`。

## 适用场景

- 监听机器人回执
- 监听抽奖口令
- 监听活动关键词
- 监听某条消息后再自动回复
- 监听到验证消息后继续 AI 识图或点按钮

## 匹配方式

当前支持三种匹配模式：

- `contains`：包含
- `exact`：完全匹配
- `regex`：正则表达式

默认行为：

- 监听任务默认 `ignore_case = true`
- `contains` 和 `exact` 支持换行或逗号分隔多个关键词
- `regex` 模式按“每行一个正则”处理

## 推送通道

`push_channel` 支持以下值：

### 1. `continue`

命中后继续执行动作序列。

适合：

- 监听后立刻回复文本
- 监听后继续点按钮
- 监听后调用 AI 识图或计算

### 2. `telegram`

只发送 Telegram Bot 通知。

依赖全局设置里的：

- `telegram_bot_token`
- `telegram_bot_chat_id`
- `telegram_bot_message_thread_id`，可选

### 3. `forward`

把命中的消息整理后转发到指定聊天。

支持：

- `forward_chat_id`
- `forward_message_thread_id`

### 4. `bark`

把命中消息推送到 Bark。

支持：

- `bark_url`

### 5. `custom`

把命中消息推送到自定义 URL。

支持两种方式：

- `GET` 模板 URL：URL 中可使用 `{title}`、`{body}`、`{url}`
- `POST JSON`：如果 URL 中没有模板变量，则直接发 JSON

## 后续动作

当 `push_channel = continue` 时，可以继续执行动作序列。

支持的后续动作类型为：

- `1` 发送文本
- `2` 发送骰子
- `3` 点击文字按钮
- `4` 根据图片选择选项
- `5` 回复计算题
- `6` AI 识图后回复文本
- `7` AI 计算后点击按钮

后续动作同样支持 `ai_prompt`。

## 文本模板变量

在后续文本动作里，可以使用这些变量：

| 变量 | 含义 |
| --- | --- |
| `{keyword}` | 命中的关键词或正则捕获值 |
| `{message}` | 原消息全文 |
| `{text}` | 原消息全文 |
| `{sender}` | 发送者 |
| `{chat_id}` | 来源聊天 ID |
| `{chat_title}` | 来源聊天标题 |
| `{message_id}` | 原消息 ID |
| `{url}` | 原消息链接 |
| `{task_name}` | 当前任务名 |
| `{account_name}` | 当前执行账号名 |

## 目标聊天与话题

监听规则支持：

- `chat_id`
- `message_thread_id`

如果你只想监听某个论坛话题，请填写 `message_thread_id`。否则留空即可。

## 自定义推送 URL 的 JSON 负载

当 `custom_url` 不包含模板变量时，系统会 `POST` 一个 JSON 负载，常见字段包括：

- `title`
- `body`
- `text`
- `keyword`
- `account_name`
- `task_name`
- `chat_id`
- `chat_title`
- `sender`
- `message_id`
- `url`

## 实战示例

### 示例 1：命中后只通知

- 模式：`contains`
- 关键词：`已开奖`
- 推送：`telegram`

### 示例 2：命中后继续回复

- 模式：`regex`
- 关键词：`验证码[:：]\\s*(\\w+)`
- 推送：`continue`
- 后续动作：发送文本 `{keyword}`

### 示例 3：命中后转发到指定话题

- 推送：`forward`
- `forward_chat_id`：`-1001234567890`
- `forward_message_thread_id`：目标话题 ID

## 设计建议

- 监听规则尽量按聊天拆分，避免一个任务承载太多不同语义
- 正则规则优先做小范围、强约束匹配
- 若命中后还要交互，直接使用 `continue`，不要再拆成第二个独立定时任务
- 如果命中消息来自机器人验证流程，下一步动作建议紧跟 AI 动作

