# 代码开发规范与自动化格式化指南

本项目（TG-SignPulse）为了保障核心代码质量与线上运行稳定性，配置了严格的本地 Git 钩子及 CI 门禁检查。

本文档汇总了代码格式化标准、自动化配置方法及常见推送拦截的解决方案。

---

## 一、为什么之前 `git push` 会经常被拦截？

在项目中运行 `bash scripts/install-hooks` 后，本地 Git 会启用 `scripts/pre-push` 钩子。推送时会自动执行以下 3 步检查：

1. **Ruff 代码检查与格式验证**：
   - `ruff check backend/ tg_signer/ tests/ scripts/`（语法、import 引用与排序等）
   - `ruff format --check backend/ tg_signer/ tests/ scripts/`（**只读格式比对**）
   - **拦截原因**：`--check` 只做静态比对拦截，不会自动修改文件。如果提交前没有执行格式化，哪怕只是多余的空格、引号风格或未排序的 import，都会导致退出码为 1 并终止推送。
2. **前端类型检查**：若涉及 `frontend/` 目录改动，执行 `npx vue-tsc --noEmit`。
3. **后端轻量边界冒烟检查**：执行 `scripts/prod_boundary_check.py`（~1-2 秒）。

---

## 二、后续如何实现“编辑完自动格式化”？（3 种方式）

为了彻底避免“写完代码因格式化问题被钩子打断”，建议按以下方式配置自动化流水线：

### 方案 1：IDE / 编辑器保存时自动格式化（最推荐，零感知）
项目根目录下已内置 `.vscode/settings.json`。使用 **VS Code**、**Cursor** 或 **Windsurf** 打开项目时：
1. 确保安装推荐扩展：`Ruff` (`charliermarsh.ruff`)。
2. 配置已生效：每次按保存键 (`Cmd + S` / `Ctrl + S`) 时：
   - 自动按照 Ruff 规则格式化 Python 代码；
   - 自动组织和排序 import 语句 (`source.organizeImports`)；
   - 自动修复常规 lint 警告 (`source.fixAll`)。

### 方案 2：Git Commit 提交前自动格式化（Pre-commit 钩子）
我们提供了 `scripts/pre-commit` 钩子。
在项目根目录下执行一次安装命令：
```bash
bash scripts/install-hooks
```
**工作原理**：
- 每次执行 `git commit` 时，钩子会自动识别暂存区中的 `.py` 文件；
- 毫秒级执行 `ruff check --fix` 与 `ruff format`；
- 自动将修复后的代码重新暂存并提交；
- **效果**：每次提交的代码天然 100% 符合规范，`git push` 时绝对不会因格式问题被拦截。

### 方案 3：手动一键全量格式化
如果在批量重构或合并分支后需要统一检查与修复，可直接执行：
```bash
bash scripts/format
# 或者直接使用虚拟环境中的 ruff：
./.venv/bin/ruff check --fix backend/ tg_signer/ tests/ scripts/
./.venv/bin/ruff format backend/ tg_signer/ tests/ scripts/
```

---

## 三、代码规范要点（Python & 前端）

### 1. Python 规范
- **基准**：PEP 8，行宽上限 `line-length = 88`（详见 `pyproject.toml` 中的 `[tool.ruff]`）。
- **工具链**：统一使用项目锁定的 `ruff`（版本与 pyproject 对齐 `<0.16`）。
- **规则集**：严格遵守 `E`（错误）、`F`（Pyflakes）、`I`（isort 导入排序）、`B`（Bugbear 避坑检查）、`C4`（推导式优化）。
- **敏感信息**：禁止在日志或持久化数据中明文打印凭据、Token、密码等敏感字段。

### 2. 前端规范 (Vue 3 + TypeScript)
- 严格遵循 TypeScript 类型定义，禁止无故隐式 `any`。
- 保证 `npm run typecheck`（`vue-tsc --noEmit`）无类型错误。

---

## 四、常见问题与应急指令

| 场景 | 命令 / 处理方式 |
|------|----------------|
| 一键安装所有 Git 钩子 | `bash scripts/install-hooks` |
| 一键修复并格式化全库 Python 代码 | `bash scripts/format` |
| 紧急修复需要立即推送（跳过推送检查） | `git push --no-verify` 或 `SKIP_PUSH_HOOK=1 git push` |
| 紧急提交需要跳过 commit 格式化 | `git commit --no-verify` 或 `SKIP_PRE_COMMIT=1 git commit` |
| 推送前在本地跑全量后端测试 | `RUN_TESTS=1 git push` |
