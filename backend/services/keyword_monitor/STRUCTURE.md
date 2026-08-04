# keyword_monitor 拆分说明

当前结构：

| 文件 | 职责 |
|------|------|
| `rules.py` | 规则模型、关键词/深链纯函数 |
| `sharding.py` | 多实例账号分片（ALLOWLIST / SHARD） |
| `runtime.py` | `KeywordMonitorService` 生命周期与 handler |
| `hits.py` | 命中记录 JSONL 落盘、分组与 CSV 导出 |
| `__init__.py` | 对外导出（含私有工具函数兼容测试） |

对外：`from backend.services.keyword_monitor import get_keyword_monitor_service`

## 重启去重

服务重启/重连后 Telegram 会补投停机期间的旧消息，可能造成重复命中、推送与
命中记录。`runtime.py` 按 `(账号, 会话)` 持久化已处理的最大消息 ID 水位：

- 状态文件：`<workdir>/keyword_monitor/seen.json`（原子写盘，30s 节流）
- 加载时机：`restart_from_tasks()` 启动前；落盘时机：水位推进节流、`stop()` 停机前
- 判定：`message.id <= 水位` 的消息直接跳过，不进入规则匹配与命中链路
