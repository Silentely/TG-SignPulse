# keyword_monitor 拆分说明

当前结构：

| 文件 | 职责 |
|------|------|
| `rules.py` | 规则模型、关键词/深链纯函数 |
| `runtime.py` | `KeywordMonitorService` 生命周期与 handler |
| `__init__.py` | 对外导出（含私有工具函数兼容测试） |

对外：`from backend.services.keyword_monitor import get_keyword_monitor_service`
