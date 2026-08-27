import asyncio
import unittest

import click

from tg_signer.cli.signer import _run_signers_isolated


class _StubSigner:
    def __init__(self, outcome, calls):
        self._outcome = outcome
        self._calls = calls

    async def run(self, num_of_dialogs):
        self._calls.append(num_of_dialogs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class SignerIsolationTest(unittest.TestCase):
    def test_continues_running_later_signers_after_failure(self):
        calls = []
        signers = [
            ("task:first", _StubSigner(RuntimeError("boom"), calls), 10),
            ("task:second", _StubSigner("ok", calls), 20),
        ]

        with self.assertRaises(click.ClickException) as ctx:
            asyncio.run(_run_signers_isolated(signers))

        self.assertEqual(calls, [10, 20])
        self.assertIn("task:first: boom", str(ctx.exception))

    def test_succeeds_when_all_signers_succeed(self):
        calls = []
        signers = [
            ("task:first", _StubSigner("ok", calls), 10),
            ("task:second", _StubSigner("ok", calls), 20),
        ]

        asyncio.run(_run_signers_isolated(signers))
        self.assertEqual(calls, [10, 20])

    def test_runs_signers_concurrently(self):
        """常驻型 run 不再阻塞后续任务：两个都不返回的 signer 都应已启动。"""
        started = []

        class _NeverDone:
            async def run(self, num_of_dialogs):
                started.append(num_of_dialogs)
                await asyncio.sleep(3600)

        async def _main():
            task = asyncio.create_task(
                _run_signers_isolated(
                    [
                        ("task:first", _NeverDone(), 10),
                        ("task:second", _NeverDone(), 20),
                    ]
                )
            )
            await asyncio.sleep(0.1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(_main())
        # 串行时代第二个任务永远轮不到；并发时代两个都已启动
        self.assertEqual(sorted(started), [10, 20])

    def test_session_invalid_error_shows_chinese_hint(self):
        calls = []
        signers = [
            ("task:first", _StubSigner(ConnectionError("Session invalid: unauthorized"), calls), 10),
        ]

        with self.assertRaises(click.ClickException) as ctx:
            asyncio.run(_run_signers_isolated(signers))

        message = str(ctx.exception)
        self.assertIn("会话已失效或未登录", message)
        self.assertIn("重新登录", message)
        # 不再透出英文裸异常
        self.assertNotIn("unauthorized", message)

    def test_other_errors_keep_original_message(self):
        calls = []
        signers = [
            ("task:first", _StubSigner(RuntimeError("磁盘满"), calls), 10),
        ]

        with self.assertRaises(click.ClickException) as ctx:
            asyncio.run(_run_signers_isolated(signers))

        self.assertIn("task:first: 磁盘满", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
