# 账号管理

## 支持的登录方式

TG-SignPulse 当前支持以下登录流程：

- 短信验证码登录
- 二维码登录
- 会话导入（复用已有的 Telegram 会话文件或 SessionString，无需重新收码）
- 账号启用了 Telegram 2FA 时补交密码

所有登录流程都通过后端 `accounts` API 完成，登录状态会被保存到数据目录中。

## 会话导入

在面板点击 **添加账号** → **导入会话**（对应接口 `POST /api/accounts/import-session`）支持三种载荷，格式自动识别：

| 载荷 | 说明 |
|---|---|
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

设备管理弹窗中的 **派生导出** 功能通过 Telegram 官方 `auth.ExportLoginToken` / `AcceptLoginToken` 协议， 为该账号派生一个**具备独立 AuthKey** 的 SessionString，可直接用于其他工具，不会与面板互踢或导致面板掉线。

- 账号启用 2FA 时无法派生（返回 `2FA_NOT_SUPPORTED`）。
- 派生过程中账号被占用时返回 `ACCOUNT_BUSY`，可稍后重试。
- 派生失败会自动回收已授权的临时会话，不会残留多余设备。

## 账号运行日志导出

面板支持针对指定账号的历史执行日志进行独立下载导出：

1. 进入面板 **日志** 页面；
2. 在顶部账号下拉框中选中目标账号；
3. 点击 **导出日志** 按钮；
4. 浏览器将自动下载包含该账号历史执行日志的 `.log` 文件（带有服务端推荐文件名）。

对应后端接口：`GET /api/accounts/{account_name}/logs/export`。导出的日志覆盖调度启动、账号可用性检查、会话锁流转、步骤动作调用与错误堆栈，便于针对单个账号离线分析与排障。

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

面板配置代理后，保存前会自动测试代理连通性并校验出口 IP。如果配置了「强制 Telegram 走代理」，出口 IP 与宿主机真实 IP 相同时会拒绝连接，防止 IP 泄漏。

## 会话模式与存储

每个账号支持两种会话模式：

- `file`：会话保存在 `data/sessions/<name>.session` 文件中。适合常规部署，支持断电恢复。
- `string`：会话以 SessionString 格式保存。适合无持久化盘的临时容器。

模式在添加账号时指定，后续不可更改。如需切换，建议先清退设备再重新登录。

## 设备指纹画像

新建账号或导入会话时，可选择设备画像预设（如 Desktop / Android / macOS / iOS）。系统会模拟对应的平台参数与系统版本，降低因多账号使用相同默认指纹被风控识别的概率。

## 设备保活

Telegram 会在账号超过一定时间（默认 6 个月）无任何活动时自动终止会话。

TG-SignPulse 提供自动保活能力：

- 每天凌晨 3:30 自动唤醒一次已登录账号
- 检查会话有效性并更新最后活跃时间
- 可在「系统设置」中开启或关闭保活调度，并调整保活周期（默认 30 天，最大 170 天）

## 官方消息与验证码

可以在面板直接查看 Telegram 官方服务号（ID: 777000）发送的历史消息，方便：

- 查看新登录时的安全通知
- 在不打开官方客户端的情况下获取登录验证码
- 确认账号是否被官方强制下线

该操作为只读操作，不会向官方服务号发送任何消息。
