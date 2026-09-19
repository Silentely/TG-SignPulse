from pathlib import Path

from backend.utils.tg_session import get_account_profile, set_account_profile


def test_account_tags_storage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TG_SIGNER_DATA_DIR", str(tmp_path))

    acc = "test_tag_account"
    # 初始状态 tags 为空
    prof = get_account_profile(acc)
    assert not prof.get("tags")

    # 设置标签
    set_account_profile(acc, tags=["VIP", "工作", "  测试  ", ""])
    prof = get_account_profile(acc)
    assert prof["tags"] == ["VIP", "工作", "测试"]

    # 更新备注不覆盖现有标签
    set_account_profile(acc, remark="我的备注")
    prof = get_account_profile(acc)
    assert prof["remark"] == "我的备注"
    assert prof["tags"] == ["VIP", "工作", "测试"]

    # 清空标签
    set_account_profile(acc, tags=[])
    prof = get_account_profile(acc)
    assert prof["tags"] == []
