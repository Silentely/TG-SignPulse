"""Docker 入口降权决策测试。

无法在本地跑 docker，故用 stub 命令（id/stat/chown/chmod/gosu/uvicorn）
驱动真实 entrypoint.sh，复证 (容器身份 × /data 属主 × chown 结果) 的组合：

- 非 root 启动：直接 exec uvicorn，不做任何属主修正
- root 启动且 chown 成功：chown 后经 gosu 降权
- root 启动且 chown 失败：非零退出且绝不启动服务（fail-closed，不回退 root）
- APP_AUTO_FIX_DATA_PERMS=0：跳过 chown，仍经 gosu 降权
"""
from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"

_STUBS = {
    "id": """#!/bin/sh
if [ "$1" = "-u" ]; then echo "${STUB_CURRENT_UID:-10001}"; exit 0; fi
echo "stub"
""",
    "stat": """#!/bin/sh
# 入口只用 `stat -c '%u' /data` / `stat -c '%g' /data`
echo "${STUB_DATA_UID:-10001}"
""",
    "chown": """#!/bin/sh
echo "chown $*" >> "${STUB_LOG}"
if [ "${STUB_CHOWN_FAILS:-0}" = "1" ]; then
  echo "chown: changing ownership: Operation not permitted" >&2
  exit 1
fi
exit 0
""",
    "chmod": """#!/bin/sh
echo "chmod $*" >> "${STUB_LOG}"
exit 0
""",
    "mkdir": """#!/bin/sh
echo "mkdir $*" >> "${STUB_LOG}"
exit 0
""",
    "gosu": """#!/bin/sh
echo "gosu $*" >> "${STUB_LOG}"
# gosu <uid>:<gid> <cmd...>：跳过身份参数后执行真实命令
shift
exec "$@"
""",
    "uvicorn": """#!/bin/sh
echo "uvicorn $*" >> "${STUB_LOG}"
exit 0
""",
}


@pytest.fixture
def stub_bin(tmp_path: Path) -> Path:
    """构造 stub 命令目录并返回（调用方通过 STUB_* 环境变量控制行为）。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in _STUBS.items():
        script = bin_dir / name
        script.write_text(body, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _prepare_script(data_dir: Path) -> Path:
    """生成常量折叠副本：把 /data 换成临时目录，其余逻辑逐字不变。

    本地没有 /data 挂载点，无法直接跑真实入口；按常量折叠复证决策逻辑。
    """
    text = ENTRYPOINT.read_text(encoding="utf-8")
    folded = text.replace("/data", str(data_dir))
    script = data_dir / "entrypoint.folded.sh"
    script.write_text(folded, encoding="utf-8")
    return script


def _run_entrypoint(stub_bin: Path, log: Path, env: dict, data_dir: Path):
    run_env = {
        "PATH": f"{stub_bin}:/usr/bin:/bin",
        "PORT": "8080",
        "LOG_LEVEL": "INFO",
        "STUB_LOG": str(log),
    }
    run_env.update(env)
    return subprocess.run(
        ["sh", str(_prepare_script(data_dir))],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(data_dir),
    )


def _logged(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [line.strip() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestEntrypointPrivilegeDrop:
    def test_non_root_container_runs_directly(self, stub_bin, tmp_path):
        """Dockerfile 已 USER app：非 root 启动直接 exec，不碰属主。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        log = data_dir / "calls.log"
        result = _run_entrypoint(
            stub_bin, log, {"STUB_CURRENT_UID": "10001"}, data_dir
        )
        assert result.returncode == 0, result.stderr
        calls = _logged(log)
        assert any(c.startswith("uvicorn ") for c in calls)
        assert not any(c.startswith("gosu ") for c in calls)
        assert not any(c.startswith("chown ") for c in calls)

    def test_root_start_chowns_then_drops_via_gosu(self, stub_bin, tmp_path):
        """root 启动且 chown 成功：修正归属后经 gosu 降权到非 root。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        log = data_dir / "calls.log"
        result = _run_entrypoint(
            stub_bin,
            log,
            {"STUB_CURRENT_UID": "0", "STUB_DATA_UID": "0"},
            data_dir,
        )
        assert result.returncode == 0, result.stderr
        calls = _logged(log)
        assert any(c.startswith("chown -R 10001:10001") for c in calls)
        assert any(c.startswith("gosu 10001:10001 uvicorn ") for c in calls)

    def test_root_start_chown_failure_is_fail_closed(self, stub_bin, tmp_path):
        """chown 失败必须非零退出且不启动服务——绝不回退到 root 运行。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        log = data_dir / "calls.log"
        result = _run_entrypoint(
            stub_bin,
            log,
            {
                "STUB_CURRENT_UID": "0",
                "STUB_DATA_UID": "0",
                "STUB_CHOWN_FAILS": "1",
            },
            data_dir,
        )
        assert result.returncode != 0
        # 折叠副本里 /data 已被替换为临时路径，只断言消息主体
        assert "无法把" in result.stderr and "归属改为" in result.stderr
        calls = _logged(log)
        assert not any(c.startswith("uvicorn ") for c in calls)
        assert not any(c.startswith("gosu ") for c in calls)

    def test_auto_fix_disabled_skips_chown_but_still_drops(self, stub_bin, tmp_path):
        """APP_AUTO_FIX_DATA_PERMS=0：跳过属主修正，仍经 gosu 降权。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        log = data_dir / "calls.log"
        result = _run_entrypoint(
            stub_bin,
            log,
            {
                "STUB_CURRENT_UID": "0",
                "STUB_DATA_UID": "0",
                "APP_AUTO_FIX_DATA_PERMS": "0",
            },
            data_dir,
        )
        assert result.returncode == 0, result.stderr
        calls = _logged(log)
        assert not any(c.startswith("chown ") for c in calls)
        assert any(c.startswith("gosu 10001:10001 uvicorn ") for c in calls)

    def test_root_start_with_non_root_volume_still_drops(self, stub_bin, tmp_path):
        """卷属主本就是非 root：chown 是幂等修正，最终仍降权到 app。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        log = data_dir / "calls.log"
        result = _run_entrypoint(
            stub_bin,
            log,
            {"STUB_CURRENT_UID": "0", "STUB_DATA_UID": "10001"},
            data_dir,
        )
        assert result.returncode == 0, result.stderr
        calls = _logged(log)
        assert any(c.startswith("gosu 10001:10001 uvicorn ") for c in calls)

    def test_entrypoint_never_falls_back_to_root_uvicorn(self, stub_bin, tmp_path):
        """回归护栏：入口里不得再出现「卷属主为 root 就保持 root」的分支。"""
        text = ENTRYPOINT.read_text(encoding="utf-8")
        assert "keep root" not in text
        # root 分支（非 root 早退之后）下必须全部经过 gosu，不允许裸 exec uvicorn
        root_branch = text.split("# 以 root 启动时", 1)[1]
        # exec 可能跨行续行，先拼接再找「exec ... uvicorn」片段
        joined = " ".join(
            line.rstrip("\\").strip() for line in root_branch.splitlines()
        )
        bare_exec = re.findall(r"exec\s+uvicorn\b", joined)
        assert not bare_exec, f"root 分支存在未降权的裸 exec uvicorn: {bare_exec}"
        assert "gosu" in joined, "root 分支必须经 gosu 降权"
