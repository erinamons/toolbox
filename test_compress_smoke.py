# -*- coding: utf-8 -*-
"""视频压缩工具冒烟测试：生成高码率样例 → 真实压缩 → 断言输出与体积下降。"""
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

from tools.compress_tool import CompressTool  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.path.join(BASE, "bin", "ffmpeg.exe")
SAMPLE = os.path.join(BASE, "bin", "_compress_src.mp4")


def main():
    # 高码率源（ultraquant 无所谓，码率拉高保证压缩有空间）
    subprocess.run([
        FFMPEG, "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        SAMPLE,
    ], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    src_size = os.path.getsize(SAMPLE)
    print("source size:", src_size)

    app = QApplication.instance() or QApplication([])
    tool = CompressTool()
    tool.list_files.addItem(SAMPLE)

    result = {}

    def check():
        result["logs"] = [tool.list_log.item(i).text() for i in range(tool.list_log.count())]
        result["status"] = tool.lbl_status.text()
        result["visible_progress"] = tool.progress.isVisible()
        app.quit()

    tool._start()
    QTimer.singleShot(30000, check)
    app.exec()

    logs = result.get("logs") or []
    print("logs:", logs)
    print("status:", result.get("status"))

    out = os.path.join(BASE, "bin", "compressed_output", "_compress_src.mp4")
    ok = False
    if os.path.isfile(out):
        out_size = os.path.getsize(out)
        print("output size:", out_size)
        ok = out_size < src_size and any("[OK]" in line for line in logs)
        # 清理
        os.remove(out)
        try:
            os.rmdir(os.path.dirname(out))
        except OSError:
            pass
    else:
        print("output missing:", out)

    if os.path.isfile(SAMPLE):
        try:
            os.remove(SAMPLE)
        except OSError:
            pass  # 清理失败不影响断言（残留文件下次覆盖）
    print("COMPRESS_SMOKE_OK" if ok else "COMPRESS_SMOKE_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
