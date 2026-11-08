<span id="chinese"></span>

# 随机等待延迟 (jitter_delay)

[English](#english) | [简体中文](#chinese)

主动动作插件。在执行签到前增加一段随机等待时间，打乱固定执行周期，避免并发请求与规律性特征。

## 功能特性

- **多概率分布模型**：支持均匀分布 (`uniform`) 与高斯正态分布 (`gaussian`) 随机采样算法。
- **边界自适应纠错**：自动调换颠倒的最大/最小值，并确保等待时长为非负数。
- **打乱定时规律**：为打卡动作链提供自然的随机停顿，错开多账号任务执行时间。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `min_seconds` | number | `1.0` | 否 | 最小延迟秒数（下限） |
| `max_seconds` | number | `5.0` | 否 | 最大延迟秒数（上限） |
| `distribution` | string | `uniform` | 否 | 分布模型 (`uniform` 均匀分布 或 `gaussian` 正态分布) |

---

<span id="english"></span>
# Random Jitter Delay (jitter_delay)

English | [简体中文](#chinese)

Active action plugin. Injects randomized wait delay before sign-in execution to break fixed timing cycles and reduce request concurrency.

## Features

- **Multiple Distribution Models**: Supports uniform (`uniform`) and Gaussian normal (`gaussian`) random sampling.
- **Bound Auto-correction**: Automatically swaps inverted min/max bounds and clamps to non-negative values.
- **Cycle De-synchronization**: Provides natural randomized pauses to stagger task executions.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `min_seconds` | number | `1.0` | No | Minimum delay in seconds |
| `max_seconds` | number | `5.0` | No | Maximum delay in seconds |
| `distribution` | string | `uniform` | No | Distribution model (`uniform` or `gaussian`) |
