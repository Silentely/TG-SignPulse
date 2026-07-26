# sign_tasks 模块化说明

当前 `backend/services/sign_tasks.py` 仍为大体量服务类，已抽出：

| 模块 | 职责 |
|------|------|
| `sign_task_failure.py` | 失败分类 |
| `sign_task_backend.py` | BackendUserSigner / TaskLogHandler |
| `sign_task_history_format.py` | 历史列表/写入条目格式化、flow 截断 |
| `sign_task_history_io.py` | 历史文件路径 / 加载 / 清理 / config 目录与缓存 last_run |
| `sign_task_run_status.py` | 运行状态字典构造、取消响应与 run_id 校验 |
| `sign_task_text.py` | 乱码修复等文本纯函数 |
| `sign_task_config_inspect.py` | 任务配置探测（update/关键词监听） |
| `sign_task_message.py` | 目标消息摘要 / 线程匹配 |
| `sign_task_chats.py` | 会话缓存检索、dialog 映射、session/API 解析、缓存读写、client kwargs/映射追加 |
| `sign_task_config_build.py` | 配置字典构造、更新字段合并、账号引用改名、调度计划/账号 diff |
| `sign_task_history_query.py` | 历史条目格式化装配、日期过滤、排序截断、按时间查找 |
| `sign_tasks.py` | SignTaskService 主体（CRUD/执行/历史） |

渐进迁移原则：新逻辑优先落独立模块，再由 `SignTaskService` 调用；对外保持 `get_sign_task_service()` 不变。
