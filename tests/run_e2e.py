#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_DATA_DIR = Path("/tmp/tg_signpulse_e2e")

def cleanup_data_dir():
    if TEST_DATA_DIR.exists():
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

def wait_for_url(url: str, timeout: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "E2E-HealthCheck"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 304):
                    return True
        except Exception:
            time.sleep(0.4)
    return False

def ensure_edge_running():
    script_path = Path("/Users/adair/.gemini/config/skills/edge-cdp-test/scripts/launch-edge.sh")
    res = subprocess.run(["bash", str(script_path)], capture_output=True, text=True)
    print("Edge 状态:\n", res.stdout.strip())

def main():
    cleanup_data_dir()
    ensure_edge_running()

    backend_env = os.environ.copy()
    backend_env["APP_DATA_DIR"] = str(TEST_DATA_DIR)
    backend_env["ADMIN_PASSWORD"] = "adminpassword123"
    backend_env["PYTHONPATH"] = str(ROOT_DIR)

    backend_cmd = [
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning"
    ]

    frontend_cmd = [
        "npm", "--prefix", "frontend", "run", "dev", "--", "--port", "5173", "--host", "127.0.0.1"
    ]

    print("⚡ 启动后端服务 (FastAPI, 127.0.0.1:8080)...")
    backend_proc = subprocess.Popen(backend_cmd, cwd=str(ROOT_DIR), env=backend_env)

    print("⚡ 启动前端服务 (Vite, 127.0.0.1:5173)...")
    frontend_proc = subprocess.Popen(frontend_cmd, cwd=str(ROOT_DIR))

    success = False
    try:
        print("⏳ 等待后端健康检查 (http://127.0.0.1:8080/health)...")
        if not wait_for_url("http://127.0.0.1:8080/health", timeout=20.0):
            raise RuntimeError("后端服务启动超时")
        print("✅ 后端服务已就绪")

        print("⏳ 等待前端 Vite 服务 (http://127.0.0.1:5173/)...")
        if not wait_for_url("http://127.0.0.1:5173/", timeout=20.0):
            raise RuntimeError("前端服务启动超时")
        print("✅ 前端服务已就绪")

        print("🏁 执行 Edge CDP 浏览器自动化测试...")
        test_res = subprocess.run(
            ["node", str(ROOT_DIR / "tests" / "e2e_edge_test.mjs")],
            cwd=str(ROOT_DIR),
        )
        if test_res.returncode == 0:
            success = True
        else:
            print(f"❌ 浏览器自动化测试返回非零退出码: {test_res.returncode}")

    finally:
        print("🧹 正在清理与关闭本地服务...")
        for proc, _name in [(frontend_proc, "Frontend"), (backend_proc, "Backend")]:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
        print("✅ 服务已完全退出")

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
