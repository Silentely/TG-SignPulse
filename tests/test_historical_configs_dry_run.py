import json
from pathlib import Path

from tools.dry_run_task_configs import run_dry_run_scan


def test_all_existing_task_configs_compile_cleanly():
    """扫描现有磁盘配置，断言编译失败数为 0"""
    report = run_dry_run_scan(signs_dir="data/signs")
    assert report["failed_count"] == 0, f"存在无法编译的旧配置: {report['errors']}"


def test_dry_run_scan_with_synthetic_configs(tmp_path: Path):
    """验证包含经典 action 与复杂工作流的历史配置都能被 dry_run_scan 正常编译"""
    task_dir_1 = tmp_path / "acc1" / "task1"
    task_dir_1.mkdir(parents=True)
    cfg1 = {
        "chats": [
            {
                "chat_id": 123456,
                "actions": [
                    {"send": "/checkin"},
                    {"wait": 2.0},
                    {"match_text": "签到成功"},
                ],
            }
        ]
    }
    with open(task_dir_1 / "config.json", "w", encoding="utf-8") as f:
        json.dump(cfg1, f)

    task_dir_2 = tmp_path / "acc2" / "task2"
    task_dir_2.mkdir(parents=True)
    cfg2 = {
        "chats": [
            {
                "chat_id": 987654,
                "initial_step_id": "step_send",
                "steps": [
                    {
                        "step_id": "step_send",
                        "action_type": 1,
                        "config": {"text": "/start"},
                        "next_step_id": "step_wait",
                    },
                    {
                        "step_id": "step_wait",
                        "action_type": 1,
                        "config": {"text": "hello"},
                    },
                ],
            }
        ]
    }
    with open(task_dir_2 / "config.json", "w", encoding="utf-8") as f:
        json.dump(cfg2, f)

    report = run_dry_run_scan(signs_dir=tmp_path)
    assert report["scanned_files"] == 2
    assert report["chats_compiled"] == 2
    assert report["success_count"] == 2
    assert report["failed_count"] == 0


def test_dry_run_scan_detects_malformed_config(tmp_path: Path):
    """验证格式损坏的配置文件能被正确检测并计入 failed_count"""
    bad_dir = tmp_path / "acc3" / "task_bad"
    bad_dir.mkdir(parents=True)
    with open(bad_dir / "config.json", "w", encoding="utf-8") as f:
        f.write("{invalid json syntax")

    report = run_dry_run_scan(signs_dir=tmp_path)
    assert report["scanned_files"] == 1
    assert report["failed_count"] == 1
    assert len(report["errors"]) == 1
