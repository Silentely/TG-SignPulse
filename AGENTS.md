# Agent Instructions & Guidelines

## Python 代码提交与格式化规范（强制门禁）

在本项目中，GitHub Actions 镜像工作流配置了严格的排版硬门槛：
`ruff format --check . --quiet`

**所有 AI Agent 在执行 `git commit` 或提交代码前，必须满足以下规范**：

1. **格式化被修改的 Python 文件**：
   ```bash
   .venv/bin/ruff format <修改的文件路径...>
   .venv/bin/ruff check --fix <修改的文件路径...>
   ```
   或者直接运行一键脚本：
   ```bash
   bash scripts/format
   ```

2. **提交前自检验证**：
   在执行 commit 前，必须运行：
   ```bash
   .venv/bin/ruff format --check .
   .venv/bin/ruff check .
   ```
   只有确认两者 100% 通过（0 errors, all files formatted）后方可提交与推送，防止 CI 镜像构建失败阻断。
