#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包脚本：排除无用 Qt 模块，压缩体积。"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
# 用 python -m PyInstaller 而非 pyinstaller.exe shim（后者在本机环境会静默退出）
PYI_CMD = [sys.executable, "-m", "PyInstaller"]

EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtSql", "PySide6.QtXml", "PySide6.QtPdf",
    "PySide6.QtTest", "PySide6.QtPrintSupport",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSerialBus", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets",
    "PySide6.QtHelp", "PySide6.QtXmlPatterns",
]

cmd = PYI_CMD + ["--noconfirm", "--onefile", "--windowed",
       "--name", "工具箱",
       "--icon", "assets/toolbox.ico",
       "--add-data", "assets;assets",
       "--add-data", "win95.qss;."]

# MediaInfo / 视频压缩工具依赖 bin/ffprobe.exe 与 bin/ffmpeg.exe（ffmpeg 官方 build 内含）
for binary in ("ffprobe.exe", "ffmpeg.exe"):
    binary_path = os.path.join(BASE, "bin", binary)
    if os.path.isfile(binary_path):
        cmd += ["--add-binary", binary_path + ";bin"]
    else:
        print(f"[WARN] bin/{binary} 不存在，相关工具在单文件包内将不可用")

for m in EXCLUDES:
    cmd += ["--exclude-module", m]
cmd.append("toolbox.py")

print("Running:", " ".join(cmd[:10]), "...")
r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[-2000:] if r.stdout else "")
print(r.stderr[-2000:] if r.stderr else "")
sys.exit(r.returncode)
