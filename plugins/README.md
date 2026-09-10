# TG-SignPulse 扩展插件目录 (Plugins)

本目录用于存放 TG-SignPulse 的自定义 Action 扩展插件（Action ID `99` / `CUSTOM_PLUGIN`）。

## 快速使用

1. **宿主机开发运行**：
   将插件目录或 `*.py` 单文件直接置于本目录（`./plugins`）。

2. **Docker 容器部署运行（推荐）**：
   由于官方 `docker-compose.yml` 默认将宿主机 `./data` 目录挂载至容器 `/data`，只需在宿主机创建 `./data/plugins/` 目录并将插件放入其中，**无需重新构建 Docker 镜像**，容器启动时会自动热加载！

## 目录与文件规范

- **目录型插件**（推荐）：
  `plugins/<plugin_name>/main.py` 或 `plugins/<plugin_name>/__init__.py`
  插件目录已自动加入 `sys.path`，内部支持多文件拆分与相对模块导入。
- **单文件插件**：
  `plugins/<plugin_name>.py`

## 内置官方精选插件库

TG-SignPulse 随包提供了丰富的开箱即用官方插件，用户可在前端表单动作中选择「自定义插件」并直接填写插件名与参数：

- **[`math_solver`](./math_solver/main.py)**：
  纯文本数学算式（如 `2*31`、`15+28`）本地秒答插件。用于处理不需要大语言模型介入的确定性验证码场景，避免产生 AI 费用与调用延迟。
  - **参数**：`reply_prefix`（可选，回复前缀如“答案是：”）。

- **[`regex_reply`](./regex_reply/main.py)**：
  通用正则表达式匹配提取与模板回复插件。支持通过正则捕获组提取验证码、动态口令，并配合模板安全秒回。
  - **参数**：`pattern`（匹配正则），`template`（回复模板，如 `code:{1}`），`timeout`（匹配等待超时）。

- **[`keyword_reactor`](./keyword_reactor/main.py)**：
  关键词监听、自动表态反应（Reaction）与快捷回复插件。当 Bot 发送包含特定关键词（如“已签到”、“任务完成”）的消息时，自动为其点赞/点爱心并可选回复。
  - **参数**：`keyword`（匹配关键词），`emoji`（表态 emoji，如 👍/❤️/🎉），`match_mode`（`contains` / `exact` / `regex`），`reply_text`（可选回复内容）。

- **[`daily_checkin_helper`](./daily_checkin_helper/main.py)**：
  通用日常签到与打卡连签辅助插件。自动发送签到口令，智能识别并点击键盘内联打卡按钮，并通过插件存储后端持久化追踪打卡连签天数与总次数。
  - **参数**：`command`（打卡命令如 `/sign`），`button_keywords`（打卡按钮模糊匹配词），`track_stats`（是否统计连签）。

详细插件开发指南请查阅：[TG-SignPulse 官方文档 - 自定义 Action 插件扩展机制](docs/guide/plugins.md)。
