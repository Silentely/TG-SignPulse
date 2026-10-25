from types import SimpleNamespace


def test_contract_compare_reports_button_drift():
    from backend.services.bot_contracts import build_bot_contract, compare_bot_contract

    first = build_bot_contract(
        SimpleNamespace(
            chat_id=1,
            message_thread_id=None,
            sender_id=2,
            text="ok",
            event_type="NEW_MESSAGE",
            button_snapshot=(("A", "1"),),
        )
    )
    second = build_bot_contract(
        SimpleNamespace(
            chat_id=1,
            message_thread_id=None,
            sender_id=2,
            text="ok",
            event_type="NEW_MESSAGE",
            button_snapshot=(("B", "2"),),
        )
    )
    result = compare_bot_contract(first, second)
    assert result["match"] is False
    assert "buttons" in result["differences"]
