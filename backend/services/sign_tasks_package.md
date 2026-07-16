# sign_tasks 模块化说明

当前 `backend/services/sign_tasks.py` 仍为大体量服务类，已抽出：

| 模块 | 职责 |
|------|------|
| `sign_task_failure.py` | 失败分类 |
| `sign_task_backend.py` | BackendUserSigner / TaskLogHandler |
| `sign_task_history_format.py` | 历史列表条目格式化 |
| `sign_task_text.py` | 乱码修复等文本纯函数 |
| `sign_task_config_inspect.py` | 任务配置探测（update/关键词监听） |
| `sign_tasks.py` | SignTaskService 主体（CRUD/执行/历史） |

渐进迁移原则：新逻辑优先落独立模块，再由 `SignTaskService` 调用；对外保持 `get_sign_task_service()` 不变。
