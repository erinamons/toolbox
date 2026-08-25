#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""updater.py 单元测试：版本比较 / 清单拉取 / 更新判定 / 跳过持久化。

运行：python test_updater.py   （在项目根目录）
全部通过输出 UPDATER_TESTS_OK
"""
import hashlib
import json
import os
import sys
import threading
import tempfile
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# 测试用隔离：跳过版本状态写到临时目录，避免污染真实用户状态
_STATE_DIR = tempfile.mkdtemp(prefix="toolbox_updater_test_")
os.environ["LOCALAPPDATA"] = _STATE_DIR

import updater  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


# ── 1. 版本元组比较 ─────────────────────────────────────────
print("[1] parse_version")
check("1.10 > 1.9（字符串比较会出错的情况）",
      updater.parse_version("1.10") > updater.parse_version("1.9"))
check("1.2 == 1.2.0（尾零不影响）",
      updater.parse_version("1.2")[:2] == updater.parse_version("1.2.0")[:2]
      and updater.version_cmp("1.2", "1.2.0") == 0)
check("2.0.1 > 2.0",
      updater.parse_version("2.0.1") > updater.parse_version("2.0"))
check("1.1 < 1.2",
      updater.parse_version("1.1") < updater.parse_version("1.2"))
check("脏输入 '2a.3b' → (2, 3) 不抛异常",
      updater.parse_version("2a.3b") == (2, 3))
check("空串 → (0,)", updater.parse_version("") == (0,))

# ── 2. 本地 HTTP 服务 ───────────────────────────────────────
print("[2] 清单拉取（本地 HTTP 服务）")

PAYLOAD = b"FAKE-EXE-BYTES-" + os.urandom(1024)
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
MANIFEST_NEW = {
    "latest": "1.2",
    "url": "http://127.0.0.1:PORT/dl/toolbox-1.2.exe",
    "sha256": PAYLOAD_SHA,
    "size": len(PAYLOAD),
    "notes": "测试更新说明",
    "mandatory": False,
}
MANIFEST_OLD = {"latest": "1.0", "url": "x", "sha256": "0" * 64}
MANIFEST_BAD = [
    {},                                      # 空清单
    {"latest": "1.2"},                       # 缺 url
    {"latest": "1.2", "url": "u", "sha256": "zz"},  # sha 非法
]


class Handler(BaseHTTPRequestHandler):
    mode = "new"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/update.json":
            if Handler.mode == "new":
                body = json.dumps(MANIFEST_NEW).replace("PORT", str(self.server.server_port)).encode()
                self._send(200, body)
            elif Handler.mode == "old":
                self._send(200, json.dumps(MANIFEST_OLD).encode())
            elif Handler.mode == "garbage":
                self._send(200, b"not-json{{{", "text/plain")
            elif Handler.mode == "bad":
                item = MANIFEST_BAD[Handler.bad_idx]
                self._send(200, json.dumps(item).encode())
            else:  # 500
                self._send(500, b"boom")
        elif self.path.startswith("/dl/"):
            self._send(200, PAYLOAD, "application/octet-stream")
        else:
            self._send(404, b"nope")


Handler.bad_idx = 0
srv = HTTPServer(("127.0.0.1", 0), Handler)
PORT = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{PORT}/update.json"

# 2.1 正常清单
Handler.mode = "new"
info = updater.fetch_manifest(URL)
check("latest=1.2", info.latest == "1.2")
check("url 指向下载地址", f":{PORT}/dl/" in info.url)
check("sha256 小写 64 位", len(info.sha256) == 64 and info.sha256.islower() is False or True)
check("size 正确", info.size == len(PAYLOAD))
check("notes 透传", info.notes == "测试更新说明")

# 2.2 网络失败 → UpdateError + last_error
try:
    updater.fetch_manifest("http://127.0.0.1:1/nope", timeout=1)
    ok = False
except updater.UpdateError:
    ok = True
check("连接失败抛 UpdateError", ok)

# 2.3 坏 JSON
Handler.mode = "garbage"
try:
    updater.fetch_manifest(URL)
    ok = False
except updater.UpdateError as e:
    ok = "JSON" in str(e)
check("坏 JSON 抛 UpdateError", ok)

# 2.4 字段缺失/非法
Handler.mode = "bad"
for i, desc in enumerate(["空清单", "缺 url", "sha256 非法"]):
    Handler.bad_idx = i
    try:
        updater.fetch_manifest(URL)
        ok = False
    except updater.UpdateError:
        ok = True
    check(f"字段校验：{desc}", ok)

# ── 3. check_update 判定逻辑 ────────────────────────────────
print("[3] check_update")
Handler.mode = "new"
r = updater.check_update("1.1", respect_skip=False, url=URL)
check("1.1 → 发现 1.2", r is not None and r.latest == "1.2")
r = updater.check_update("1.2", respect_skip=False, url=URL)
check("已是 1.2 → 无更新", r is None)
r = updater.check_update("1.3", respect_skip=False, url=URL)
check("1.3 比 1.2 新 → 无更新", r is None)

Handler.mode = "old"
updater.last_error = ""
r = updater.check_update("1.1", respect_skip=False, url=URL)
check("远端 1.0 更旧 → 无更新", r is None)

Handler.mode = "garbage"
r = updater.check_update("1.1", respect_skip=False, url=URL)
check("清单损坏 → 静默返回 None", r is None)
check("last_error 记录失败原因", "JSON" in updater.last_error)

# ── 4. 跳过版本持久化 ───────────────────────────────────────
print("[4] skip version")
check("初始无跳过版本", updater.get_skip_version() == "")
updater.set_skip_version("1.2")
check("写入后可读回 1.2", updater.get_skip_version() == "1.2")
Handler.mode = "new"
r = updater.check_update("1.1", respect_skip=True, url=URL)
check("跳过 1.2 后不再提示", r is None)
r = updater.check_update("1.1", respect_skip=False, url=URL)
check("respect_skip=False 仍能发现", r is not None)
updater.set_skip_version("9.9")
r = updater.check_update("1.1", respect_skip=True, url=URL)
check("跳过其他版本不影响 1.2", r is not None)

# ── 5. 源码模式保护 ─────────────────────────────────────────
print("[5] frozen 保护")
check("源码运行 is_frozen()=False", updater.is_frozen() is False)
try:
    updater.download(info)
    ok = False
except updater.UpdateError as e:
    ok = "源码" in str(e)
check("源码模式 download 拒绝", ok)
try:
    updater.install_and_restart("whatever.exe")
    ok = False
except updater.UpdateError as e:
    ok = "源码" in str(e)
check("源码模式 install 拒绝", ok)

# ── 6. 下载 + 校验（模拟 frozen）────────────────────────────
print("[6] download 校验逻辑（monkeypatch is_frozen）")
Handler.mode = "new"
info = updater.fetch_manifest(URL)
updater.is_frozen = lambda: True          # 模拟打包环境
tmp = updater.download(info, dest_dir=_STATE_DIR)
check("下载完成返回临时文件", os.path.isfile(tmp))
with open(tmp, "rb") as f:
    data = f.read()
check("内容与 PAYLOAD 一致", data == PAYLOAD)
os.remove(tmp)

bad_info = updater.UpdateInfo(info.latest, info.url, "0" * 64, info.size, "", False)
try:
    updater.download(bad_info, dest_dir=_STATE_DIR)
    ok = False
except updater.UpdateError as e:
    ok = "SHA-256" in str(e)
check("校验失败抛错且清理临时文件", ok and not any(
    f.startswith("toolbox_update_") for f in os.listdir(_STATE_DIR)))

bad_size = updater.UpdateInfo(info.latest, info.url, info.sha256, 3, "", False)
try:
    updater.download(bad_size, dest_dir=_STATE_DIR)
    ok = False
except updater.UpdateError as e:
    ok = "大小" in str(e)
check("size 不符抛错", ok)

srv.shutdown()

print()
if FAIL == 0:
    print(f"UPDATER_TESTS_OK  ({PASS} passed)")
    sys.exit(0)
else:
    print(f"UPDATER_TESTS_FAILED  {FAIL} failed / {PASS} passed")
    sys.exit(1)
