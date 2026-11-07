# 加密货币行情监控 (crypto_price_tracker)

[English](#english) | 简体中文

响应式插件。实时监控目标会话中由各类 Bot 或频道推送的行情消息，自动提取指定代币（如 BTC、ETH、TON、SOL 等）的价格，并保存到本地插件存储。

## 功能特性

- **多币种支持**：通过正则匹配提取 BTC、ETH、USDT 等常见数字资产报价。
- **本地存储记录**：将最新提取到的价格与更新时间戳记录至插件独立存储（`ctx.storage`）。
- **轻量无感知**：监听消息并提取数据，不干扰正常对话。

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `target_symbol` | string | `BTC` | 是 | 欲监听的数字货币代码，如 `BTC`, `ETH`, `SOL` |
| `track_history` | boolean | `true` | 否 | 是否将最新价格与更新时间写入插件持久化存储 |

---

<span id="english"></span>
# Crypto Price Tracker (crypto_price_tracker)

English | [简体中文](#加密货币行情监控-crypto_price_tracker)

Reactive plugin. Monitors cryptocurrency prices posted by bots or channels, extracts token prices, and persists them into plugin storage.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `target_symbol` | string | `BTC` | Yes | Token symbol to track (e.g. `BTC`, `ETH`, `SOL`) |
| `track_history` | boolean | `true` | No | Whether to record price and timestamp in storage |
