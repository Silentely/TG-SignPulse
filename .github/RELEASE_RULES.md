# TG-SignPulse 发布规则

> 本文档定义 Agent 在执行版本发布时必须遵循的规则与流程。

## 版本号规范

采用 [语义化版本 (SemVer)](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`

| 类型 | 升级位 | 触发条件 | 示例 |
|------|--------|----------|------|
| **主版本** (MAJOR) | v**X**.0.0 | 破坏性变更、不向后兼容的架构重构 | v2.0.0 → v3.0.0 |
| **次版本** (MINOR) | v0.**X**.0 | 新功能、新模块、显著改进 | v2.2.0 → v2.3.0 |
| **补丁版本** (PATCH) | v0.0.**X** | Bug 修复、文档修正、CI 调整 | v2.2.2 → v2.2.3 |

### 预发布标识（暂不使用）

项目当前不使用 `-alpha` / `-beta` / `-rc` 后缀。如需引入，须在本文件中新增规则。

## 发布前置条件

在执行发布操作前，Agent **必须确认**以下所有条件均满足：

### 代码质量

- [ ] `pytest tests/ -n auto -x -q` 全部通过
- [ ] `ruff check` 核心模块无新增错误
- [ ] 前端 `npm run typecheck` 通过
- [ ] 前端 `npm run build` 成功

### 变更审查

- [ ] 自上个版本以来的变更已整理为 CHANGELOG 条目
- [ ] 所有关联 Issue 已关闭或标注为已解决
- [ ] 无未完成的 TODO / FIXME 标记影响发布功能

### 版本号同步

以下位置的版本号**必须保持一致**，Agent 需逐一检查并更新：

| 位置 | 文件路径 | 说明 |
|------|----------|------|
| Python 包版本 | `tg_signer/__init__.py` → `__version__` | **唯一真实来源**，pyproject.toml 动态读取 |
| pyproject.toml | `pyproject.toml` → `[project]` | `dynamic = ["version"]`，无需手动改 |
| Docker 标签 | `.github/workflows/docker.yml` | 自动从 tag 派生，无需手动改 |
| CHANGELOG | 根目录 `CHANGELOG.md`（如存在）或 CLAUDE.md 变更记录 | 新增版本条目 |

## 发布流程

### Step 1：确认版本号

```bash
# 查看当前版本
python -c "from tg_signer import __version__; print(__version__)"

# 确定新版本号（基于变更类型）
# Bug fix → PATCH, 新功能 → MINOR, 破坏性变更 → MAJOR
```

### Step 2：更新版本号

```bash
# 修改 tg_signer/__init__.py 中的 __version__
# 例如：__version__ = "2.3.0"
```

### Step 3：更新 CHANGELOG

在 CLAUDE.md 变更记录表格中新增行，格式：

```
| YYYY-MM-DD | 变更摘要（一句话） |
```

变更摘要应遵循以下前缀约定（与 commit message 一致）：

| 前缀 | 含义 |
|------|------|
| ✨ feat: | 新功能 |
| 🐛 fix: | Bug 修复 |
| ♻️ refactor: | 重构 |
| 🔥 remove: | 删除废弃代码 |
| 🔧 chore: | 构建 / CI / 工具链 |
| 📝 docs: | 文档 |
| improve: | 现有功能改进 |

### Step 4：提交与打 Tag

```bash
# 提交版本更新
git add tg_signer/__init__.py CLAUDE.md
git commit -m "chore: 发布版本号同步至 X.Y.Z"

# 打 tag（必须以 v 开头）
git tag vX.Y.Z

# 推送
git push origin main
git push origin vX.Y.Z
```

### Step 5：验证 CI

- 推送 `v*` tag 后，Docker Image 工作流自动触发
- 工作流会构建镜像并推送到 GHCR，标签策略：
  - `vX.Y.Z` — 精确版本
  - `latest` — 最新稳定版
  - `main` — main 分支最新
- **Agent 必须等待 CI 通过后才算发布完成**

```bash
# 检查 CI 状态
gh run list --workflow=docker.yml --limit=3
```

## 发布后验证

- [ ] GHCR 镜像已推送（`ghcr.io/<owner>/tg-signpulse:vX.Y.Z`）
- [ ] Docker 标签 `latest` 已更新
- [ ] 版本检查 API 返回新版本号

## 禁止事项

- ❌ 禁止跳过测试直接发布
- ❌ 禁止在 CI 未通过时标记发布完成
- ❌ 禁止手动覆盖已发布的 tag（应发布新的 patch 版本）
- ❌ 禁止在发布 commit 中混入功能代码
- ❌ 禁止发布包含 `Claude` / `Co-Authored-By` 字样的 commit

## 紧急热修复流程

当生产环境出现严重 Bug 需要紧急修复时：

1. 从最新 release tag 创建 hotfix 分支：`git checkout -b hotfix/vX.Y.Z vX.Y.Z`
2. 仅修复目标 Bug，不混入其他变更
3. 运行测试确认通过
4. 按正常流程升级 PATCH 版本号并发布
5. hotfix 分支合并回 main 和 dev

## 版本回退

如果发布后发现严重问题：

1. **不删除已发布的 tag**（Docker 镜像已推送，删除 tag 无法撤回）
2. 立即修复并发布新的 patch 版本
3. 如有必要，在 GitHub Release 页面标注问题版本
