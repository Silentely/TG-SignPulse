"""
异步文件管理器

提供 JSON 和文本文件的异步读写能力，基于 aiofiles 实现非阻塞 I/O。

典型用例：
- 异步加载/保存 JSON 配置文件
- 异步读写日志或文本数据
- 文件存在性检查和清理

示例：
    manager = AsyncFileManager()
    data = await manager.read_json("/path/to/config.json")
    await manager.write_json("/path/to/output.json", {"key": "value"})
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

import aiofiles
import aiofiles.os


class AsyncFileManager:
    """异步文件管理器，支持 JSON 和文本文件的异步读写操作。

    所有文件操作均通过 aiofiles 实现非阻塞 I/O，避免阻塞事件循环。
    """

    async def read_json(self, path: Union[str, Path]) -> Any:
        """异步读取 JSON 文件并解析返回。

        Args:
            path: 文件路径

        Returns:
            解析后的 Python 对象（dict、list 等）

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        text = await self.read_text(path)
        return json.loads(text)

    async def write_json(
        self,
        path: Union[str, Path],
        data: Any,
        indent: int = 2,
        ensure_ascii: bool = False,
    ) -> None:
        """将 Python 对象序列化为 JSON 并异步写入文件。

        自动创建父目录。

        Args:
            path: 文件路径
            data: 要序列化的 Python 对象
            indent: JSON 缩进空格数，默认 2
            ensure_ascii: 是否转义非 ASCII 字符，默认 False
        """
        text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
        await self.write_text(path, text)

    async def read_text(self, path: Union[str, Path], encoding: str = "utf-8") -> str:
        """异步读取文本文件全部内容。

        Args:
            path: 文件路径
            encoding: 文件编码，默认 utf-8

        Returns:
            文件文本内容

        Raises:
            FileNotFoundError: 文件不存在
        """
        async with aiofiles.open(path, mode="r", encoding=encoding) as f:
            return await f.read()

    async def write_text(
        self, path: Union[str, Path], content: str, encoding: str = "utf-8"
    ) -> None:
        """异步写入文本内容到文件。

        自动创建父目录。

        Args:
            path: 文件路径
            content: 要写入的文本内容
            encoding: 文件编码，默认 utf-8
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, mode="w", encoding=encoding) as f:
            await f.write(content)

    async def exists(self, path: Union[str, Path]) -> bool:
        """异步检查文件或目录是否存在。

        Args:
            path: 文件或目录路径

        Returns:
            存在返回 True，否则返回 False
        """
        return await aiofiles.os.path.exists(str(path))

    async def delete(self, path: Union[str, Path]) -> bool:
        """异步删除文件。

        Args:
            path: 文件路径

        Returns:
            成功删除返回 True，文件不存在返回 False
        """
        try:
            await aiofiles.os.remove(str(path))
            return True
        except FileNotFoundError:
            return False
