#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2E 自替换测试核心：被两个壳（old/new）调用，逻辑与工具箱一致。

旧版流程：check_update → download → install_and_restart（不返回）
新版流程：写标记文件 + 重试清理 .old + 退出 0
"""
import os
import sys
import tempfile
import time

import updater


def _marker():
    return os.path.join(tempfile.gettempdir(), "e2e_done.txt")


def main(app_v):
    if updater.version_cmp(app_v, "1.0") >= 0:
        # ── 新版本进程：证明重启成功 ──
        with open(_marker(), "w", encoding="utf-8") as f:
            f.write(f"APP_V={app_v}")
        old = sys.executable + ".old"
        for _ in range(50):                      # 等旧进程退出后删 .old
            if not os.path.exists(old):
                break
            try:
                os.remove(old)
            except OSError:
                time.sleep(0.1)
        sys.exit(0)

    # ── 旧版本进程：走完整更新链路 ──
    info = updater.check_update(app_v)
    if info is None:
        print("E2E_CHECK_FAILED:", updater.last_error)
        sys.exit(1)
    tmp = updater.download(info)
    updater.install_and_restart(tmp)
    print("E2E_INSTALL_RETURNED")                # 不应到达
    sys.exit(2)
