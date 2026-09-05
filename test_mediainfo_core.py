# -*- coding: utf-8 -*-
"""MediaInfo 工具核心逻辑自测：ffmpeg 生成样例 → ffprobe 解析 → 文本导出。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import ffprobe_utils  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(BASE, "bin", "_sample.mp4")
FFMPEG = os.path.join(BASE, "bin", "ffmpeg.exe")


def main():
    # 1. 生成 3 秒测试视频（视频 + 音频 + 字幕流 + 双语标签）
    if os.path.isfile(SAMPLE):
        os.remove(SAMPLE)
    cmd = [
        FFMPEG, "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30000/1001:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-x264-params", "profile=high10",
        "-c:a", "aac", "-b:a", "128k",
        "-metadata:s:v:0", "language=chi",
        "-metadata:s:a:0", "language=eng",
        "-metadata", "encoder=Lavf59.27.100",
        SAMPLE,
    ]
    subprocess.run(cmd, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    print("sample generated:", os.path.getsize(SAMPLE), "bytes")

    # 2. 定位 ffprobe
    exe = ffprobe_utils.find_ffprobe()
    assert exe and os.path.isfile(exe), "find_ffprobe 失败"
    print("ffprobe found:", exe)

    # 3. 解析
    info = ffprobe_utils.probe(SAMPLE)
    kinds = [s.get("codec_type") for s in info.get("streams", [])]
    assert "video" in kinds and "audio" in kinds, f"流类型缺失: {kinds}"
    print("streams:", kinds)

    # 4. 文本导出
    text = ffprobe_utils.to_mediainfo_text(SAMPLE, info)
    for expect in ("General", "Video", "Audio", "Complete name", "Pixel format", "Sampling rate", "fps"):
        assert expect in text, f"文本缺少 {expect}"
    print("--- MediaInfo text ---")
    print(text)
    assert ffprobe_utils.fmt_size(info["format"]["size"]).endswith("B")
    assert "fps" in ffprobe_utils.fmt_frame_rate("30000/1001")
    assert ffprobe_utils.fmt_duration(3725.5) == "1 h 2 min 5 s", ffprobe_utils.fmt_duration(3725.5)

    # 5. 损坏文件容错
    bad = os.path.join(BASE, "bin", "_bad.mp4")
    with open(bad, "wb") as f:
        f.write(b"not a video")
    try:
        ffprobe_utils.probe(bad)
        print("FAIL: 损坏文件未报错")
        return 1
    except RuntimeError:
        print("corrupt file correctly rejected")
    finally:
        os.remove(bad)

    os.remove(SAMPLE)
    print("MEDIAINFO_CORE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
