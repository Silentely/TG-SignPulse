# Backend 变更记录

> 从 CLAUDE.md 拆分的变更记录，保持 CLAUDE.md 精简。

| 日期 | 变更内容 |
|------|----------|
| 2026-10-07 | 核心与账号修复：新增 natural_sort_key 实现账号自然排序；tg_session 列表与 accounts 列表采用自然排序；Client 新增 _safe_close_client 妥善捕获未连接异常并在 finally 中释放 SQLite 锁；rename_account 覆盖 0 字节无效目标并同步迁移头像缓存；list_accounts 与 account_exists 过滤并清理 0 字节幽灵 session 避免客户端初始化异常（Issue #12） |
| 2026-08-05 | /ccg:init 二轮：CRUD/config_build/group/chats 专章（多账号 *、task_group_id、chats_cache） |
| 2026-08-05 | /ccg:init 补扫：写入 sign_task_runner 分阶段流水线、历史 index 落盘链、keyword_monitor 消息路径与 continue action_id 语义 |
| 2026-08-05 | /ccg:init 全仓扫描刷新 CLAUDE.md 与 .claude/index.json |
| 2026-08-05 | 文档同步：重写对外接口章节（路由清单、端点计数、批量/SSE 现状）、ORM/服务/工具层清单，删除已移除的旧版 ORM 任务体系描述 |
| 2026-06-30 | 初始化 backend 模块 CLAUDE.md |
| 2026-06-30 | 补扫：TelegramService 登录流程、4 个路由文件端点详情 |
