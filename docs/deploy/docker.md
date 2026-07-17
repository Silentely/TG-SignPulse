# Docker 部署

## 镜像策略

| 触发条件 | 镜像 / 行为 | 用途 |
|----------|--------------|------|
| `main` 推送 | **只跑测试**，不构建 Docker | 合并门禁 |
| `dev` 推送 | 测试 + 推送 `…:dev` / `…:dev-<sha>` | 开发/预发 |
| Git 标签 `v*` | 测试 + **一次**推送 `…:vX.Y.Z` + `…:latest` + `…:main` + `…:main-<sha>` | 正式发版（多架构） |
| 手动 `workflow_dispatch` | 可按当前分支构建（main 上仅 `main-<sha>`） | 应急补镜像 |

> 发版流程：`merge → main`（过测）→ 打 `vX.Y.Z` 并 push tag（出正式镜像）。`latest` / 浮动 `main` 只随正式 tag 更新。

### Actions 运行记录清理

`Docker Image` 工作流在每次运行结束时（无论测试/构建成功与否）会清理**本工作流**的历史记录：

- 至少保留最近 **3** 次已完成运行
- 删除 **3 天前**的其余已完成运行
- 无定时任务，仅随本工作流触发

## 快速部署

### docker run

```bash
docker run -d \
  --name tg-signpulse \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e APP_SECRET_KEY=$(openssl rand -base64 32) \
  -e ADMIN_PASSWORD=your_strong_password \
  ghcr.io/silentely/tg-signpulse:latest
```

### Docker Compose（推荐）

```yaml
services:
  app:
    image: ghcr.io/silentely/tg-signpulse:latest
    container_name: tg-signpulse
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      PORT: 8080
      TZ: Asia/Shanghai
      APP_DATA_DIR: /data
      APP_SECRET_KEY: replace-with-a-long-random-string
      ADMIN_PASSWORD: replace-with-a-strong-password
      APP_LEGACY_TASKS_READONLY: "1"
      APP_SCHEDULER_LOCK: "1"
      # APP_DATABASE_URL: postgresql+psycopg2://...
      # APP_MONITOR_SHARD: "0/2"
    mem_limit: 768m
    cpus: 1.0
    init: true
    read_only: true
    tmpfs:
      - /tmp
      - /app/__pycache__
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    stop_grace_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

启动：

```bash
docker compose up -d
```

### 上线后快速自检

```bash
curl -sS http://127.0.0.1:8080/readyz
# 期望: {"status":"ready","scheduler_lock_held":true,"legacy_tasks_writable":false,...}

curl -sS -H "Authorization: Bearer <token>" http://127.0.0.1:8080/api/ops/runtime-status
curl -sS -H "Authorization: Bearer <token>" http://127.0.0.1:8080/api/tasks/legacy-status
```

更多边界说明见 [运维手册 - 上线检查清单](../reference/ops.md#上线检查清单dev--生产)。

### 本地源码构建

仓库根目录已提供 `docker-compose.yml`，默认本地构建：

```bash
docker compose up -d --build
```

## 端口与健康检查

| 端点 | 说明 |
|------|------|
| `:8080` | 容器默认监听端口 |
| `GET /healthz` | 快速健康检查 |
| `GET /readyz` | 服务就绪检查（启动完成后返回 200） |

Docker 内置健康检查已配置，间隔 30s，超时 10s。

## 数据持久化

**必须挂载 `/data`**，否则所有数据在容器重建后丢失。

`/data` 目录包含：

```text
/data
├── db.sqlite                    # 主数据库
├── .app_secret_key              # JWT 密钥
├── .admin_bootstrap_password    # 初始密码
├── .global_settings.json        # 全局设置
├── .openai_config.json          # AI 配置
├── .telegram_api.json           # Telegram API 配置
├── logs/                        # 执行日志
├── sessions/                    # Telegram 会话
└── .signer/                     # 签到引擎数据
```

> ⚠️ 如果 `/data` 不可写，程序会降级到 `/tmp/tg-signpulse`（非持久化），仅适合临时测试。

## 权限处理

容器入口脚本会自动：

1. 检测 `/data` 挂载目录的属主 UID/GID
2. 以该 UID/GID 身份运行应用
3. 修复 `/data` 下文件的权限（确保可写）

如果不需要自动修复权限：

```bash
APP_AUTO_FIX_DATA_PERMS=0
```

默认容器用户：UID=10001, GID=10001。

## 反向代理

生产环境若需 TLS 终止、SSE / WebSocket 正确转发，请使用完整样例：

- 文档：[Nginx 反向代理](./nginx.md)
- 配置文件：`docker/nginx.conf.example`

### 最小 Nginx（仅 HTTP 反代）

```nginx
server {
    listen 80;
    server_name panel.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Caddy

```
panel.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

> 💡 使用反向代理时，建议将容器端口绑定到本地：`-p 127.0.0.1:8080:8080`  
> SSE 路径 `/api/events/` 必须关闭 `proxy_buffering`，详见 [nginx.md](./nginx.md)。

## CI/CD 缓存

镜像构建建议分层缓存：

- 前端：先复制 `frontend/package*.json` 并运行 `npm install`，再复制源码构建。
- 后端：优先缓存 Python wheel / pip 下载目录，依赖文件变化时再失效。
- Docker Buildx：启用 registry cache 或 GitHub Actions cache，减少多平台构建耗时。

预发流程建议：

1. 每次主分支构建推送 `test-<short-sha>`。
2. 预发环境显式部署该 sha 标签并验证。
3. 验证通过后再移动或发布 `staging` 标签，避免预发环境隐式漂移。

## 升级

### GHCR 镜像升级

```bash
docker compose pull
docker compose up -d
```

### 本地构建升级

```bash
git pull
docker compose up -d --build
```

> 💡 升级前建议备份 `data/` 目录。

## 安全加固

当前 `docker-compose.yml` 已包含以下安全措施：

| 措施 | 说明 |
|------|------|
| `read_only: true` | 容器文件系统只读 |
| `cap_drop: ALL` | 移除所有 Linux capabilities |
| `no-new-privileges` | 禁止提权 |
| `init: true` | 正确处理僵尸进程 |
| `tmpfs` | 临时文件写入内存 |

额外建议：

- 生产环境固定 `APP_SECRET_KEY`
- 明确设置 `ADMIN_PASSWORD`
- 启用 HTTPS（通过反向代理）
- 收紧 `APP_CORS_ALLOW_ORIGINS`
- 不要在公网长期运行 `test-*` 镜像

## 多平台支持

Docker 镜像支持：

- `linux/amd64`
- `linux/arm64`（跳过 tgcrypto 编译）

arm64 平台建议使用 `TG_SESSION_MODE=string` 以获得更好的兼容性。

## 常见问题

### 容器启动后无法写入数据

```bash
# 进入容器检查
docker exec -it tg-signpulse sh
id
ls -ld /data
touch /data/.probe && rm /data/.probe
```

如果权限不对，可以在宿主机上修复：

```bash
sudo chown -R 10001:10001 ./data
```

### 数据库锁定

SQLite 已配置 WAL 模式和 30 秒超时。如果仍然出现锁定：

1. 确认没有多个容器实例挂载同一个 `/data`
2. 检查磁盘空间是否充足
3. 考虑增大 `TG_GLOBAL_CONCURRENCY`（默认 1）
