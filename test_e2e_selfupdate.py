#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2E 自替换验证驱动：

1. PyInstaller 打包两个 console exe：e2e_old(0.9) / e2e_new(1.0)
2. 本地 HTTP 服务提供 update.json（1.0）+ 新版 exe 下载
3. 启动旧 exe → 应自动更新并重启为新 exe → 写标记文件后退出 0
4. 断言：标记内容 APP_V=1.0、旧 exe 原路径现为 1.0、.old 已被清理

通过输出 E2E_SELF_UPDATE_OK
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
WORK = tempfile.mkdtemp(prefix="e2e_selfupdate_")
STATE = os.environ.get("LOCALAPPDATA", WORK)
STATE_DIR = os.path.join(STATE, "工具箱", "updater")


def log(msg):
    print(f"[e2e] {msg}")


def build(tag):
    dist = os.path.join(WORK, tag)
    os.makedirs(dist, exist_ok=True)
    cmd = [
        PY, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--distpath", dist, "--workpath", os.path.join(WORK, f"b_{tag}"),
        "--specpath", os.path.join(WORK, f"s_{tag}"),
        os.path.join(BASE, f"e2e_{tag}_app.py"),
    ]
    log(f"building {tag} ...")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-1500:])
        print(r.stderr[-1500:])
        sys.exit(f"BUILD_{tag.upper()}_FAILED")
    exe = os.path.join(dist, f"e2e_{tag}_app.exe")
    assert os.path.isfile(exe), exe
    return exe


# ── 本地 HTTP 服务 ────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    exe_bytes = b""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/update.json":
            body = json.dumps({
                "latest": "1.0",
                "url": f"http://127.0.0.1:{self.server.server_port}/dl.exe",
                "sha256": hashlib.sha256(Handler.exe_bytes).hexdigest(),
                "size": len(Handler.exe_bytes),
                "notes": "E2E",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/dl.exe":
            body = Handler.exe_bytes
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    new_exe = build("new")                       # 先建新版（供下载）
    with open(new_exe, "rb") as f:
        Handler.exe_bytes = f.read()
    log(f"new exe: {len(Handler.exe_bytes)} bytes")

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"http server on :{port}")

    # 模拟用户安装位置：旧 exe 放到独立目录（与构建目录隔离）
    old_exe_src = build("old")
    target_dir = os.path.join(WORK, "installed")
    os.makedirs(target_dir, exist_ok=True)
    old_path = os.path.join(target_dir, "e2e_old_app.exe")
    shutil.copy2(old_exe_src, old_path)

    marker = os.path.join(tempfile.gettempdir(), "e2e_done.txt")
    if os.path.exists(marker):
        os.remove(marker)
    # 清理旧测试状态（跳过版本等）
    try:
        for f in os.listdir(STATE_DIR):
            os.remove(os.path.join(STATE_DIR, f))
    except OSError:
        pass

    env = dict(os.environ)
    env["TOOLBOX_UPDATE_URL"] = f"http://127.0.0.1:{port}/update.json"

    log("starting old exe (should self-update & restart as 1.0) ...")
    p = subprocess.Popen(
        [old_path], env=env, cwd=target_dir,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        out, _ = p.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        p.kill()
        sys.exit("E2E_TIMEOUT_OLD_PROCESS")
    if out and out.strip():
        log(f"old exe output: {out.strip()[:500]}")

    # 等新版进程写标记（最长 30 秒）
    content = ""
    for _ in range(300):
        if os.path.exists(marker):
            time.sleep(0.2)
            with open(marker, encoding="utf-8") as f:
                content = f.read()
            break
        time.sleep(0.1)
    if content != "APP_V=1.0":
        sys.exit(f"E2E_MARKER_MISSING (got {content!r})")
    log("marker OK: APP_V=1.0")

    # 原路径现在应是新版（与网站上的新 exe 字节一致）
    with open(old_path, "rb") as f:
        now_bytes = f.read()
    if now_bytes != Handler.exe_bytes:
        sys.exit("E2E_EXE_NOT_REPLACED")
    log("exe at original path == new 1.0 build")

    # .old 应已被新版进程清理
    for _ in range(60):
        if not os.path.exists(old_path + ".old"):
            break
        time.sleep(0.5)
    if os.path.exists(old_path + ".old"):
        log("WARN: .old still exists (new process may have exited early)")
    else:
        log(".old cleaned")

    srv.shutdown()
    print("E2E_SELF_UPDATE_OK")


if __name__ == "__main__":
    main()
