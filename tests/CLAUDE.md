[根目录](../CLAUDE.md) > **tests**

# Tests 模块

> 仓库根级 pytest 套件：覆盖 backend、tg_signer 与部分集成路径。

## 变更记录 (Changelog)

> 模块级变更并入根 [`CHANGELOG.md`](../CHANGELOG.md)。本文件由 `/ccg:init` 补扫生成。

## 模块职责

- 后端 API / 服务 / 工具单元与集成测试
- `tg_signer` 核心与配置兼容测试
- 关键词监听、签到 runner、通知、SSE 等回归
- 通过 factories / fixtures / mocks 降低真实 Telegram 依赖

## 入口与运行

```bash
# 仓库根
pip install -e ".[dev]"
pytest
pytest tests/ -n auto --dist loadgroup -q   # 与 CI 类似的并行
pytest --cov --cov-fail-under=40            # 覆盖率门槛 40%
```

| 项 | 说明 |
|----|------|
| 框架 | pytest + pytest-asyncio + pytest-cov（见 `pyproject.toml`） |
| 规模 | 约 **70+** 个 `test_*.py`（目录内总文件约 80+，含辅助包） |
| 覆盖 | 近期全量行覆盖约 **60%**（`coverage.xml`）；门槛 **40%** |
| CI | `.github/workflows/docker.yml` 的 `test` job：`pytest -n auto` + 核心路径 `ruff check` |

## 目录结构

```
tests/
├── conftest.py          # 全局 fixture
├── factories/           # 测试数据工厂
├── fixtures/            # accounts / messages / tasks 等夹具
├── mocks/               # telegram / database / ai_service 替身
├── utils/               # 测试辅助
└── test_*.py            # 用例（按领域命名）
```

## 主要用例族群（按文件名前缀）

| 前缀 / 文件 | 覆盖域 |
|-------------|--------|
| `test_api*` / `test_*_routes*` | HTTP 路由与鉴权边界 |
| `test_sign_*` / `test_task_runner*` | 签到 CRUD、runner、batch、历史 |
| `test_keyword_monitor*` / `test_keyword_hits*` / `test_monitor_sharding*` | 监听、命中、分片、去重 |
| `test_events_*` | SSE |
| `test_device_keepalive*` / `test_ops_*` | 保活与运维 |
| `test_core*` / `test_config*` / `test_ai_*` / `test_signer*` | tg_signer 与配置 |
| `test_*utils*` / `test_atomic_io*` / `test_cache*` / `test_tg_session*` | 工具层 |

## 编写约定

1. **优先本地替身**：`mocks/telegram.py` 等，避免真实网络与 session 文件
2. **异步**：`pytest-asyncio`；与生产相同的 async 入口
3. **隔离数据目录**：用例应使用临时目录 / fixture，不写生产 `APP_DATA_DIR`
4. **改 runner / keyword_monitor / 路由**：至少补对应 `test_*.py` 再声称完成
5. **前端测试不在此目录**：见 `frontend/src/test/*.spec.ts`（vitest）

## 常见问题 (FAQ)

**Q: 为何 CI 忽略 `tools/`？**  
A: `pytest tests/ --ignore=tools`；tools 为运维脚本，不进默认套件。

**Q: ruff 是否全仓强制？**  
A: CI 对核心新模块路径做硬门槛（telegram、keyword_monitor 部分、batch/ops、scheduler 等），并非一次性全仓 `ruff check .`。

## 相关文件清单

- `tests/conftest.py`、`tests/factories/`、`tests/fixtures/`、`tests/mocks/`
- `pyproject.toml`（pytest / cov / ruff）
- `.github/workflows/docker.yml`（`test` / `frontend-test` jobs）
- 前端：`frontend/src/test/`
