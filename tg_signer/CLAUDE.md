[根目录](../CLAUDE.md) > **tg_signer**

# tg_signer 模块

> Pyrogram/kurigram 封装的 Telegram 签到与监控引擎；同时作为 CLI 与 backend 执行内核。

## 变更记录 (Changelog)

> 本模块变更随根级 [`CHANGELOG.md`](../CHANGELOG.md) 记录；无独立长表。

## 模块职责

- 封装 Telegram Client 生命周期（引用计数、重连、FloodWait）
- 签到配置模型（V1→V3 迁移）与 8 类动作执行
- CLI：`tg-signer` 入口（Click）签到 / 监控
- AI 工具（OpenAI 兼容：OCR、计算、识图选按钮等）
- 通知：Server酱等
- 安全与工具：session 加密相关、异步工具、日志

包版本：`__version__ = "2.2.3"`（`tg_signer/__init__.py`）。

## 入口与启动

| 路径 | 职责 |
|------|------|
| `__main__.py` / `project.scripts: tg-signer` | CLI 入口 `signer()` → `cli.tg_signer` |
| `cli/signer.py` | 根组 `tg-signer` + 签到子命令 |
| `cli/monitor.py` | 子组 `tg-signer monitor` |
| `core/__init__.py` | 公共符号 re-export + patch 副作用 |

面板场景下通常不直接跑 CLI，而由 `backend.services.sign_task_backend.BackendUserSigner` 继承 `UserSigner` 驱动。

## CLI 命令与参数

入口：`tg-signer`（Click，`AliasedGroup`）。别名：`run_once`→`run-once`，`send_text`→`send-text`。

### 全局选项（所有子命令前）

| 选项 | 默认 / 环境变量 | 说明 |
|------|-----------------|------|
| `-l / --log-level` | `LOG_LEVEL` 或 `info` | `debug\|info\|warn\|error` |
| `--log-file` | `logs/tg-signer.log` | 日志文件 |
| `--log-dir` | `logs` | 日志目录 |
| `-p / --proxy` | `TG_PROXY` | 如 `socks5://127.0.0.1:1080` |
| `--session_dir` | `.` | session 目录 |
| `-a / --account` | `my_account` / `TG_ACCOUNT` | 账号名 → `<account>.session` |
| `-w / --workdir` | `.signer` | 配置与签到记录目录 |
| `--session-string` | `TG_SESSION_STRING` | 覆盖文件 session |
| `--in-memory` | flag | session 存内存 |

### 签到子命令（`cli/signer.py`）

| 命令 | 参数 / 选项 | 说明 |
|------|-------------|------|
| `version` | — | 打印 `tg-signer <version>` |
| `list` | — | 列出 workdir 下已有任务配置 |
| `login` | `-n/--num-of-dialogs`（默认 50） | 交互登录获取 session |
| `logout` | — | 登出并删 session |
| `run` | `TASK_NAMES...`（≥1）；`-n` 默认 50 | 按配置跑签到（可多任务顺序） |
| `run-once` | `TASK_NAME`（默认 `my_sign`）；`-n` | 强制跑一次（忽略今日已签） |
| `send-text` | `CHAT_ID TEXT`；`--delete-after` 秒 | 发文本（可定时删） |
| `send-dice` | `CHAT_ID EMOJI`；`--delete-after` | 骰子：🎲🎯🏀⚽🎳🎰 |
| `reconfig` | `TASK_NAME`（默认 `my_sign`） | 交互重配任务 |
| `list-members` | `--chat_id` 必填；`QUERY`；`--admin`；`-l` 默认 10 | 群/频道成员（username 须 `@` 前缀） |
| `export` | `TASK_NAME`；`-O/--file` | 导出配置到文件或 stdout |
| `import` | `TASK_NAME`；`-I/--file` | 从文件或 stdin 导入 |
| `schedule-messages` | `CHAT_ID TEXT`；`-C crontab` 必填；`-N next-times` 默认 1；`-RS random-seconds` 默认 0 | 配置 TG 原生定时消息 |
| `list-schedule-messages` | `CHAT_ID` | 列出已配定时消息 |
| `multi-run` | `TASK_NAME`；`-a/--account` 可重复必填；`-n` | 一套配置多账号 |
| `llm-config` | — | 交互配置 OpenAI 兼容 API（写 workdir） |

`run` / `multi-run`：独立 event loop + `_run_signers_isolated`；单任务失败记入汇总，其余继续，最后 `ClickException` 汇总。

### 监控子组（`tg-signer monitor`，`cli/monitor.py`）

| 命令 | 参数 / 选项 | 说明 |
|------|-------------|------|
| `list` | — | 列出监控配置 |
| `run` | `TASK_NAME`（默认 `my_monitor`）；`-n` 默认 20 | 常驻监听 |
| `reconfig` | `TASK_NAME`（默认 `my_monitor`） | 交互重配 |
| `export` | `TASK_NAME`；`-O` | 导出 |
| `import` | `TASK_NAME`；`-I` | 导入 |

> 帮助文案里偶见 `tg-monitor` 示例，实际入口仍是 **`tg-signer monitor ...`**。

## 包结构

```
tg_signer/
├── config.py          # SignConfig / SignAction / MonitorConfig（约 473 行）
├── ai_tools.py        # AITools、OpenAI 配置
├── compat.py          # Pyrogram 符号与重试兼容
├── core/
│   ├── client.py      # Client、get_client、close_client_by_name、_patched_invoke
│   ├── runtime.py     # BaseUserWorker、UserSigner
│   ├── signer_*.py    # runner / actions / matchers / config Mixin
│   ├── monitor.py     # UserMonitor
│   └── context.py     # UserSignerWorkerContext
├── cli/               # Click 命令
├── notification/      # server_chan 等
├── security.py / utils.py / logger.py / log_utils.py / async_utils.py
└── pydantic_compat.py
```

## 配置模型要点

- **版本链**：`SignConfigV1` → `V2` → `V3`；`BaseJSONConfig.load()` 自动迁移
- **SupportAction（8）**：SEND_TEXT、SEND_DICE、CLICK_KEYBOARD_BY_TEXT、CHOOSE_OPTION_BY_IMAGE、REPLY_BY_CALCULATION_PROBLEM、REPLY_BY_IMAGE_RECOGNITION、CLICK_BUTTON_BY_CALCULATION_PROBLEM、KEYWORD_NOTIFY
- **MonitorConfig / MatchConfig**：chat/user/text 过滤与推送字段
- 生产依赖 **pydantic v1**（`pydantic>=1.10.26,<2`），代码保留 v2 兼容分支

## Client 与 Worker

见根 `CLAUDE.md`「Client 生命周期」与 core 类表。要点：

- 全局 `_CLIENT_INSTANCES` / `_CLIENT_REFS` / `_CLIENT_ASYNC_LOCKS`
- `UserSigner` 多重继承：Runner + Actions + Matchers + Config + `BaseUserWorker[SignConfigV3]`
- 工作目录约定：`_workdir` / `_tasks_dir = "signs"`（backend 会覆盖适配）

## 对外接口（库视角）

| 符号 | 来源 | 调用方 |
|------|------|--------|
| `UserSigner` / `UserMonitor` / `get_client` | `tg_signer.core` | backend sign/monitor |
| `SignConfigV3`、动作模型 | `tg_signer.config` | 配置读写与校验 |
| `AITools` | `tg_signer.ai_tools` | 签到动作与监控回复 |
| `create_logged_task` 等 | `async_utils` | backend 后台任务 |
| CLI `tg-signer` | `__main__` | 运维/无面板场景 |

## 测试与质量

- 根 `pytest` 覆盖 `tg_signer`（`pyproject` `tool.coverage.run source`）
- 相关测试：`test_core`、`test_config`、`test_ai_tools`、`test_tg_signer_*`、`test_signer_*`、`test_server_chan` 等
- `tg_signer/__main__.py` 在 coverage omit 列表中

## 常见问题 (FAQ)

**Q: 为何拆 core 多文件？**  
A: 原单文件过大；现 `client` / `runtime` / Mixin 分离，对外 import 路径保持稳定。

**Q: 面板与 CLI 差异？**  
A: 面板用 `BackendUserSigner` 禁交互、接 TaskLogHandler 与后端目录；CLI 可交互询问配置。

## 相关文件清单

- `config.py`、`ai_tools.py`、`compat.py`
- `core/client.py`、`runtime.py`、`signer_*.py`、`monitor.py`、`context.py`
- `cli/signer.py`、`cli/monitor.py`
- `notification/server_chan.py`
- `security.py`、`utils.py`、`__main__.py`
