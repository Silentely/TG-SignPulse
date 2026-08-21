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
