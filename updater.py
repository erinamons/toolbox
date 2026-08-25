#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
updater.py — 工具箱自动更新模块（纯标准库，无 Qt 依赖）
=========================================================
打包约束：build_exe.py 排除了 PySide6.QtNetwork，因此本模块
只允许使用 Python 标准库（urllib / hashlib / json / subprocess …），
禁止 import 任何 PySide6 网络模块，否则打包后的 exe 会缺模块崩溃。

清单协议（update.json）：
{
  "latest":    "1.2",                          最新版本号
  "url":       "https://…/工具箱-1.2.exe",      新版下载地址
  "sha256":    "小写十六进制 64 位",             新版文件校验和
  "size":      12345678,                       可选：字节数
  "notes":     "修复了……",                      可选：更新说明
  "mandatory": false                           可选：强制更新
}

便携 exe 自替换流程（Windows，PyInstaller --onefile）：
  1. 下载新 exe 到临时文件并校验 SHA-256
  2. 把正在运行的 exe 改名为 xxx.exe.old（Windows 允许 rename 运行中的 exe，
     但不允许删除或覆盖）
  3. 把新 exe 移动到原路径（失败则回滚）
  4. 启动新 exe 并立即退出当前进程（os._exit，避免 Qt 清理占用文件）
  5. 新版启动时调用 cleanup_old_files() 删除残留的 .old

测试钩子：环境变量 TOOLBOX_UPDATE_URL 可覆盖清单地址，
用于本地 HTTP 服务器端到端验证自替换，不影响正式发布。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

APP_NAME = "工具箱"
APP_ID = "Toolbox"          # HTTP User-Agent 必须 ASCII（header 仅支持 latin-1）
MANIFEST_URL = os.environ.get(
    "TOOLBOX_UPDATE_URL", "https://mochizuki.top/downloads/update.json"
)

_CHUNK = 64 * 1024            # 下载分块 64 KB
_MANIFEST_TIMEOUT = 5         # 清单请求超时（秒）
_DOWNLOAD_TIMEOUT = 30        # 下载读超时（秒）

# check_update 失败时记录原因，供 UI 在"手动检查"场景提示
last_error = ""


class UpdateError(Exception):
    """更新流程中的可预期错误（网络 / 校验 / 环境）。"""


class UpdateInfo:
    """一份通过基本校验的新版本清单信息。"""

    __slots__ = ("latest", "url", "sha256", "size", "notes", "mandatory")

    def __init__(self, latest, url, sha256, size=0, notes="", mandatory=False):
        self.latest = str(latest)
        self.url = str(url)
        self.sha256 = str(sha256).lower()
        self.size = int(size or 0)
        self.notes = str(notes or "")
        self.mandatory = bool(mandatory)

    def __repr__(self):
        return f"<UpdateInfo {self.latest} {self.size}B sha256={self.sha256[:8]}…>"


# ── 版本比较 ────────────────────────────────────────────────

def parse_version(s):
    """把 '1.2.3' 解析成可比较的整数元组 (1, 2, 3)。

    元组比较保证 (1, 10) > (1, 9)，字符串比较会把 '1.10' 判成小于 '1.9'。
    非数字段（如 '2a'）取前导数字，取不到按 0 处理，绝不抛异常。
    """
    parts = []
    for seg in str(s).strip().split("."):
        num = ""
        for ch in seg.strip():
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def version_cmp(v1, v2):
    """比较两个版本号，返回 -1 / 0 / 1。

    先补零到等长再比，保证 1.2 == 1.2.0（直接元组比较会把
    (1,2) 判成小于 (1,2,0)，导致同版本误报更新）。
    """
    t1, t2 = parse_version(v1), parse_version(v2)
    n = max(len(t1), len(t2))
    t1 += (0,) * (n - len(t1))
    t2 += (0,) * (n - len(t2))
    return (t1 > t2) - (t1 < t2)


# ── 清单获取与检查 ──────────────────────────────────────────

def fetch_manifest(url=None, timeout=_MANIFEST_TIMEOUT):
    """拉取并校验 update.json，返回 UpdateInfo；失败抛 UpdateError。

    url 为 None 时使用模块级 MANIFEST_URL（不作为默认参数值绑定，
    保证环境变量/测试注入生效）。
    """
    if url is None:
        url = MANIFEST_URL
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_ID}-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1 << 20)  # 清单不可能超过 1 MiB
    except Exception as e:
        raise UpdateError(f"无法获取更新清单：{e}") from e

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise UpdateError("更新清单不是有效的 JSON") from e
    if not isinstance(data, dict):
        raise UpdateError("更新清单格式错误")

    for key in ("latest", "url", "sha256"):
        if not data.get(key):
            raise UpdateError(f"更新清单缺少字段 {key}")

    sha = str(data["sha256"]).lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise UpdateError("更新清单的 sha256 字段格式错误")

    return UpdateInfo(
        latest=data["latest"],
        url=data["url"],
        sha256=sha,
        size=data.get("size", 0),
        notes=data.get("notes", ""),
        mandatory=data.get("mandatory", False),
    )


def check_update(current_version, respect_skip=True, url=None):
    """检查更新。有新版返回 UpdateInfo，无新版或失败返回 None。

    失败原因写入模块级 last_error（静默检查不打扰用户，
    手动检查时 UI 可读取它提示失败原因）。
    """
    global last_error
    last_error = ""
    try:
        info = fetch_manifest(url)
    except UpdateError as e:
        last_error = str(e)
        return None
    if version_cmp(info.latest, current_version) <= 0:
        return None
    if respect_skip and get_skip_version() == info.latest:
        return None
    return info


# ── 下载与校验 ──────────────────────────────────────────────

def download(info, dest_dir=None, progress_cb=None, cancel_event=None):
    """下载新版本到临时文件，校验 SHA-256，成功返回临时文件路径。

    progress_cb(downloaded, total)：进度回调，total 可能为 0
    （服务器未返回 Content-Length），回调抛异常不会中断下载。
    cancel_event.is_set() 为真时中止并清理半成品。
    仅打包后（sys.frozen）允许调用，源码运行直接拒绝。
    """
    if not is_frozen():
        raise UpdateError("源码运行模式不支持自动下载，请手动更新")

    fd, tmp_path = tempfile.mkstemp(prefix="toolbox_update_", suffix=".exe", dir=dest_dir)
    os.close(fd)
    downloaded = 0
    hasher = hashlib.sha256()
    try:
        req = urllib.request.Request(info.url, headers={"User-Agent": f"{APP_ID}-Updater"})
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            with open(tmp_path, "wb") as f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateError("已取消下载")
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            pass

        actual = hasher.hexdigest()
        if actual != info.sha256:
            raise UpdateError(f"SHA-256 校验失败\n期望 {info.sha256}\n实际 {actual}")
        if info.size and downloaded != info.size:
            raise UpdateError(f"文件大小不符：期望 {info.size} B，实际 {downloaded} B")
        return tmp_path
    except UpdateError:
        _safe_remove(tmp_path)
        raise
    except Exception as e:
        _safe_remove(tmp_path)
        raise UpdateError(f"下载失败：{e}") from e


# ── 自替换安装 ──────────────────────────────────────────────

def install_and_restart(new_exe_path):
    """自替换并重启。成功后当前进程立即退出，本函数不返回。

    步骤：rename 旧 exe 为 .old → 新 exe 移到原路径（失败回滚）
    → 启动新 exe → os._exit(0)。
    """
    if not is_frozen():
        raise UpdateError("源码运行模式不支持自动安装，请手动更新")

    exe_path = sys.executable            # onefile 模式下即 exe 本体
    old_path = exe_path + ".old"

    _safe_remove(old_path)               # 清理更早的残留
    try:
        os.rename(exe_path, old_path)    # Windows 允许 rename 运行中的 exe
    except OSError as e:
        raise UpdateError(f"无法重命名当前程序：{e}") from e

    try:
        shutil.move(new_exe_path, exe_path)
    except OSError:
        _rollback(exe_path, old_path)
        raise UpdateError("写入新版本失败，已回滚到当前版本")

    try:
        # 剥离 PyInstaller onefile 的内部环境变量（_PYI_* / _MEIPASS2）。
        # PyInstaller 6.14+ 的子进程 bootloader 会依据 _PYI_PARENT_PROCESS_LEVEL
        # 校验父进程链：若这些变量被继承，新 exe 会把旧 exe 进程当作
        # onefile 父进程做安全校验，报
        # "Security validation failure: parent process has different executable"
        # 并拒绝启动。剥离后新 exe 以顶级进程身份干净启动。
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and k != "_MEIPASS2" and k != "_MEIPASS"
        }
        subprocess.Popen(
            [exe_path],
            cwd=os.path.dirname(exe_path) or None,
            env=env,
            close_fds=True,
        )
    except OSError:
        # 新版没启动起来也不回滚文件：文件已是新版，用户可手动打开
        pass

    # PyInstaller 6.11+ onefile 引导器启动时会做父进程安全校验，
    # 父进程过早退出会报 "failed to obtain executable path for
    # parent process" 并拒绝启动，因此延迟退出给它留出校验窗口。
    import time
    time.sleep(1.5)
    os._exit(0)                          # 立即退出，避免 Qt 清理期间产生文件锁竞争


def cleanup_old_files():
    """新版启动时调用：删除升级残留的 .old（旧进程退出后锁已释放）。

    删除失败静默跳过（旧进程可能尚未完全退出，下次启动再删）。
    源码运行模式直接跳过（此时 sys.executable 是 python 解释器）。
    """
    if not is_frozen():
        return
    exe_path = sys.executable
    _safe_remove(exe_path + ".old")


# ── 跳过版本持久化 ─────────────────────────────────────────

def _state_path():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, APP_NAME, "updater")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "state.json")


def get_skip_version():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return str(json.load(f).get("skip_version", ""))
    except Exception:
        return ""


def set_skip_version(version):
    """记住用户跳过的版本；写不进去也不致命（最多多提示一次）。"""
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump({"skip_version": str(version)}, f)
    except OSError:
        pass


# ── 内部工具 ────────────────────────────────────────────────

def is_frozen():
    """是否运行在 PyInstaller 打包后的 exe 中。"""
    return bool(getattr(sys, "frozen", False))


def _safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _rollback(exe_path, old_path):
    try:
        if os.path.exists(old_path) and not os.path.exists(exe_path):
            os.rename(old_path, exe_path)
    except OSError:
        pass
