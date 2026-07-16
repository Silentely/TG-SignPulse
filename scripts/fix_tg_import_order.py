from pathlib import Path
import re

pkg = Path(__file__).resolve().parents[1] / "backend" / "services" / "telegram"
for name in ["login_phone.py", "login_qr.py", "accounts.py", "devices.py"]:
    p = pkg / name
    t = p.read_text(encoding="utf-8")
    m = re.search(
        r"\nfrom backend\.services\.telegram\.sessions import \([^)]+\)\n",
        t,
        re.S,
    )
    if not m:
        print(name, "no sessions block")
        continue
    block = m.group(0).lstrip("\n")
    t2 = t[: m.start()] + "\n" + t[m.end() :]
    key = "from backend.core.config import get_settings\n"
    if key not in t2:
        print(name, "no get_settings import")
        continue
    t2 = t2.replace(key, key + block, 1)
    p.write_text(t2, encoding="utf-8")
    print("fixed", name)
