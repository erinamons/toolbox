#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release.py — 工具箱一键发版脚本（调用网站 releases API）。

一条命令完成：打包 → 算哈希 → 创建草稿版本 → 上传安装包 → 发布。

用法：
    python release.py 1.2 "新增 XXX；修复 YYY"
    python release.py 1.2 "说明" --mandatory
    python release.py 1.2 "说明" --no-build          # 跳过打包，用现成 dist/工具箱.exe
    python release.py 1.2 "说明" --exe D:/pkg/工具箱.zip   # 直接发布指定安装包（跳过打包）
    python release.py 1.2 "说明" --base http://127.0.0.1:3000   # 指定站点基址
    python release.py 1.2 "说明" --dry-run           # 只演练，不真正调 API（无需令牌）

发布令牌来源（优先级从高到低）：
    1. --token 参数
    2. 环境变量 TOOLBOX_RELEASE_TOKEN
    3. toolbox-release.json（本目录，形如 {"token": "dl_xxx"}，已加入 .gitignore）

与旧流程的关系：
    make_update_manifest.py 仍可用于离线生成清单归档，
    但正式发版一律走本脚本（服务器权威、带下载计数与反馈闭环）。

API 端点（Bearer 发布令牌认证）：
    POST   /api/downloads/{app}/releases                 创建草稿
    POST   /api/downloads/{app}/releases/{v}/assets      上传安装包（multipart）
    POST   /api/downloads/{app}/releases/{v}/publish     发布
    GET    /api/downloads/{app}/update.json              验证清单已生效
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.path.dirname(os.path.abspath(__file__))

APP_SLUG = "toolbox"
DEFAULT_BASE = "https://mochizuki.top"
TOKEN_FILE = os.path.join(BASE, "toolbox-release.json")
EXE_PATH = os.path.join(BASE, "dist", "工具箱.exe")

ASSET_EXTS = {".exe", ".zip", ".7z", ".msi", ".gz", ".bz2"}


class ReleaseError(RuntimeError):
    pass


# 本机代理常会劫持 127.0.0.1 请求（返回 502），发往内网/本机站点时必须直连。
_PROXY_BYPASS_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_open(req, timeout):
    host = urllib.parse.urlparse(req.full_url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1") or host.startswith("192.168.") or host.startswith("10."):
        return _PROXY_BYPASS_OPENER.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


# ---------- 令牌 ----------

def load_token(cli_token: str | None) -> str:
    if cli_token:
        return cli_token.strip()
    env = os.environ.get("TOOLBOX_RELEASE_TOKEN", "").strip()
    if env:
        return env
    if os.path.isfile(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            tok = str(data.get("token", "")).strip()
            if tok.startswith("dl_"):
                return tok
            raise ReleaseError(f"{TOKEN_FILE} 中 token 不合法（应以 dl_ 开头）")
        except json.JSONDecodeError as exc:
            raise ReleaseError(f"{TOKEN_FILE} 不是合法 JSON：{exc}") from exc
    raise ReleaseError(
        "未找到发布令牌。请任选其一：\n"
        "  1) 后台「软件发布」面板新建应用 toolbox 并签发令牌（明文只显示一次）\n"
        "  2) set TOOLBOX_RELEASE_TOKEN=dl_xxx\n"
        "  3) 把 {\"token\": \"dl_xxx\"} 写入 toolbox-release.json"
    )


# ---------- HTTP ----------

def api_json(base: str, token: str, method: str, path: str, payload: dict | None = None,
             timeout: int = 30) -> dict:
    """调用 JSON API（创建草稿 / 发布 / 查询）。"""
    url = base.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with _http_open(req, timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ReleaseError(f"{method} {path} → HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseError(f"{method} {path} 网络失败：{exc.reason}") from exc


def upload_asset(base: str, token: str, version: str, exe_path: str, sha256: str,
                 timeout: int = 1800) -> dict:
    """multipart/form-data 上传安装包。

    exe 通常 < 100 MB，整体读入内存后一次性发送，比流式回调更简单可靠；
    服务端会用流式 SHA-256 再校验一次，哈希不符即拒绝。
    """
    url = f"{base.rstrip('/')}/api/downloads/{APP_SLUG}/releases/{version}/assets"
    boundary = "----toolboxrelease" + uuid.uuid4().hex
    filename = os.path.basename(exe_path)

    head = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"sha256\"\r\n\r\n{sha256}\r\n"
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")

    with open(exe_path, "rb") as f:
        blob = f.read()
    body = head + blob + tail

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with _http_open(req, timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ReleaseError(f"上传失败 → HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseError(f"上传网络失败：{exc.reason}") from exc


# ---------- 构建 ----------

def build_exe() -> str:
    print("[1/6] PyInstaller 打包 …")
    result = subprocess.run(
        [sys.executable, os.path.join(BASE, "build_exe.py")],
        cwd=BASE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        raise ReleaseError("build_exe.py 打包失败")
    if not os.path.isfile(EXE_PATH):
        raise ReleaseError(f"打包产物不存在：{EXE_PATH}")
    print(f"      产物 {EXE_PATH}（{os.path.getsize(EXE_PATH) / 1048576:.1f} MB）")
    return EXE_PATH


def file_hash(path: str) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def validate_version(v: str) -> None:
    if not v or not all(part.isdigit() and 1 <= len(part) <= 4 for part in v.split(".")) or len(v.split(".")) > 4:
        raise ReleaseError(f"版本号不合法：{v}（应为 1、1.2、1.2.3 形式）")


def read_app_version() -> str:
    """从 toolbox.py 源码读取 APP_VERSION 常量。

    发布版本号必须与 exe 内置版本一致，否则用户「关于」页显示旧版本、
    且会陷入「提示更新→装到的还是旧版本」的死循环（v1.2 坏包事故）。
    """
    source_path = os.path.join(BASE, "toolbox.py")
    with open(source_path, "r", encoding="utf-8") as f:
        source = f.read()
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if not match:
        raise ReleaseError("toolbox.py 中未找到 APP_VERSION 常量")
    return match.group(1).strip()


def assert_version_consistency(version: str) -> str:
    """断言发布版本号 == toolbox.py 的 APP_VERSION，不一致直接拒发。"""
    app_version = read_app_version()
    if app_version != version:
        raise ReleaseError(
            f"版本不一致：发布版本 {version}，但 toolbox.py 的 APP_VERSION 是 {app_version}。\n"
            f"请先把 toolbox.py 的 APP_VERSION 改为 {version} 再发版，"
            f"否则用户「关于」页会显示错误版本并陷入更新死循环。"
        )
    return app_version


def main() -> None:
    ap = argparse.ArgumentParser(description="工具箱一键发版（releases API）")
    ap.add_argument("version", help="版本号，如 1.2")
    ap.add_argument("notes", nargs="?", default="", help="更新说明")
    ap.add_argument("--mandatory", action="store_true", help="强制更新")
    ap.add_argument("--no-build", action="store_true", help="跳过打包，用现成 dist/工具箱.exe")
    ap.add_argument("--exe", default=None, help="直接发布指定安装包文件（隐含 --no-build）")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"站点基址（默认 {DEFAULT_BASE}）")
    ap.add_argument("--token", default=None, help="发布令牌（优先级最高）")
    ap.add_argument("--dry-run", action="store_true", help="演练：只校验与算哈希，不调 API")
    args = ap.parse_args()

    validate_version(args.version)

    # 版本一致性：发布号必须等于 exe 内置 APP_VERSION（防止坏包，v1.2 事故防线）
    app_version = assert_version_consistency(args.version)

    # dry-run 无需令牌即可演练
    token = load_token(args.token) if not args.dry_run else (args.token or "dry-run-token")

    base = args.base.rstrip("/")

    if args.exe:
        exe = os.path.abspath(args.exe)
        if not os.path.isfile(exe):
            raise ReleaseError(f"--exe 指定的文件不存在：{exe}")
        print(f"[1/6] 使用指定安装包（--exe）")
    elif args.no_build:
        exe = EXE_PATH
        if not os.path.isfile(exe):
            raise ReleaseError(f"--no-build 但产物不存在：{exe}")
        print("[1/6] 跳过打包（--no-build）")
    else:
        exe = build_exe()

    print("[2/6] 计算 SHA-256 …")
    sha256, size = file_hash(exe)
    print(f"      sha256={sha256}")
    print(f"      size={size}（{size / 1048576:.1f} MB）")
    ext = os.path.splitext(exe)[1].lower()
    if ext not in ASSET_EXTS:
        raise ReleaseError(f"安装包扩展名不受支持：{ext}（支持 {'/'.join(sorted(ASSET_EXTS))}）")

    plan = {
        "app": APP_SLUG, "version": args.version, "app_version": app_version,
        "notes": args.notes,
        "mandatory": args.mandatory, "base": base, "exe": exe,
        "sha256": sha256, "size": size,
    }
    print("[3/6] 发版计划：")
    for key, value in plan.items():
        print(f"      {key} = {value}")
    if args.dry_run:
        print("DRY_RUN_OK（未调用任何 API）")
        return

    print("[4/6] 创建草稿版本 …")
    api_json(base, token, "POST", f"/api/downloads/{APP_SLUG}/releases",
             {"version": args.version, "notes": args.notes, "mandatory": args.mandatory})

    print("[5/6] 上传安装包（服务端会再校验一次 SHA-256）…")
    upload_asset(base, token, args.version, exe, sha256)

    print("[6/6] 发布版本 …")
    api_json(base, token, "POST", f"/api/downloads/{APP_SLUG}/releases/{args.version}/publish", {})

    manifest_url = f"{base}/downloads/{APP_SLUG}/update.json"
    print("等待清单生效 …")
    for _ in range(10):
        try:
            with _http_open(urllib.request.Request(manifest_url), 10) as resp:
                manifest = json.loads(resp.read().decode("utf-8"))
            if manifest.get("latest") == args.version and manifest.get("sha256") == sha256:
                print(f"清单已生效：{manifest_url}")
                print(f"  latest={manifest.get('latest')} url={manifest.get('url')}")
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        print(f"警告：清单 10 秒内未确认生效，请手动检查 {manifest_url}")

    print()
    print("发版完成：")
    print(f"  公开下载页 {base}/downloads.html")
    print(f"  更新清单   {manifest_url}")
    print(f"  安装包     {base}/downloads/{APP_SLUG}/{APP_SLUG}-{args.version}.exe")


if __name__ == "__main__":
    try:
        main()
    except ReleaseError as exc:
        print(f"发版失败：{exc}", file=sys.stderr)
        sys.exit(1)
