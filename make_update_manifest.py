#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布脚本：为 dist/工具箱.exe 生成网站更新清单。

用法：
    python make_update_manifest.py <版本号> [更新说明]
    python make_update_manifest.py 1.2 "新增 XXX 工具；修复 PDF 转换崩溃"

产物（写到 release/ 目录）：
    release/工具箱-<版本>.exe      建议的上传文件名（ASCII 安全名可选）
    release/update.json            更新清单（上传到网站下载根目录）

清单字段与 updater.py 协议一致：
    latest / url / sha256 / size / notes / mandatory
"""
import argparse
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# 网站下载根目录（发布后 update.json 与 exe 都放这里）
DOWNLOAD_BASE_URL = "https://mochizuki.top/downloads"

# exe 在服务器上的文件名：用 ASCII 名避免 URL 编码问题
REMOTE_EXE_NAME = "toolbox-latest.exe"     # 固定名：客户端只认清单 URL


def main():
    ap = argparse.ArgumentParser(description="生成工具箱更新清单")
    ap.add_argument("version", help="新版版本号，如 1.2")
    ap.add_argument("notes", nargs="?", default="", help="更新说明（可省略）")
    ap.add_argument("--mandatory", action="store_true", help="标记为强制更新")
    ap.add_argument("--exe", default=os.path.join(BASE, "dist", "工具箱.exe"),
                    help="exe 路径（默认 dist/工具箱.exe）")
    ap.add_argument("--out", default=os.path.join(BASE, "release"),
                    help="输出目录（默认 release/）")
    args = ap.parse_args()

    if not os.path.isfile(args.exe):
        sys.exit(f"找不到 exe：{args.exe}")

    with open(args.exe, "rb") as f:
        data = f.read()
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    # 1) 版本化副本（存档用）
    archive_name = f"toolbox-{args.version}.exe"
    archive_path = os.path.join(out_dir, archive_name)
    with open(archive_path, "wb") as f:
        f.write(data)

    # 2) 固定名副本（网站下载目标）
    latest_path = os.path.join(out_dir, REMOTE_EXE_NAME)
    with open(latest_path, "wb") as f:
        f.write(data)

    # 3) 清单
    manifest = {
        "latest": args.version,
        "url": f"{DOWNLOAD_BASE_URL}/{REMOTE_EXE_NAME}",
        "sha256": sha256,
        "size": size,
        "notes": args.notes,
        "mandatory": bool(args.mandatory),
    }
    manifest_path = os.path.join(out_dir, "update.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"版本        : {args.version}")
    print(f"SHA-256     : {sha256}")
    print(f"大小        : {size:,} bytes ({size / 1048576:.1f} MB)")
    print(f"强制更新    : {'是' if args.mandatory else '否'}")
    print()
    print("产物：")
    print(f"  {archive_path}")
    print(f"  {latest_path}")
    print(f"  {manifest_path}")
    print()
    print(f"上传步骤：把 {REMOTE_EXE_NAME} 和 update.json 上传到")
    print(f"{DOWNLOAD_BASE_URL}/ 对应的网站目录即可。")


if __name__ == "__main__":
    main()
