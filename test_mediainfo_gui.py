# -*- coding: utf-8 -*-
"""MediaInfo GUI 冒烟测试：离屏实例化 → 添加文件 → 等解析 → 断言树内容。"""
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

from tools.mediainfo_tool import MediaInfoTool  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.path.join(BASE, "bin", "ffmpeg.exe")
SAMPLE = os.path.join(BASE, "bin", "_sample_gui.mp4")


def main():
    subprocess.run([
        FFMPEG, "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        SAMPLE,
    ], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

    app = QApplication.instance() or QApplication([])
    tool = MediaInfoTool()

    result = {}

    def check():
        # 树中应有 General / Video / Audio 三个分区
        tops = [tool.tree.topLevelItem(i).text(0) for i in range(tool.tree.topLevelItemCount())]
        result["tops"] = tops
        result["status"] = tool.lbl_status.text()
        result["file_count"] = tool.list_files.count()
        app.quit()

    tool.list_files.addItem(SAMPLE)
    tool._start_probe()
    QTimer.singleShot(4000, check)
    app.exec()

    print("files:", result.get("file_count"))
    print("tree tops:", result.get("tops"))
    print("status:", result.get("status"))

    tops = result.get("tops") or []
    ok = (
        result.get("file_count") == 1
        and any("General" in t for t in tops)
        and any("Video" in t for t in tops)
        and any("Audio" in t for t in tops)
    )

    # 复制当前信息 → 剪贴板非空
    if ok:
        tool._copy_current()
        from PySide6.QtGui import QGuiApplication
        clip = QGuiApplication.clipboard().text()
        ok = "General" in clip and "Video" in clip
        print("clipboard bytes:", len(clip))

    if os.path.isfile(SAMPLE):
        os.remove(SAMPLE)
    print("MEDIAINFO_GUI_OK" if ok else "MEDIAINFO_GUI_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
