# 自动掷骰子与抽签 (dice_roller)

[English](#english) | 简体中文

响应式插件。实时监控指定群聊或私聊中的 `/roll`、`/dice` 等口令，随机生成点数并回复结果。

## 触发命令

- `/roll`：默认掷出 1~100 的随机数
- `/roll 20`：掷出 1~20 的二十面骰
- `/dice 6`：掷出 1~6 的六面骰

## 配置参数

| 参数名 | 类型 | 默认值 | 必填 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `max_sides` | number | `100` | 否 | 默认的最大骰子面数 |
| `reply_prefix` | string | `🎲 骰子掷出了：` | 否 | 回显结果前缀 |

---

<span id="english"></span>
# Auto Dice Roller (dice_roller)

English | [简体中文](#自动掷骰子与抽签-dice_roller)

Reactive plugin. Listens for `/roll` or `/dice` commands in chats and rolls random numbers.

## Configuration Parameters

| Parameter | Type | Default | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `max_sides` | number | `100` | No | Maximum dice faces |
| `reply_prefix` | string | `🎲 骰子掷出了：` | No | Reply text prefix |
