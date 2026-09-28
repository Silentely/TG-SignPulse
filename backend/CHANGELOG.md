# Backend 变更记录

> 从 CLAUDE.md 拆分的变更记录，保持 CLAUDE.md 精简。

| 日期 | 变更内容 |
|------|----------|
| 2026-09-28 | 安全加固：JWT 令牌世代号吊销（改密/登出自增 token_epoch，签发嵌入 tep 声明，缺失或不匹配即 401）；关键词正则 ReDoS 防护（静态判据 + 4096 字符截断 + regex_match_deadline 墙钟上限，写入侧与运行期同判据）；出站 URL 公网校验（WebDAV/S3/推送 webhook 统一复用 validate_public_http_url，保存即拒绝内网与元数据端点）；备份归档权限收敛（0600/0700，tar.add filter 归一成员权限）；配置导出递归脱敏（Bark 密钥/自定义 URL 内嵌凭据/Server 酱 sendkey/转发回调鉴权头，导入侧对称丢弃占位）；全局代理只回传 global_proxy_set；ChatOps 增加发送者 user_id 白名单与默认关闭；通配任务删除整体生效（剥离 * 标记 + 删除记录 + 后置条件复验）；atomic_io 新增 path_write_lock，CRUD/expand/last_run 回写全程持锁；历史文件名对 _ 与 % 做可逆编码；插件 AST 门禁改为按严重度失败关闭，市场安装强制 sha256 且成员后缀白名单，forward_messages 钉死源会话 |
| 2026-08-05 | /ccg:init 二轮：CRUD/config_build/group/chats 专章（多账号 *、task_group_id、chats_cache） |
| 2026-08-05 | /ccg:init 补扫：写入 sign_task_runner 分阶段流水线、历史 index 落盘链、keyword_monitor 消息路径与 continue action_id 语义 |
| 2026-08-05 | /ccg:init 全仓扫描刷新 CLAUDE.md 与 .claude/index.json |
| 2026-08-05 | 文档同步：重写对外接口章节（路由清单、端点计数、批量/SSE 现状）、ORM/服务/工具层清单，删除已移除的旧版 ORM 任务体系描述 |
| 2026-06-30 | 初始化 backend 模块 CLAUDE.md |
| 2026-06-30 | 补扫：TelegramService 登录流程、4 个路由文件端点详情 |
