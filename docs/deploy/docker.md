# Docker 部署

## 镜像策略

| 触发条件 | 镜像标签 | 用途 |
|----------|----------|------|
| 分支推送 | `ghcr.io/<owner>/tg-signpulse:test-<branch>` | 测试 |
| 分支推送 | `ghcr.io/<owner>/tg-signpulse:test-<short-sha>` | 精确回溯 |
| Git 标签 `v*` | `ghcr.io/<owner>/tg-signpulse:vX.Y.Z` | 生产 |
| Git 标签 `v*` | `ghcr.io/<owner>/tg-signpulse:latest` | 生产（滚动） |

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
  ghcr.io/akasls/tg-signpulse:latest
```

### Docker Compose（推荐）

```yaml
services:
  app:
    image: ghcr.io/akasls/tg-signpulse:latest
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

### Nginx

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
