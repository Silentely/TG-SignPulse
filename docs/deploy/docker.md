# Docker 部署

## 镜像策略

仓库已经配置 GitHub Actions 自动构建 GHCR 镜像。

### 测试镜像

所有分支推送都会生成：

- `ghcr.io/<owner>/tg-signpulse:test-<branch>`
- `ghcr.io/<owner>/tg-signpulse:test-<short-sha>`

适合：

- 自测
- 预发布环境
- 验证修复是否生效

### 正式镜像

当你推送 `v*` 标签时会生成：

- `ghcr.io/<owner>/tg-signpulse:vX.Y.Z`
- `ghcr.io/<owner>/tg-signpulse:latest`

适合：

- 生产环境
- 明确版本回滚

## 推荐 Compose

```yaml
version: "3.8"

services:
  app:
    image: ghcr.io/<owner>/tg-signpulse:test-main
    container_name: tg-signpulse
    ports:
      - "8080:8080"
    environment:
      PORT: 8080
      TZ: Asia/Shanghai
      APP_DATA_DIR: /data
      APP_SECRET_KEY: replace-with-a-long-random-string
      ADMIN_PASSWORD: replace-with-a-strong-password
    volumes:
      - ./data:/data
    init: true
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    restart: unless-stopped
```

启动：

```bash
docker compose up -d
```

## 使用仓库自带 Compose

仓库根目录已经提供 `docker-compose.yml`，默认行为是本地构建镜像并启动：

```bash
docker compose up -d --build
```

适合：

- 你正在本地修改代码
- 你希望直接从工作区构建

## 重要端口

- 容器默认监听：`8080`
- 健康检查使用：`/healthz`
- 就绪检查使用：`/readyz`

## 数据持久化

请务必挂载 `/data`，否则账号会话、配置和数据库都无法长期保留。

典型数据内容包括：

- `db.sqlite`
- `.app_secret_key`
- `.admin_bootstrap_password`
- `.global_settings.json`
- `.openai_config.json`
- `.telegram_api.json`
- `sessions/`
- `logs/`
- `.signer/`

如果 `/data` 不可写，程序会自动降级到 `/tmp/tg-signpulse`。这适合临时运行，不适合长期部署。

## 权限行为

容器入口脚本会自动读取挂载目录 `/data` 的属主 UID/GID，并尽量以同样身份运行，减少 SQLite 只读或会话写入失败的问题。

如果你明确不希望自动修复权限，可以设置：

```bash
APP_AUTO_FIX_DATA_PERMS=0
```

## 反向代理

如果你要对外提供访问，建议放在 Nginx 或 Caddy 后面，并启用 HTTPS。

Nginx 示例：

```nginx
server {
  listen 80;
  server_name panel.example.com;

  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
  }
}
```

## 升级

### 使用 GHCR 镜像

```bash
docker compose pull
docker compose up -d
```

### 使用本地源码构建

```bash
git pull
docker compose up -d --build
```

升级前建议先备份 `data/` 目录。

## 健康检查

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

- `/health`：基础健康
- `/healthz`：容器健康检查
- `/readyz`：服务是否已完成启动

## 部署建议

- 生产环境固定 `APP_SECRET_KEY`
- 明确设置 `ADMIN_PASSWORD`
- 只在测试环境使用 `test-*` 镜像
- 挂载持久化 `data/`
- 配置 HTTPS 反向代理
- 按需收紧 `APP_CORS_ALLOW_ORIGINS`

