# 拟人随机延迟抖动 (jitter_delay)

[English](#english) | 简体中文

主动动作插件。在签到或打卡指令执行前注入具有拟人特征的随机等待与思考延迟，彻底打破固定周期的定时特征，有效避免风控引擎根据规律执行特征识别自动化行为。

## 功能特性

- **多概率分布模型**：支持均匀分布 (`uniform`) 与高斯正态分布 (`gaussian`) 采样算法。
- **边界自适应纠错**：智能调换颠倒的上下界，并严格钳制为非负安全数值。
- **消除定时特征**：为打卡动作链提供天然的拟人随机停顿。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `min_seconds` | number | `1.0` | 否 | 随机延迟等待时长的下限（秒） |
| `max_seconds` | number | `5.0` | 否 | 随机延迟等待时长的上限（秒） |
| `distribution` | select | `uniform` | 否 | 随机数采样概率分布模型 (`uniform` 均匀分布 或 `gaussian` 高斯分布) |

---

<span id="english"></span>
# Humanized Jitter Delay (jitter_delay)

English | [简体中文](#拟人随机延迟抖动-jitter_delay)

Active action plugin. Injects human-like randomized delays and thinking pauses before sign-in commands, eliminating fixed-schedule timing patterns to protect accounts from automated behavior detection.

## Features

- **Multiple Distribution Models**: Supports both Uniform (`uniform`) and Gaussian/Normal (`gaussian`) distribution sampling.
- **Smart Boundary Handling**: Automatically swaps inverted min/max bounds and clamps delays to non-negative values.
- **Timing De-fingerprinting**: Injects authentic natural pauses into workflow execution pipelines.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `min_seconds` | number | `1.0` | No | Lower bound for random delay in seconds |
| `max_seconds` | number | `5.0` | No | Upper bound for random delay in seconds |
| `distribution` | select | `uniform` | No | Sampling distribution model (`uniform` or `gaussian`) |
