"""测试签到记录文件损坏时的自动容错与安全恢复。"""

from __future__ import annotations

from pathlib import Path

from tg_signer.core.signer_config import SignerConfigMixin


class DummySigner(SignerConfigMixin):
    def __init__(self, record_path: Path):
        self._record_path = record_path

    @property
    def sign_record_file(self) -> Path:
        return self._record_path


def test_load_sign_record_creates_new_file(tmp_path: Path):
    rec_path = tmp_path / "record.json"
    signer = DummySigner(rec_path)
    res = signer.load_sign_record()
    assert res == {}
    assert rec_path.is_file()


def test_load_sign_record_valid_content(tmp_path: Path):
    rec_path = tmp_path / "record.json"
    rec_path.write_text('{"2025-01-01": "2025-01-01T08:00:00"}', encoding="utf-8")
    signer = DummySigner(rec_path)
    res = signer.load_sign_record()
    assert res == {"2025-01-01": "2025-01-01T08:00:00"}


def test_load_sign_record_handles_corrupt_json(tmp_path: Path):
    rec_path = tmp_path / "record.json"
    rec_path.write_text('{"bad json here...', encoding="utf-8")
    signer = DummySigner(rec_path)
    res = signer.load_sign_record()
    assert res == {}
    # 损坏文件应被重置为有效 JSON
    assert rec_path.is_file()
    assert signer.load_sign_record() == {}


def test_load_sign_record_handles_non_dict_json(tmp_path: Path):
    rec_path = tmp_path / "record.json"
    rec_path.write_text('[1, 2, 3]', encoding="utf-8")
    signer = DummySigner(rec_path)
    res = signer.load_sign_record()
    assert res == {}
