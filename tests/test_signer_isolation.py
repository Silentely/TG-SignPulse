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


if __name__ == "__main__":
    unittest.main()
