from collections import defaultdict
from types import SimpleNamespace

import pytest

from tg_signer.core.signer_runner import SignerRunnerMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [(1, 2), (2, 1)])
async def test_mixed_targets_preserve_failure_and_do_not_replay_success(ids):
    runner = SimpleNamespace(
        context=SimpleNamespace(
            sign_chats=defaultdict(list), chat_messages=defaultdict(dict)
        ),
        log=lambda *a, **k: None,
        _account="dummy",
    )

    async def run(chat):
        if chat.chat_id == 1:
            raise RuntimeError("target unavailable")
        runner.context.business_status = "confirmed"

    runner.sign_a_chat = run
    config = SimpleNamespace(
        chats=[SimpleNamespace(chat_id=i, message_thread_id=None) for i in ids],
        sign_interval=0,
    )
    rows = await SignerRunnerMixin._run_config_chats(runner, config)
    assert isinstance(rows, list)
    assert {r["chat_id"]: r["business_status"] for r in rows} == {
        "1": "failed",
        "2": "confirmed",
    }
    assert runner.context.aggregate_status == "partial"
    assert [r["chat_id"] for r in rows if r["retry_safe"]] == ["1"]


@pytest.mark.asyncio
async def test_unknown_side_effect_is_not_retry_safe():
    from tg_signer.core.operation_receipts import UnknownOperationResult

    runner = SimpleNamespace(
        context=SimpleNamespace(
            sign_chats=defaultdict(list), chat_messages=defaultdict(dict)
        ),
        log=lambda *a, **k: None,
        _account="dummy",
    )

    async def run(chat):
        raise UnknownOperationResult("send outcome unknown")

    runner.sign_a_chat = run
    rows = await SignerRunnerMixin._run_config_chats(
        runner,
        SimpleNamespace(
            chats=[SimpleNamespace(chat_id=1, message_thread_id=None)], sign_interval=0
        ),
    )
    assert rows[0]["business_status"] == "unknown"
    assert rows[0]["retry_safe"] is False
    assert runner.context.aggregate_status == "unknown"


def test_history_keeps_additive_target_evidence(tmp_path):
    from backend.services.sign_task_history_store import SignTaskHistoryStore

    store = SignTaskHistoryStore(tmp_path)
    entry = store.record_run(
        account="a",
        task="t",
        entry={
            "success": False,
            "aggregate_status": "partial",
            "targets": [{"chat_id": "1", "business_status": "failed"}],
        },
    )
    assert entry["aggregate_status"] == "partial"
    assert store.load_entries("a", "t")[0]["targets"][0]["chat_id"] == "1"
