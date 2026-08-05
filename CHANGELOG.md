# TG-SignPulse 变更记录

> 从 CLAUDE.md 拆分的变更记录，保持 CLAUDE.md 精简。

| 日期 | 变更内容 |
|------|----------|
| 2026-08-05 | /ccg:init 二轮补扫：tg_signer CLI 全局选项与子命令参数表；frontend Accounts/Logs/Dashboard/Settings 全链路；backend CRUD/config_build/group/chats 专章；清空 init gaps |
| 2026-08-05 | /ccg:init 补扫：sign_task_runner/历史栈、keyword_monitor continue、frontend Tasks 全链路写入模块 CLAUDE；新增 docs/tests CLAUDE；根文档补 Docker/CI 与执行摘要；architecture.md 交叉对齐；刷新 .claude/index.json |
| 2026-08-05 | /ccg:init 全仓扫描刷新 CLAUDE.md 与 .claude/index.json |
| 2026-08-05 | 文档：将根/backend/frontend 三处 CLAUDE.md 内嵌变更记录拆分至同级 CHANGELOG.md，CLAUDE.md 仅保留链接指针，减轻 AI 上下文体积 |
| 2026-08-05 | 打磨：面板全局设置重启后回灌环境变量（提取 apply_global_settings_to_env，保存与 on_startup 共用，修复 AI_VISION_TIMEOUT 等 6 项重启后静默回退默认值；删死包装函数，新增 5 条测试）；前端 Tasks 列表 last_run 收敛到统一面板时区格式化（formatTaskListDate 重复实现删除，补 UTC→HK 回归测试）；删除无消费死端点 GET /api/config/tasks 与同步 POST /api/sign-tasks/{name}/run（服务方法保留）；version_info/device_keepalive 直用 datetime.now 收敛到 utils.time；keyword_monitor 内存日志时间戳统一 UTC（updated_at 改 Z 后缀 ISO，前端可正确解析）；Login.vue 移除对本地化文案的脆弱 TOTP 判断；log_utils 删零引用死函数；文档同步 backend/CLAUDE.md 接口章节、keyword-monitor.md Server酱通道表述、根 CLAUDE.md 组件表（13→32）与 docs README 目录树。后端 1205 条测试全绿，前端 304 条/typecheck 全绿 |
| 2026-08-04 | 关键词监听重启去重：按 (账号, 会话) 持久化已处理消息水位（keyword_monitor/seen.json，30s 节流原子写盘、停机/重启加载），重连补投的旧消息不再重复命中、推送与落记录，新增 6 条测试。前端账号名解析统一收敛：resolveTaskAccountName 兼容 TaskUiItem 自动解 raw，Tasks 视图/useTaskListActions/TaskLogsModal 移除重复封装，新增 resolveTaskAccountNames 供 useTaskListRuntime 复用；修复克隆任务把 '*' 当账号名传后端的缺陷并补回归测试。后端 1186 条测试全绿，前端 304 条/typecheck/构建全绿 |
| 2026-08-04 | 打磨：删除 config 路由死类 ExportTaskResponse 与 tg_session 内 6 处不可达防御分支（_load_account_store 已归一化 accounts 为 dict）；测试密钥统一升级至 ≥32 字节消除 PyJWT InsecureKeyLengthWarning 噪音；backend/utils/tg_session 覆盖率 54%→99%（新增 68 条用例覆盖账号存储 CRUD、并发信号量、会话串旧格式、导出兜底），backend/utils/storage 覆盖率 68%→98%（新增 18 条用例）。前端：删除死导出 AccountUiStatus 与 AsyncPoolTask。后端 1162 条测试全绿且无警告，前端 301 条/typecheck 全绿 |
| 2026-08-04 | 后端：限流器补过期桶清扫（1h 陈旧/解封清理，防内存缓增）；任务运行状态迁移补 3 张内存映射；运行配置改单次读取（return_raw 消除双读，重试语义修正）；任务历史时间戳改 UTC；收敛账号解析与 JobLookupError 兜底、QR 注册失败可见化、头像缓存失败清理。前端：删除 16 个死 API 导出；会话头像 blob URL 追踪回收（列表替换/卸载统一 revoke）；会话搜索/复制提示/重登弹窗延时与 AbortController 卸载清理；DatePicker 与 AboutSettings 硬编码文案 i18n 化（含键一致性回归测试）；账号名解析收敛到共享 resolveTaskAccountName。后端 1094 条测试全绿，前端 301 条/typecheck/构建全绿 |
| 2026-08-03 | 修复任务清理竞态（cancel 后 finally 误删新条目）与日志页/会话搜索过期响应竞态（各配回归测试）；修复 F821 未导入与 config.json 非原子回写；头像 blob URL 泄漏改 AvatarUrlCache 会话复用；收敛 hits 字段截断、6 处时间格式化、账号日志双循环；清理 write-only 字段与死导出并补静默异常诊断日志。后端 1076 条测试覆盖率 52.19%，前端 299 条/typecheck/构建全绿 |
| 2026-08-03 | 任务取消不再误写失败历史/误发通知（CancelledError 单独捕获，收尾仍执行）；头像下载瞬时错误不再写 7 天无头像标记（服务层上抛与空结果区分，accounts/chat 双路由补回归测试）；AI 空结果检查修复（原 not lambda 恒 False 恒不触发）；Server酱 推送异常隔离不再中断监控匹配循环；补抓最后消息失败补诊断日志；list_accounts 三处 exists+stat 双重系统调用收敛单次 stat；清理死方法 login_sync、click text= 死分支与 __aexit__ 锁弹出竞态；前端竞态守卫/时区统一/卸载标记/死导出清理。后端 1086 条测试覆盖率 52.97%，前端 299 条/typecheck/构建全绿 |
| 2026-06-30 | 初始化根级 CLAUDE.md，含架构总览、模块索引、Mermaid 结构图 |
| 2026-06-30 | 补扫：TelegramService 登录流程、4 个后端路由、3 个前端 Views、tg_signer 核心类 |
| 2026-06-30 | 补扫：backend/utils/ 13 个工具模块、tools/ 迁移脚本、前端剩余 3 个 Views |
| 2026-06-30 | 补扫：前端 Composables、tg_signer/config.py 配置模型；验证 5 项关键发现 |
| 2026-06-30 | 补扫：tg_signer/core.py 前半段（Client 生命周期）、前端 13 个 Components；规划 token/any 修复方案 |
| 2026-07-01 | 新增账号设备管理、设备保活、官方消息查看、批量状态检查功能 |
| 2026-07-30 | 删除 pyotp 根 shim 与四处死代码；收敛凭据解析/JWT/前端通知/账号状态公共入口；批量写延迟缓存刷新；覆盖率门槛升至 40% |
| 2026-07-31 | print_exc 收敛为结构化日志并清理注释死代码；历史清理/回复解析/空备份清理等 6 处静默异常补诊断日志；修复历史运维模块乱码 docstring；print_to_user 编码兜底改为 ascii 使回退真正生效；tg_signer/utils 覆盖率 35%→100%（新增 14 条测试） |
| 2026-07-31 | 静默 except 收尾 11 处（通配任务配置写入失败升 warning，其余按级别补诊断日志，过期历史清理收窄为 OSError）；tg_signer/security 覆盖率 56%→100%（新增 18 条测试）；前端 typecheck/vitest 287 条/生产构建全绿 |
| 2026-07-31 | 集中补测长尾模块——telegram/sessions 23%→96%（登录会话释放与过期/超量清理）、tg_signer/pydantic_compat 57%→97%（鸭子类型命中 v2 分支与 dump_json）、backend/utils/task_logs 71%→98%（日志提取器全分支）；新增 23 条测试 |
| 2026-07-31 | 修复配置接口输入边界：设备保活手动执行响应补回并发提示字段；导入签到任务非法名称返回 400 且回显规范化后的落盘名称；Telegram 凭据保存时校验 api_id 为正整数；新增 10 条接口守钉测试 |
| 2026-07-31 | 攻克 sign_task_runner 覆盖率 1%→93%——FakeSvc/FakeSigner 替身穿透成功/失败/超时/重试/冷却/强失败翻转/session 双模式/补抓超时分支，新增 24 条测试，总覆盖率 46%→48% |
| 2026-07-31 | 文档一致性：tg_signer/core.py 单文件行号锚点重锚为 client.py/runtime.py 拆分后真实结构（README 中英文同步）；删除 pyproject 中已不存在 shim 文件的 per-file-ignores 死配置 |
| 2026-07-31 | 修正 tasks 指南中旧 `/api/tasks` "默认只读"过时表述（实际已完全移除，改链 FAQ）；sign_task_backend 覆盖率 54%→100%（TaskLogHandler 规范化/回退/溢出/容错与 task_dir 三级解析/交互禁令，新增 10 条测试）；前端 bundle 分析确认分包健康无需干预 |
| 2026-07-31 | 通知链路补测——sign_task_notify 10%→100%（门控/静默时段/话题 ID 解析/失败与成功推送容错/mark_account_invalid 幂等通知/check_account_before_task 预检全分支含 fail-open）、server_chan 12%→100%（标准与 sctp 双 URL、参数合并、非法 sendkey 报错）；新增 36 条测试 |
| 2026-07-31 | 提交信息规范化：未推送历史中的过程性字眼改写为描述式表述，变更记录同步去除编号前缀 |
| 2026-07-31 | 功能修复四处：设备保活间隔配置非数字值不再导致整轮 500（容错解析并夹取 1~170 天），运行中响应的 enabled 改为如实读取而非硬编码 True；账号日志 task_name 为空串时统一回落默认名并删除第二兜底；logs 路由校验式日期调用补意图注释。device_keepalive 覆盖 16%→84%（新增 13 条用例含间隔夹取/启停门控/忙响应/状态持久化），总测试 1047 条 |
| 2026-07-31 | 路由层补测——routes/accounts 33%→96%（登录/QR 全流程错误映射、批量状态 Job 增删查消、最近/账号日志映射与限长夹取、导出内容断言、设备/官方消息、头像缓存三级回退、改名更新路径）、routes/events 36%→91%（SSE 字节编码/去重键/令牌校验、事件流种子去重/兜底扫描与容错/心跳）；新增 69 条测试，总覆盖 48.86%→50.48% |
