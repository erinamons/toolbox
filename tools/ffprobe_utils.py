# -*- coding: utf-8 -*-
"""ffprobe 共享基建：二进制定位、JSON 解析、MediaInfo 风格文本导出。

供 MediaInfo 工具与后续的视频压缩工具共用。
"""
import json
import os
import shutil
import subprocess
import sys

# 支持拖入解析的媒体文件扩展名（视频 + 音频）
MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".ts", ".m2ts", ".mts", ".webm",
    ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".vob", ".ogv",
    ".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".ape", ".wv", ".tta",
}

_LAST_PROBE_ERROR = ""


def find_ffprobe():
    """定位 ffprobe 可执行文件。

    顺序：
      1. PyInstaller 解包目录 bin/ffprobe.exe（--add-binary 带入）
      2. 主程序所在目录 bin/ffprobe.exe（绿色分发）
      3. 源码根目录 bin/ffprobe.exe
      4. 系统 PATH
    返回绝对路径或 None。
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "bin", "ffprobe.exe"))
    base = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
    for root in (
        os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else None,
        base,
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ):
        if root:
            candidates.append(os.path.join(root, "bin", "ffprobe.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    found = shutil.which("ffprobe")
    return os.path.abspath(found) if found else None


def find_ffmpeg():
    """定位 ffmpeg 可执行文件，定位顺序同 find_ffprobe。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "bin", "ffmpeg.exe"))
    base = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
    for root in (
        os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else None,
        base,
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ):
        if root:
            candidates.append(os.path.join(root, "bin", "ffmpeg.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    found = shutil.which("ffmpeg")
    return os.path.abspath(found) if found else None


def probe(path, ffprobe_path=None, timeout=30):
    """解析媒体文件，返回 ffprobe JSON dict；失败抛 RuntimeError。"""
    global _LAST_PROBE_ERROR
    exe = ffprobe_path or find_ffprobe()
    if not exe:
        _LAST_PROBE_ERROR = (
            "未找到 ffprobe.exe。请将 ffprobe.exe 放到程序目录的 bin 文件夹下"
            "（ffmpeg 官方 build 内含），或加入系统 PATH。"
        )
        raise RuntimeError(_LAST_PROBE_ERROR)
    cmd = [
        exe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", "-show_chapters",
        path,
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as e:
        _LAST_PROBE_ERROR = f"解析超时（>{timeout}s）"
        raise RuntimeError(_LAST_PROBE_ERROR) from e
    except OSError as e:
        _LAST_PROBE_ERROR = f"无法启动 ffprobe：{e}"
        raise RuntimeError(_LAST_PROBE_ERROR) from e
    if result.returncode != 0:
        _LAST_PROBE_ERROR = (result.stderr or "").strip()[-300:] or f"ffprobe 退出码 {result.returncode}"
        raise RuntimeError(_LAST_PROBE_ERROR)
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as e:
        _LAST_PROBE_ERROR = "ffprobe 输出解析失败"
        raise RuntimeError(_LAST_PROBE_ERROR) from e


# ── 人类可读格式化 ──────────────────────────────────────────────

def fmt_size(value):
    """字节数 → 人类可读大小，如 1 234.5 MiB。"""
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(size)
    unit = units[0]
    for u in units:
        unit = u
        if size < 1024 or u == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:,.1f} {unit}".replace(",", " ")


def fmt_duration(seconds):
    """秒 → MediaInfo 风格时长，如 1 h 23 min / 2 min 5 s / 45 s 300 ms。"""
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if hours or minutes:
        parts.append(f"{minutes} min")
    parts.append(f"{int(secs)} s" if secs >= 1 else f"{int(secs * 1000)} ms")
    return " ".join(parts)


def fmt_bitrate(bps):
    """比特率 → MediaInfo 风格，如 5 126 kb/s。"""
    try:
        value = float(bps)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.3f} Mb/s".replace(",", " ")
    return f"{value / 1000:,.0f} kb/s".replace(",", " ")


def fmt_frame_rate(ratio):
    """'30000/1001' → '29.970 fps'。"""
    if not ratio:
        return ""
    try:
        if "/" in str(ratio):
            num, den = str(ratio).split("/", 1)
            num, den = float(num), float(den)
            if den <= 0 or num <= 0:
                return ""
            return f"{num / den:.3f} fps"
        value = float(ratio)
        return f"{value:.3f} fps" if value > 0 else ""
    except (TypeError, ValueError):
        return ""


def fmt_dimension(value):
    """'1920' → '1 920 pixels'（MediaInfo 千分位风格）。"""
    try:
        return f"{int(value):,} pixels".replace(",", " ")
    except (TypeError, ValueError):
        return ""


LANG_MAP = {
    "chi": "Chinese", "zho": "Chinese", "eng": "English", "jpn": "Japanese",
    "kor": "Korean", "und": "未指定",
}


def fmt_language(tag_value):
    if not tag_value:
        return ""
    key = str(tag_value).lower()
    return LANG_MAP.get(key, str(tag_value))


# ── MediaInfo 风格文本导出 ─────────────────────────────────────

def _stream_language(stream):
    tags = stream.get("tags") or {}
    return fmt_language(tags.get("language"))


def _video_lines(stream):
    lines = []
    add = lines.append
    add(("ID", str(stream.get("index", ""))))
    add(("Format", stream.get("codec_long_name") or stream.get("codec_name", "")))
    if stream.get("profile"):
        add(("Format profile", stream["profile"]))
    codec_tag = (stream.get("codec_tag_string") or "").strip()
    if codec_tag and codec_tag != stream.get("codec_name"):
        add(("Codec ID", codec_tag))
    if stream.get("duration"):
        add(("Duration", fmt_duration(stream["duration"])))
    if stream.get("bit_rate"):
        add(("Bit rate", fmt_bitrate(stream["bit_rate"])))
    width = stream.get("width")
    height = stream.get("height")
    if width and height:
        add(("Width", fmt_dimension(width)))
        add(("Height", fmt_dimension(height)))
        dar = stream.get("display_aspect_ratio")
        if dar:
            add(("Display aspect ratio", dar))
        frame_rate = fmt_frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
        if frame_rate:
            add(("Frame rate", frame_rate))
    if stream.get("pix_fmt"):
        add(("Pixel format", stream["pix_fmt"]))
        bits = {"yuv420p": 8, "yuvj420p": 8, "yuv422p": 8, "yuv444p": 8,
                "yuv420p10le": 10, "yuv422p10le": 10, "yuv444p10le": 10,
                "yuv420p12le": 12, "gray16le": 16}.get(stream["pix_fmt"])
        if bits:
            add(("Bit depth", f"{bits} bits"))
    if stream.get("color_range"):
        add(("Color range", stream["color_range"]))
    if stream.get("color_space"):
        add(("Color space", stream["color_space"]))
    if stream.get("color_transfer"):
        add(("Color transfer", stream["color_transfer"]))
    if stream.get("color_primaries"):
        add(("Color primaries", stream["color_primaries"]))
    if stream.get("nb_frames"):
        add(("Frame count", stream["nb_frames"]))
    lang = _stream_language(stream)
    if lang:
        add(("Language", lang))
    return lines


def _audio_lines(stream):
    lines = []
    add = lines.append
    add(("ID", str(stream.get("index", ""))))
    add(("Format", stream.get("codec_long_name") or stream.get("codec_name", "")))
    if stream.get("profile"):
        add(("Format profile", stream["profile"]))
    if stream.get("duration"):
        add(("Duration", fmt_duration(stream["duration"])))
    if stream.get("bit_rate"):
        add(("Bit rate", fmt_bitrate(stream["bit_rate"])))
    if stream.get("sample_rate"):
        try:
            add(("Sampling rate", f"{int(stream['sample_rate']):,} Hz".replace(",", " ")))
        except (TypeError, ValueError):
            pass
    if stream.get("channels"):
        layout = stream.get("channel_layout") or ""
        add(("Channel(s)", f"{stream['channels']} channel{'s' if stream['channels'] > 1 else ''}"
             + (f" ({layout})" if layout else "")))
    lang = _stream_language(stream)
    if lang:
        add(("Language", lang))
    return lines


def _subtitle_lines(stream):
    lines = []
    add = lines.append
    add(("ID", str(stream.get("index", ""))))
    add(("Format", stream.get("codec_long_name") or stream.get("codec_name", "")))
    lang = _stream_language(stream)
    if lang:
        add(("Language", lang))
    return lines


def _general_lines(path, info):
    fmt = info.get("format") or {}
    lines = []
    add = lines.append
    add(("Complete name", os.path.abspath(path)))
    add(("Format", fmt.get("format_long_name") or fmt.get("format_name", "")))
    if fmt.get("size"):
        add(("File size", fmt_size(fmt["size"])))
    if fmt.get("duration"):
        add(("Duration", fmt_duration(fmt["duration"])))
    if fmt.get("bit_rate"):
        add(("Overall bit rate", fmt_bitrate(fmt["bit_rate"])))
    tags = fmt.get("tags") or {}
    if tags.get("encoder"):
        add(("Writing application", tags["encoder"]))
    if tags.get("creation_time"):
        add(("Encoded date", str(tags["creation_time"])[:19].replace("T", " ") + " UTC"))
    video_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    text_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "subtitle"]
    if video_streams:
        add(("Video format count", str(len(video_streams))))
    if audio_streams:
        add(("Audio format count", str(len(audio_streams))))
    if text_streams:
        add(("Text format count", str(len(text_streams))))
    return lines


def to_mediainfo_text(path, info):
    """ffprobe JSON → MediaInfo 风格纯文本（便于发帖求助时粘贴）。"""
    blocks = []
    general = _general_lines(path, info)
    if general:
        blocks.append(("General", general))
    index = {"video": 0, "audio": 0, "subtitle": 0}
    titles = {"video": "Video", "audio": "Audio", "subtitle": "Text"}
    builders = {"video": _video_lines, "audio": _audio_lines, "subtitle": _subtitle_lines}
    for stream in info.get("streams", []):
        kind = stream.get("codec_type")
        if kind not in builders:
            continue
        index[kind] += 1
        title = titles[kind] + (f" #{index[kind]}" if index[kind] > 1 else "")
        lines = builders[kind](stream)
        if lines:
            blocks.append((title, lines))
    chapters = info.get("chapters") or []
    if chapters:
        lines = []
        for i, chapter in enumerate(chapters, 1):
            tags = chapter.get("tags") or {}
            title = tags.get("title") or f"Chapter {i}"
            try:
                start = float(chapter.get("start_time", 0))
                lines.append((f"Chapter {i:02d}", f"{fmt_duration(start)} - {title}"))
            except (TypeError, ValueError):
                lines.append((f"Chapter {i:02d}", title))
        blocks.append(("Chapters", lines))

    width = max(
        [len(key) for _, lines in blocks for key, _ in lines] + [8]
    )
    out = []
    for title, lines in blocks:
        out.append(title)
        for key, value in lines:
            if not value:
                continue
            out.append(f"{key.ljust(width)} : {value}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
