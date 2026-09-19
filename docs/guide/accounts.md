# 账号管理

## 支持的登录方式

TG-SignPulse 当前支持以下登录流程：

- 短信验证码登录
- 二维码登录
- 会话导入（复用已有的 Telegram 会话文件或 SessionString，无需重新收码）
- 账号启用了 Telegram 2FA 时补交密码

所有登录流程都通过后端 `accounts` API 完成，登录状态会被保存到数据目录中。

## 会话导入

面板「添加账号 → 导入会话」或 `POST /api/accounts/import-session` 支持三种载荷，格式自动识别：

| 载荷 | 说明 |
|------|------|
| Telethon `.session` | 自动转换为 Pyrogram SQLite 结构 |
| Pyrogram `.session` | 直接校验并落盘 |
| Pyrogram StringSession | 转换为本地会话文件 |
| TData `.zip` | Telegram Desktop 归档，需服务端安装可选依赖（见下） |

- Telethon **StringSession 不支持**（以 `1` 开头的字符串会被拒绝），请改用 `.session` 文件或 Pyrogram StringSession。
- 导入前会先做一次 `get_me()` 首次连接校验，未授权/失效会话会被拒绝且不落盘。
- 目标账号已存在时默认拒绝（HTTP 409），需显式勾选「覆盖同名已有账号」。
- 单次上传上限 50MB；TData 归档另有限制：解压后总量 ≤ 100MB 且文件数 ≤ 1000（防解压炸弹）。

TData 转换依赖可选依赖 `opentele`：

```bash
pip install "tg-signer[tdata]"      # 或 uv sync --extra tdata
```

未安装时导入 TData 会返回 `TDATA_CONVERTER_UNAVAILABLE`，`.session` / StringSession 导入不受影响。

## 派生独立 Session 导出

设备管理弹窗中的「派生导出」通过 Telegram 官方 `auth.ExportLoginToken` / `AcceptLoginToken` 协议，
为该账号派生一个**具备独立 AuthKey** 的 SessionString，可直接用于其他工具，不会与面板互踢或导致面板掉线。

- 账号启用 2FA 时无法派生（返回 `2FA_NOT_SUPPORTED`）。
- 派生过程中账号被占用时返回 `ACCOUNT_BUSY`，可稍后重试。
- 派生失败会自动回收已授权的临时会话，不会残留多余设备。

## 代理规则

系统同时支持“全局代理”和“账号级代理”。

优先级：

1. 账号单独配置的代理
2. 全局设置中的 `global_proxy`
3. 未配置代理时直连

常见格式：

```text
socks5://127.0.0.1:1080
socks5://user:pass@127.0.0.1:1080
http://127.0.0.1:7890
```

### 代理强制与出口校验

- 全局设置 `require_proxy_for_telegram` 开启后，任何**未配置有效代理**的 Telegram 连接（登录、状态检测、设备/会话操作、签到执行、关键词监听）都会被硬阻断，错误码 `PROXY_REQUIRED_BLOCKED`。
- 代理字符串格式非法时同样阻断（`PROXY_INVALID_BLOCKED`），不会静默降级为直连。
- 配置了代理时，连接前会探测代理出口 IP 并与宿主机直连出口 IP 比对：
  - 出口 IP 与宿主机相同（即代理未生效/泄漏）→ 无条件阻断，`PROXY_PROBE_FAILED`。
  - 探测端点不可达 → 默认（`strict`）阻断 `PROXY_PROBE_UNAVAILABLE`；账号级 `proxy_probe_policy` 设为 `warn` 时记录告警并放行。
  - 探测结果缓存 10 分钟，避免重复探测阻塞账号操作。

## 账号字段建议

- `账号名称`：建议使用稳定、易识别的名称，例如 `main_cn`、`backup_01`
- `手机号`：短信登录时使用
- `代理`：可选，适合账号需要单独走代理的场景
- `备注`：用于在面板里区分账号用途
- `设备画像`：可选，按 desktop / android / macos / ios 预设绑定设备指纹（`device_model` / `system_version` / `app_version` / `lang_code` / `system_lang_code`），同一账号的连接会复用该画像。修改画像要求账号当前没有活跃连接，否则返回 `ACCOUNT_BUSY`。

## 二维码登录流程

1. 在面板发起二维码登录
2. 用 Telegram 手机端扫描
3. 如果 Telegram 返回 `password_required`，继续填写 2FA 密码
4. 登录成功后会自动落盘会话

适合：

- 不方便接收短信验证码
- 批量维护已有账号

## 会话存储模式

通过环境变量 `TG_SESSION_MODE` 控制：

- `file`：默认模式，使用会话文件
- `string`：使用 session string 存储

### file 模式

适合大多数场景。

- 会话更直观
- 与传统 Telegram 客户端管理方式一致
- 数据落在 `sessions/` 目录

### string 模式

适合容器化或你希望统一管理 session string 的场景。

- 账号信息保存在 `sessions/accounts.json`
- 对迁移和备份更友好

## 接收消息更新（updates）

客户端是否接收实时消息更新由系统**按任务自动决定**，无需手动配置：

- 任务包含「等待消息响应」类动作（如点击按钮后等待机器人回复、AI 识图、关键词监听）时，客户端会接收 updates；
- 仅发送文本 / 骰子等纯定时动作时，客户端以 `no_updates` 模式运行，降低资源占用。

关键词监听和某些需要实时等待消息变化的动作依赖 updates。如果监听任务不触发，优先检查任务执行模式与账号会话状态，而不是环境变量。

## 账号状态检测

面板支持检查账号状态。`status` 常见取值：

- `connected`：会话可用
- `invalid`：会话失效
- `error`：检测过程出错
- `checking`：检测进行中

另有独立布尔字段 `needs_relogin`：为 `true` 时表示需要重新登录（常见于 `status = invalid`）。

建议：

- 定期检查长期挂机账号
- `needs_relogin` 或 `invalid` 后尽快重登
- 如果任务失败集中出现在某个账号，先检查账号状态和代理

## 重新登录

当账号失效或 Telegram 要求重新验证时：

1. 打开账号编辑
2. 保留原账号名称
3. 使用短信或二维码重登
4. 成功后原任务会继续绑定该账号

## 自定义 Telegram API

如果你不想使用默认内置配置，可以在系统设置中填写自己的：

- `TG_API_ID`
- `TG_API_HASH`

也可以通过面板保存，这些值会写入 `.telegram_api.json`。

## 建议做法

- 一个账号只承担一类核心任务，便于排障
- 风险高的任务单独走代理
- 批量账号优先使用共享任务，而不是复制大量相同任务
- 长期运行时定期备份 `sessions/` 与数据库

