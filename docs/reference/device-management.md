# 设备管理功能

## 概述

设备管理功能允许用户查看和管理 Telegram 账号的已登录设备，提高账号安全性。

## 功能特性

### 1. 设备列表查看

- 查看账号所有已登录设备
- 显示设备型号、平台、IP、位置信息
- 标记当前会话和官方客户端

### 2. 设备下线

- 踢下线非当前会话的设备
- 不能踢下线当前正在使用的会话
- 操作前需要确认

### 3. 清退其他设备

- 一键调用 `account.ResetAuthorizations`，清退除当前面板会话外的**所有**已授权设备
- 会同时使此前通过「派生独立 Session」导出的会话失效
- 新登录会话处于 Telegram 初始保护期时会返回 `FRESH_RESET_AUTHORISATION_FORBIDDEN`，需数小时后再试
- 账号被其他任务占用时返回 `ACCOUNT_BUSY`（HTTP 409）

### 4. 派生独立 Session 导出

- 通过官方 `auth.ExportLoginToken` / `AcceptLoginToken` 协议派生独立 AuthKey 的 SessionString
- 可用于其他工具或脚本，不会与面板发生互踢
- 账号启用 2FA 时返回 `2FA_NOT_SUPPORTED`
- 派生失败自动回收临时授权，不残留设备

### 5. 设备保活

- 定期轻量唤醒账号会话
- 防止 6 个月不活跃被 Telegram 自动踢下线
- 可配置保活间隔（建议 30 天）
- 每天凌晨 3:30 自动执行

### 6. 官方消息查看

- 读取 Telegram 官方服务号 777000 的消息
- 查看登录验证码和安全通知
- 只读操作，不会发送消息

### 7. 批量状态检查

- 一键批量检测所有账号状态
- 显示正常/异常数量
- 异常账号显示具体错误信息

## API 接口

### 设备管理

```
GET    /api/accounts/{account_name}/devices
DELETE /api/accounts/{account_name}/devices/{auth_hash}
POST   /api/accounts/{account_name}/devices/reset-others
POST   /api/accounts/{account_name}/session-exports
```

`reset-others` 与 `session-exports` 的语义见上文「清退其他设备」「派生独立 Session 导出」；
账号不存在返回 404，账号忙返回 409 `ACCOUNT_BUSY`。

### 官方消息

```
GET /api/accounts/{account_name}/official-messages?limit=20
```

### 设备保活

```
POST /api/config/settings/device-keepalive/run
```

## 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `device_keepalive_enabled` | `true` | 是否启用设备保活 |
| `device_keepalive_interval_days` | `30` | 保活间隔天数（最大 170） |

## 使用场景

1. **安全审计**：定期检查账号登录设备，发现异常设备及时下线
2. **会话维护**：长期不活跃的账号通过保活机制避免会话过期
3. **验证码获取**：无需打开 Telegram 客户端即可获取登录验证码
4. **批量管理**：多账号场景下快速检查所有账号状态
