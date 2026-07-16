#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
replacements = {
    "from .ai_tools": "from tg_signer.ai_tools",
    "from .async_utils": "from tg_signer.async_utils",
    "from .compat": "from tg_signer.compat",
    "from .log_utils": "from tg_signer.log_utils",
    "from .notification": "from tg_signer.notification",
    "from .utils": "from tg_signer.utils",
}
for rel in [
    "tg_signer/core/runtime.py",
    "tg_signer/core/client.py",
    "tg_signer/core/worker.py",
    "tg_signer/core/signer.py",
    "tg_signer/core/monitor.py",
]:
    p = ROOT / rel
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    orig = t
    for a, b in replacements.items():
        t = t.replace(a, b)
    if t != orig:
        p.write_text(t, encoding="utf-8")
        print("fixed", rel)
    else:
        print("no change", rel)
