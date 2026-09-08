# TG-SignPulse 扩展插件目录 (Plugins)

本目录用于存放 TG-SignPulse 的自定义 Action 扩展插件（Action ID `99` / `CUSTOM_PLUGIN`）。

## 快速使用

1. **宿主机开发运行**：
   将插件目录或 `*.py` 单文件直接置于本目录（`./plugins`）。

2. **Docker 容器部署运行（推荐）**：
   由于官方 `docker-compose.yml` 默认将宿主机 `./data` 目录挂载至容器 `/data`，只需在宿主机创建 `./data/plugins/` 目录并将插件放入其中，**无需重新构建 Docker 镜像**，容器启动时会自动热加载！

## 目录与文件规范

- **目录型插件**（推荐）：
  `plugins/<plugin_name>/main.py` 或 `plugins/<plugin_name>/__init__.py`
  插件目录已自动加入 `sys.path`，内部支持多文件拆分与相对模块导入。
- **单文件插件**：
  `plugins/<plugin_name>.py`

## 内置官方范例

- [`math_solver/main.py`](./math_solver/main.py)：
  纯文本数学算式（如 `2*31`）本地秒答插件。用于处理不需要大语言模型介入的确定性验证码场景，避免产生 AI 费用与调用延迟。

详细开发文档请查阅：[TG-SignPulse 官方文档 - 自定义 Action 插件扩展机制](file:///Users/adair/Projects/TG-SignPulse/docs/guide/plugins.md)。
