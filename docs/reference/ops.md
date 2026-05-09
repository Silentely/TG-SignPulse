# 运维手册

## 健康检查

系统提供三个健康端点：

| 端点 | 用途 |
| --- | --- |
| `/health` | 基础存活检查 |
| `/healthz` | 容器健康检查 |
| `/readyz` | 服务是否完成启动 |

示例：

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

当 `/readyz` 返回 `503` 时，说明应用还在启动中。

## 查看日志

### Docker 日志

```bash
docker logs -f tg-signpulse
```

### 面板内任务日志

适合查看：

- 哪一步动作失败
- AI 动作有没有拿到答案
- 按钮有没有点击成功
- 监听任务是不是命中了关键词

## 备份

最简单的备份方法就是整个备份 `data/` 目录。

重点内容：

- `db.sqlite`
- `sessions/`
- `.signer/`
- `.global_settings.json`
- `.openai_config.json`
- `.telegram_api.json`

示例：

```bash
tar -czf tg-signpulse-backup-$(date +%F).tar.gz data
```

## 恢复

1. 停止容器
2. 替换或还原 `data/`
3. 重新启动容器

```bash
docker compose down
tar -xzf tg-signpulse-backup-2026-05-09.tar.gz
docker compose up -d
```

## 升级策略

### 使用测试镜像

适合先验证：

```bash
docker compose pull
docker compose up -d
```

测试标签建议使用：

- `test-main`
- `test-<feature-branch>`
- `test-<short-sha>`

### 使用正式镜像

确认测试没问题后，再切换到：

- `vX.Y.Z`
- 或 `latest`

## 常规巡检清单

- `/readyz` 是否正常
- `data/` 是否仍可写
- 最近任务失败率是否异常升高
- 账号状态是否出现 `needs_relogin`
- 监听任务是否仍在接收更新
- 代理是否失效
- AI 接口是否还能返回结果

## 常见排障动作

### 检查数据目录可写

```bash
ls -ld data
touch data/.probe && rm data/.probe
```

### 读取首登密码

```bash
cat data/.admin_bootstrap_password
```

### 观察健康状态

```bash
watch -n 5 'curl -fsS http://127.0.0.1:8080/readyz || true'
```

## 升级前建议

- 先备份 `data/`
- 先在测试标签上验证
- 确认 AI、登录、监听、共享任务都能正常工作
- 再把生产环境切到正式标签

