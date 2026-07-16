# telegram 拆分说明

当前结构（mixin 组合）：

| 文件 | 职责 |
|------|------|
| `runtime.py` | `TelegramService` 组合入口 + `get_telegram_service` |
| `sessions.py` | 登录临时 session 与清理 |
| `accounts.py` | 账号列表/状态/头像/删除/重命名 |
| `login_phone.py` | 手机号登录 |
| `login_qr.py` | 扫码登录 |
| `devices.py` | 设备管理与官方消息 |

对外：`from backend.services.telegram import get_telegram_service`
