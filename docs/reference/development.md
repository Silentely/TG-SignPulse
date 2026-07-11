# 开发规范

## 框架版本要求

当前后端运行基线：

| 组件 | 要求 |
| --- | --- |
| Python | `>=3.10,<3.14` |
| FastAPI | `>=0.109.2` |
| Pydantic | 当前依赖锁定为 `pydantic<2` |
| SQLAlchemy | 当前使用 1.x 风格 API |
| APScheduler | 进程内调度器，单后端实例运行 |

新增代码必须兼容 Python 3.10，不使用 3.11+ 专属语法。

## Pydantic 使用规范

当前项目仍运行在 Pydantic v1：

- 使用 `BaseModel`、`Field`、`validator` 等 v1 API。
- 不要在生产代码中直接引入 v2 专属的 `field_validator`、`ConfigDict` 或 `model_validate`，除非同时提供兼容层。
- 对外 API schema 保持字段名稳定，新增字段优先设为可选并提供默认值。
- 输入模型必须做边界校验，例如空字符串、超长文本、非法 URL 和非法枚举值。

如果后续迁移到 Pydantic v2：

- 用兼容模块集中封装 `model_dump` / `dict`、`model_validate` / `parse_obj` 差异。
- 先迁移测试覆盖充分的边界模型，再迁移核心任务配置模型。
- 不在业务服务中散落版本判断。

## SQLAlchemy 使用规范

当前项目使用 SQLAlchemy 1.x 风格：

- 路由层通过依赖注入获取 `Session`。
- 服务函数接收显式 `Session`，不要在深层函数里隐式创建连接。
- 写操作必须提交或回滚清晰，异常路径不要留下未关闭 session。
- 查询结果对外返回前转换为 Pydantic / dict，不直接暴露 ORM 对象给前端。

新增索引或约束时需要同时说明查询场景、影响的写入路径和对已有数据的兼容性。

## 日志规范

- 使用模块级 logger，例如 `logging.getLogger("backend.tasks")`。
- 不记录明文 token、密码、API key、session string、验证码。
- 面向用户的任务日志写清楚动作、目标和失败原因。
- 异常日志保留上下文，但避免把完整请求体或密钥写入日志。
- 日志级别遵循：调试细节用 `DEBUG`，状态变化用 `INFO`，可恢复异常用 `WARNING`，功能失败用 `ERROR`。

## 类型注解规范

- 新增函数必须标注参数和返回值。
- Python 3.10 使用内置泛型：`dict[str, Any]`、`list[str]`。
- 可空值使用 `Optional[T]` 或 `T | None`，同一文件内保持一致。
- 对 JSON-like 配置使用 `dict[str, Any]`，不要用裸 `dict` 扩散到新代码。
- 公共服务方法的返回类型要表达失败语义，例如 `Optional[dict[str, Any]]` 或显式结果对象。

## 代码变更原则

- 优先保持现有模块边界，避免把路由、持久化和执行逻辑混在一起。
- 文件写入使用原子写入或明确锁保护，避免损坏用户配置。
- 后台任务必须记录异常，不能让 `asyncio.create_task` 的异常静默丢失。
- 新增环境变量必须同步更新 `docs/reference/configuration.md`。
- 涉及部署行为的变更必须同步更新 `docs/deploy/docker.md` 或 `docs/reference/ops.md`。

## 测试规范

### 测试基础设施

测试目录 `tests/` 下包含完整的测试基础设施：

| 目录/文件 | 说明 |
| --- | --- |
| `conftest.py` | 全局 fixtures（数据库会话、测试客户端、Mock 对象） |
| `fixtures/` | 预定义测试数据（账号、任务、消息） |
| `mocks/` | Mock 对象（Telegram 客户端、数据库会话、AI 服务） |
| `factories/` | 测试数据工厂（AccountFactory、TaskFactory 等） |
| `utils/` | 测试辅助函数（时间工具、环境管理、断言增强） |

### 运行测试

```bash
# 运行全部测试
pytest

# 运行指定模块
pytest tests/test_core.py -v

# 运行并查看覆盖率
pytest --cov=tg_signer --cov-report=term-missing

# 跳过覆盖率阈值检查（用于新增 backend/ 模块测试）
pytest --no-cov
```

### 前端测试

前端使用 Vitest 进行单元测试：

```bash
cd frontend

# 运行全部测试
npm test

# 监听模式
npm run test:watch
```

测试文件位于 `frontend/src/test/` 目录。

### 覆盖率配置

`pyproject.toml` 中配置了 pytest-cov：

- `tg_signer` 包的 `fail_under` 阈值为 25%
- `backend/` 模块暂未纳入覆盖率统计
- 新增测试用例时，优先覆盖核心逻辑和边界条件

### 新增依赖

近期新增的运行时依赖：

| 依赖 | 用途 |
| --- | --- |
| `aiofiles` | 异步文件读写（`backend/utils/async_io.py`） |
| `psutil>=5.9.0` | 内存监控（`backend/utils/memory_monitor.py`） |

前端新增依赖：

| 依赖 | 用途 |
| --- | --- |
| `vue-i18n@9` | 多语言支持（中英文切换） |
