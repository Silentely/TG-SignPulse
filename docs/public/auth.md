# auth.md

> TG-SignPulse 文档站与自托管面板的 Agent 认证说明。

## 受众

本页面向需要程序化访问 **自托管 TG-SignPulse 面板 API** 的 AI Agent / 自动化客户端。  
文档站 `https://tg.cosr.eu.org` 为公开静态站点，无需认证。

## 认证模型概览

| 组件 | 说明 |
|------|------|
| 方案 | JWT Bearer（HS256） |
| 登录 | `POST /api/auth/login`（OAuth2 Password 风格） |
| Token 用法 | `Authorization: Bearer <access_token>` |
| 可选二步验证 | 用户启用 TOTP 时，登录需附带 `totp_code` |
| 发现元数据 | 见 `/.well-known/oauth-protected-resource` 与 `/.well-known/oauth-authorization-server` |

## 自托管面板注册 / 开通

面板采用 **本地管理员账号**，默认在首次启动时由环境变量创建：

1. 部署实例（Docker / 源码），设置 `ADMIN_PASSWORD`（或使用启动日志中的随机密码）。
2. 使用管理员账号登录 Web 面板或调用登录 API。
3. 在「用户设置」中可修改用户名、密码，并启用 TOTP。
4. Agent 侧：使用同一账号密码换取 JWT，再调用受保护 API。

没有公开的第三方 OAuth 客户端动态注册端点。Agent 注册 = 由管理员在面板创建/分配账号凭据。

## 登录示例

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "<password>",
  "totp_code": "123456"
}
```

成功响应：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

后续请求：

```http
GET /api/sign-tasks
Authorization: Bearer <jwt>
```

## 受保护资源范围（逻辑 scope）

面板 API 使用统一 JWT，无细粒度 OAuth scope 拆分。逻辑能力包括：

| scope 名称（文档用） | 含义 |
|----------------------|------|
| `panel.read` | 读取账号、任务、日志、运维状态 |
| `panel.write` | 创建/修改任务、触发签到、导入配置 |
| `ops.read` | 运维只读接口（版本、调度、内存） |
| `ops.write` | 备份导出、设备保活触发等 |

实际授权以服务端 JWT 校验 + 管理员账号权限为准。

## 发现文档

- Protected Resource Metadata: `/.well-known/oauth-protected-resource`
- Authorization Server Metadata: `/.well-known/oauth-authorization-server`
- OpenAPI（自托管实例）: `{panel-origin}/openapi.json`
- 服务文档: https://tg.cosr.eu.org/reference/configuration

## Agent 接入建议

1. 先读取本页与 OAuth 元数据，确认 `issuer` 与 `token_endpoint`。
2. 使用管理员提供的账号调用 `token_endpoint` / 登录接口换 token。
3. 将 token 放入 `Authorization: Bearer` 访问 `{resource}` 下的 API。
4. Token 过期后重新登录；不要在公共仓库提交密码或 JWT。
5. 文档站内容可用 `Accept: text/markdown` 获取 Markdown 正文。

## 联系与源码

- GitHub: https://github.com/Silentely/TG-SignPulse
- 文档: https://tg.cosr.eu.org/
