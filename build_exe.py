#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包脚本：排除无用 Qt 模块，压缩体积。"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PYI = os.path.join(os.path.dirname(sys.executable), "pyinstaller.exe")

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

cmd = [PYI, "--noconfirm", "--onefile", "--windowed",
       "--name", "工具箱",
       "--icon", "assets/toolbox.ico",
       "--add-data", "assets;assets",
       "--add-data", "win95.qss;."]
for m in EXCLUDES:
    cmd += ["--exclude-module", m]
cmd.append("toolbox.py")

print("Running:", " ".join(cmd[:10]), "...")
r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout[-2000:] if r.stdout else "")
print(r.stderr[-2000:] if r.stderr else "")
sys.exit(r.returncode)
