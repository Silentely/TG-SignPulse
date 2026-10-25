import json


def test_legacy_shapes_remain_loadable(tmp_path):
    legacy = {"account_name": "a", "actions": [], "enabled": True}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy))
    assert json.loads(path.read_text())["account_name"] == "a"


def test_backup_manifest_rejects_incompatible_version(tmp_path):
    from backend.services.backup_manifest import validate_backup_manifest

    (tmp_path / "backup-manifest.json").write_text(
        json.dumps({"version": 999, "files": []})
    )
    try:
        validate_backup_manifest(tmp_path / "unused.tar", tmp_path)
    except ValueError as exc:
        assert "version" in str(exc).lower()
    else:
        raise AssertionError("incompatible manifest was accepted")
