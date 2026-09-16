# TG-SignPulse 社区插件贡献指南 (Community Plugins)

欢迎为 TG-SignPulse 插件市场贡献你的插件！

通过本目录，你可以直接提交 Pull Request（PR）向官方仓库贡献自定义 Action 插件。**注意：所有插件 PR 均要求提交至 `dev` 分支**，经 CI 门禁检查与审查合并后，由官方流水线自动构建打包并发布至 `main` 分支，所有 TG-SignPulse 运行实例即可在 Web 管理界面的「插件市场」中一键拉取安装与热重载。

---

## 快速贡献步骤

1. **Fork 本项目** 并拉取最新代码到本地。
2. **复制模板**：
   复制 `community_plugins/_template` 目录并重命名为你自己的插件唯一标识（如 `community_plugins/my_custom_tool/`）。
   - 插件标识必须为 3-32 位小写字母、数字或下划线（正则：`^[a-z0-9_]{3,32}$`）。
3. **完善元数据 (`plugin.json`)**：
   根据 [`schema.json`](./schema.json) 补齐你的插件名称、作者、版本、模式、分类及参数定义。
4. **编写核心代码 (`main.py`)**：
   实现处理函数并使用 `@PluginRegistry.register` 完成注册。
5. **编写插件文档 (`README.md`)**：
   清晰说明插件功能、配置参数意义与使用场景。
6. **本地测试与语法检查**：
   运行 `python scripts/build_marketplace.py --check` 验证所有插件的元数据与语法规范。
7. **提交 PR**：
   向官方仓库的 `dev` 分支提交 Pull Request（**请注意：PR 目标分支务必选为 `dev` 分支**，经 CI 自动化安全门禁检查与测试通过后，由官方统一合并并发布至 `main` 分支）。

---

## 插件目录规范

每个社区插件必须作为独立子目录存放于 `community_plugins/<plugin_id>/` 下：

```text
community_plugins/
└── <plugin_id>/
    ├── plugin.json       # 必选：插件元数据清单（符合 schema.json 规范）
    ├── main.py           # 必选：插件入口文件
    └── README.md         # 必选：插件中文或多语言说明文档
```

---

## 元数据规范 (`plugin.json`)

```json
{
  "id": "my_sample_plugin",
  "name": "我的示例插件",
  "version": "1.0.0",
  "mode": "reactive",
  "category": "utility",
  "description": "监控特定消息并自动执行计算",
  "author": "GitHubUsername",
  "homepage": "https://github.com/your-username/repo",
  "icon": "sparkles",
  "tags": ["example", "demo"],
  "min_app_version": "1.8.0",
  "permissions": ["storage", "telegram_send"],
  "params_schema": [
    {
      "name": "keyword",
      "label": "触发关键词",
      "type": "string",
      "default": "ping",
      "required": true
    }
  ]
}
```

### 分类 (Category) 取值
- `utility`：实用工具（数学计算、格式转换、文本处理等）
- `notification`：通知与推送（Webhook、多渠道告警、行情追踪）
- `message`：消息编排（自动应答、转录、正则匹配、表情反应）
- `captcha`：验证码秒答与挑战辅助
- `helper`：签到辅助与状态跟踪
- `entertainment`：互动娱乐（抽签、掷骰子、成语接龙）

---

## 代码与安全规范

为了保障所有终端用户的安全与系统稳定性，所有进入插件市场的社区代码均需通过静态安全审计：

1. **禁止高危系统调用**：
   - 严禁调用 `eval()`、`exec()`、`compile()` 或任意形式的代码混淆。
   - 严禁使用 `os.system()`、`subprocess` 启动未经声明的外部命令。
   - 严禁尝试读取主程序的 `.session` 凭据文件或其它敏感数据库。
2. **遵守运行模式规范**：
   - `reactive` 模式：需返回布尔值（`True` 代表成功命中并处理，`False` 代表未命中继续监听）。
   - `active` 模式：单次主动执行，返回处理结果。
3. **超时与死循环防护**：
   - 插件执行环境受独立沙箱进程与超时 `SIGKILL` 保护，请避免长时间无响应的同步阻塞。

---

## 🤖 AI 智能审查与元数据补全工作流

为了降低社区作者的维护负担并强化代码安全性，TG-SignPulse 仓库已接入 **AI 审查守门人 (AI Quality Gatekeeper)**：

1. **Pull Request 自动化审查**：
   - 当你向 `community_plugins/` 目录提交 PR 时，GitHub Actions 将自动触发 `ai-plugin-review.yml`。
   - 机器人将分析插件代码是否存在隐藏的后门逻辑、未经授权的数据外发，以及是否存在 `time.sleep` 等阻塞 `asyncio` 事件循环的性能问题。
   - 审查结论将自动以 Markdown 报告形式回帖至你的 Pull Request。

2. **本地运行 AI 审查与元数据补全**：
   在提交 PR 之前，你可以在本地直接运行该脚本：
   ```bash
   # 查看 AI 对插件的审查报告（自动回显中文、英文双语描述建议）
   python scripts/ai_review_plugin.py community_plugins/my_plugin

   # 自动将 AI 生成的英文描述 (description_en)、标签与核心亮点补全至 plugin.json
   python scripts/ai_review_plugin.py community_plugins/my_plugin --apply
   ```
   > 提示：本地执行支持设置 `GEMINI_API_KEY` 或 `OPENAI_API_KEY`，若未提供 API Key，脚本将以 Mock 离线模式运行。

3. **打包时自动化增强**：
   官方构建流水线在生成市场索引时，通过 `--ai-enrich` 标志为缺乏英文翻译或标签过少的插件自动补充高质量国际化元数据，确保全球用户体验一致。
