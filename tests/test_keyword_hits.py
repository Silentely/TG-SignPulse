"""关键词命中记录落盘 / 分组 / 导出测试。"""
from pathlib import Path

import pytest

from backend.services.keyword_monitor import hits as hits_mod


@pytest.fixture(autouse=True)
def _isolated_hits(tmp_path: Path, monkeypatch):
    hits_mod.reset_hits_for_tests()

    class _Settings:
        def resolve_workdir(self):
            return tmp_path

    monkeypatch.setattr(hits_mod, "get_settings", lambda: _Settings())
    yield
    hits_mod.reset_hits_for_tests()


def test_record_and_list_hits():
    hits_mod.record_keyword_hit(
        account_name="acc1",
        task_name="listen_a",
        chat_id=-1001,
        chat_title="Group A",
        keyword="code1",
        keywords=["code1"],
        message_text="hello code1",
        sender="bob",
        push_channel="telegram",
    )
    hits_mod.record_keyword_hit(
        account_name="acc1",
        task_name="listen_a",
        chat_id=-1002,
        chat_title="Group B",
        keyword="code2",
        message_text="hello code2",
    )
    data = hits_mod.list_keyword_hits(task_name="listen_a", limit=10)
    assert data["total"] == 2
    assert data["items"][0]["keyword"] == "code2"  # 新在前
    assert data["items"][1]["keyword"] == "code1"


def test_group_by_chat():
    for i in range(3):
        hits_mod.record_keyword_hit(
            account_name="a",
            task_name="t",
            chat_id=-100,
            chat_title="Same",
            keyword=f"k{i}",
            message_text=f"m{i}",
        )
    hits_mod.record_keyword_hit(
        account_name="a",
        task_name="t",
        chat_id=-200,
        chat_title="Other",
        keyword="x",
    )
    grouped = hits_mod.group_keyword_hits(group_by="chat", limit_per_group=10)
    assert grouped["group_by"] == "chat"
    keys = {g["key"] for g in grouped["groups"]}
    assert "-100" in keys
    assert "-200" in keys
    same = next(g for g in grouped["groups"] if g["key"] == "-100")
    assert same["count"] == 3
    assert len(same["items"]) == 3


def test_group_chat_title_with_pipe_does_not_break_key():
    hits_mod.record_keyword_hit(
        account_name="a",
        task_name="t",
        chat_id=-1,
        chat_title="A|B|C",
        keyword="k",
    )
    grouped = hits_mod.group_keyword_hits(group_by="chat")
    assert len(grouped["groups"]) == 1
    assert grouped["groups"][0]["key"] == "-1"
    assert grouped["groups"][0]["label"] == "A|B|C"
    assert grouped["groups"][0]["count"] == 1


def test_export_csv_contains_header_and_rows():
    hits_mod.record_keyword_hit(
        account_name="acc",
        task_name="task",
        keyword="kw",
        message_text="line",
    )
    csv_text = hits_mod.export_keyword_hits_csv()
    assert "account_name" in csv_text
    assert "kw" in csv_text
    assert "acc" in csv_text


def test_export_limit_not_capped_at_list_default():
    for i in range(30):
        hits_mod.record_keyword_hit(
            account_name="a",
            task_name="t",
            keyword=f"k{i}",
            message_text=f"m{i}",
        )
    # 列表默认 max_limit=500，但 export 用 max_limit=MAX_RECORDS
    data = hits_mod.list_keyword_hits(limit=600, max_limit=hits_mod.MAX_RECORDS)
    assert data["total"] == 30
    assert len(data["items"]) == 30
    csv_text = hits_mod.export_keyword_hits_csv(limit=25)
    # header + 25 rows
    assert csv_text.count("\n") >= 25


def test_export_csv_formula_injection_escaped():
    hits_mod.record_keyword_hit(
        account_name="acc",
        task_name="task",
        keyword="=1+1",
        message_text="+cmd",
    )
    csv_text = hits_mod.export_keyword_hits_csv()
    assert "'=1+1" in csv_text
    assert "'+cmd" in csv_text


def test_record_strips_javascript_url():
    rec = hits_mod.record_keyword_hit(
        account_name="a",
        task_name="t",
        url="javascript:alert(1)",
        keyword="k",
    )
    assert rec["url"] == ""
    rec2 = hits_mod.record_keyword_hit(
        account_name="a",
        task_name="t",
        url="https://t.me/c/1/2",
        keyword="k2",
    )
    assert rec2["url"].startswith("https://")


def test_clear_filtered():
    hits_mod.record_keyword_hit(account_name="a1", task_name="t1", keyword="1")
    hits_mod.record_keyword_hit(account_name="a2", task_name="t1", keyword="2")
    deleted = hits_mod.clear_keyword_hits(account_name="a1")
    assert deleted == 1
    data = hits_mod.list_keyword_hits()
    assert data["total"] == 1
    assert data["items"][0]["account_name"] == "a2"
