# -*- coding: utf-8 -*-
"""工具：视频压缩（小丸式本地压制：H.264/H.265 + CRF，批量队列，进度实时）。"""
import glob
import os
import re
import subprocess

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from tools.base import ToolWidget
from tools import ffprobe_utils

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"]
SCALE_OPTIONS = [("保持原始", None), ("限制 1080p", 1080), ("限制 720p", 720), ("限制 480p", 480)]

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


class CompressWorker(QThread):
    """后台批量压缩线程：逐个文件调用 ffmpeg，实时回报进度。"""

    progress_file = Signal(int, int, str)     # (文件序号从1, 总数, 文件名)
    progress_tick = Signal(int)               # 当前文件 0-100
    log = Signal(str, str)                    # (消息, 输出文件路径)
    done = Signal(int, int, int)              # (成功数, 失败数, 跳过数)
    current_process = Signal(object)          # 把 ffmpeg 进程句柄交给 UI 以便取消

    def __init__(self, jobs, codec, crf, preset, max_height, out_dir):
        super().__init__()
        self.jobs = jobs                       # [(src, dst)]
        self.codec = codec                     # libx264 / libx265
        self.crf = crf
        self.preset = preset
        self.max_height = max_height           # None / 1080 / 720 / 480
        self.out_dir = out_dir
        self._cancelled = False
        self._proc = None

    def cancel(self):
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def _duration_of(self, src):
        try:
            info = ffprobe_utils.probe(src)
            return float((info.get("format") or {}).get("duration") or 0)
        except (RuntimeError, TypeError, ValueError):
            return 0.0

    def run(self):
        ok = fail = skipped = 0
        total = len(self.jobs)
        for i, (src, dst) in enumerate(self.jobs, 1):
            if self._cancelled:
                skipped += total - i + 1
                break
            self.progress_file.emit(i, total, os.path.basename(src))
            if os.path.isfile(dst) and os.path.getsize(dst) > 0:
                skipped += 1
                self.log.emit(f"[跳过] {os.path.basename(src)}（输出已存在）", dst)
                continue
            duration = self._duration_of(src)
            out_dir = os.path.dirname(dst)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            cmd = [
                ffprobe_utils.find_ffmpeg(), "-y", "-hide_banner", "-nostats",
                "-i", src,
                "-map", "0:v:0", "-map", "0:a?",
                "-c:v", self.codec, "-preset", self.preset, "-crf", str(self.crf),
            ]
            if self.max_height:
                cmd += ["-vf", f"scale=-2:'min({self.max_height},ih)'"]
            cmd += ["-c:a", "aac", "-b:a", "128k", "-c:s", "mov_text", "-movflags", "+faststart"]
            if dst.lower().endswith(".mp4"):
                cmd += ["-f", "mp4"]
            cmd += ["-progress", "pipe:1", dst]

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=creationflags,
                )
                # stderr 必须持续排空：ffmpeg 的警告写满 64KB 管道缓冲会把自己阻塞
                stderr_chunks = []
                proc = self._proc

                def _drain_stderr():
                    try:
                        while True:
                            chunk = proc.stderr.read(4096)
                            if not chunk:
                                break
                            stderr_chunks.append(chunk)
                    except (OSError, ValueError):
                        pass

                import threading
                drainer = threading.Thread(target=_drain_stderr, daemon=True)
                drainer.start()
                for line in self._proc.stdout:
                    if self._cancelled:
                        break
                    if duration > 0:
                        m = _TIME_RE.search(line)
                        if m:
                            h, mnt, sec = m.groups()
                            pos = int(h) * 3600 + int(mnt) * 60 + float(sec)
                            self.progress_tick.emit(max(0, min(99, int(pos * 100 / duration))))
                code = self._proc.wait()
                drainer.join(timeout=2)
                self._proc = None
                if self._cancelled:
                    self._remove_partial(dst)
                    skipped += 1
                    break
                if code != 0:
                    self._remove_partial(dst)
                    stderr_tail = "".join(stderr_chunks).strip()[-300:]
                    raise RuntimeError(f"ffmpeg 退出码 {code}" + (f"：{stderr_tail}" if stderr_tail else ""))
                ok += 1
                self.log.emit(self._result_line(src, dst), dst)
            except RuntimeError as e:
                fail += 1
                self.log.emit(f"[FAIL] {os.path.basename(src)}: {e}", "")
            except OSError as e:
                fail += 1
                self.log.emit(f"[FAIL] {os.path.basename(src)}: {e}", "")
        self.done.emit(ok, fail, skipped)

    def _remove_partial(self, dst):
        try:
            if os.path.isfile(dst):
                os.remove(dst)
        except OSError:
            pass

    def _result_line(self, src, dst):
        try:
            before = os.path.getsize(src)
            after = os.path.getsize(dst)
            if before > 0:
                pct = (1 - after / before) * 100
                arrow = "压缩" if pct >= 0 else "增大"
                return (f"[OK] {os.path.basename(src)}: {ffprobe_utils.fmt_size(before)}"
                        f" → {ffprobe_utils.fmt_size(after)}（{arrow} {abs(pct):.0f}%）")
        except OSError:
            pass
        return f"[OK] {os.path.basename(src)} → {os.path.basename(dst)}"


class CompressTool(ToolWidget):
    name = "视频压缩"
    description = "小丸式本地压制：H.264/H.265 + 质量滑条，批量队列"
    icon = "🗜"

    def __init__(self, on_back=None, parent=None):
        self._worker = None
        super().__init__(on_back, parent)

    def build_ui(self, layout):
        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加视频")
        self.btn_add_dir = QPushButton("添加文件夹")
        self.btn_clear = QPushButton("清空列表")
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_dir)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

        self.list_files = QListWidget()
        self.list_files.setMinimumHeight(100)
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_files.customContextMenuRequested.connect(self._menu_files)
        layout.addWidget(self.list_files)

        # ── 编码器 ──
        enc_row = QHBoxLayout()
        lbl_enc = QLabel("编码器:")
        lbl_enc.setAlignment(Qt.AlignVCenter)
        enc_row.addWidget(lbl_enc)
        self.radio_h264 = QRadioButton("H.264 兼容")
        self.radio_h265 = QRadioButton("H.265 更小")
        self.radio_h264.setChecked(True)
        enc_row.addWidget(self.radio_h264)
        enc_row.addWidget(self.radio_h265)
        enc_row.addStretch(1)
        lbl_preset = QLabel("速度:")
        lbl_preset.setAlignment(Qt.AlignVCenter)
        enc_row.addWidget(lbl_preset)
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(PRESETS)
        self.combo_preset.setCurrentIndex(PRESETS.index("veryfast"))
        enc_row.addWidget(self.combo_preset)
        layout.addLayout(enc_row)

        # ── 质量滑条 ──
        crf_row = QHBoxLayout()
        lbl_crf = QLabel("质量:")
        lbl_crf.setAlignment(Qt.AlignVCenter)
        crf_row.addWidget(lbl_crf)
        self.slider_crf = QSlider(Qt.Horizontal)
        self.slider_crf.setRange(18, 32)
        self.slider_crf.setValue(23)
        self.slider_crf.setTickPosition(QSlider.TicksBelow)
        self.slider_crf.setTickInterval(2)
        crf_row.addWidget(self.slider_crf, 1)
        self.lbl_crf_value = QLabel("CRF 23（均衡）")
        self.lbl_crf_value.setMinimumWidth(130)
        crf_row.addWidget(self.lbl_crf_value)
        layout.addLayout(crf_row)

        # ── 分辨率 + 输出目录 ──
        scale_row = QHBoxLayout()
        lbl_scale = QLabel("分辨率:")
        lbl_scale.setAlignment(Qt.AlignVCenter)
        scale_row.addWidget(lbl_scale)
        self.combo_scale = QComboBox()
        for label, _ in SCALE_OPTIONS:
            self.combo_scale.addItem(label)
        scale_row.addWidget(self.combo_scale)
        scale_row.addStretch(1)
        lbl_out = QLabel("输出目录:")
        lbl_out.setAlignment(Qt.AlignVCenter)
        scale_row.addWidget(lbl_out)
        self.lbl_outdir = QLabel("留空 = 视频同目录 compressed_output")
        self.lbl_outdir.setStyleSheet("color:#666;")
        scale_row.addWidget(self.lbl_outdir, 1)
        self.btn_browse = QPushButton("浏览")
        scale_row.addWidget(self.btn_browse)
        layout.addLayout(scale_row)

        # ── 开始 + 进度 ──
        self.btn_convert = QPushButton("开始压缩")
        self.btn_convert.setObjectName("primaryBtn")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)
        convert_row = QHBoxLayout()
        convert_row.addWidget(self.btn_convert)
        convert_row.addWidget(self.btn_cancel)
        convert_row.addStretch(1)
        layout.addLayout(convert_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.list_log = QListWidget()
        self.list_log.setMinimumHeight(80)
        layout.addWidget(self.list_log, 1)
        self.lbl_status = QLabel("就绪：将视频拖入窗口，或点击「添加视频」")
        layout.addWidget(self.lbl_status)

        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_clear.clicked.connect(self._clear_all)
        self.btn_browse.clicked.connect(self._browse_outdir)
        self.btn_convert.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)
        self.slider_crf.valueChanged.connect(self._on_crf_change)
        self._out_dir = ""
        self.setAcceptDrops(True)
        self._check_ffmpeg()

    # ── ffmpeg 可用性 ─────────────────────────────
    def _check_ffmpeg(self):
        if ffprobe_utils.find_ffmpeg() is None:
            self.lbl_status.setText(
                "⚠ 未找到 ffmpeg.exe：请把 ffmpeg.exe 放入程序目录的 bin 文件夹（ffmpeg 官方 build 内含）"
            )

    def _on_crf_change(self, value):
        hint = "高画质" if value <= 20 else "均衡" if value <= 25 else "高压缩"
        self.lbl_crf_value.setText(f"CRF {value}（{hint}）")

    # ── 添加文件 ──────────────────────────────────
    def _video_exts(self):
        return {e for e in ffprobe_utils.MEDIA_EXTENSIONS
                if e in (".mp4", ".mkv", ".mov", ".avi", ".flv", ".ts", ".m2ts", ".webm", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp")}

    def _add_files(self):
        patterns = " ".join(f"*{ext}" for ext in sorted(self._video_exts()))
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择视频文件（可多选）", "", f"视频文件 ({patterns});;所有文件 (*.*)")
        self._add_to_list(files)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择包含视频的文件夹")
        if not d:
            return
        files = []
        for ext in self._video_exts():
            files.extend(glob.glob(os.path.join(d, "*" + ext)))
        self._add_to_list(sorted(set(files)))

    def _add_to_list(self, files):
        existing = {self.list_files.item(i).text() for i in range(self.list_files.count())}
        for f in files:
            if f and f not in existing and os.path.isfile(f):
                self.list_files.addItem(f)
        n = self.list_files.count()
        self.lbl_status.setText(f"已添加 {n} 个视频，点击「开始压缩」")

    def _clear_all(self):
        self._stop_worker()
        self.list_files.clear()
        self.list_log.clear()
        self.progress.setVisible(False)
        self.lbl_status.setText("就绪：将视频拖入窗口，或点击「添加视频」")

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._out_dir = d
            self.lbl_outdir.setText(d)

    # ── 压缩流程 ──────────────────────────────────
    def _build_jobs(self):
        jobs = []
        for i in range(self.list_files.count()):
            src = self.list_files.item(i).text()
            base = os.path.splitext(os.path.basename(src))[0]
            out_dir = self._out_dir or os.path.join(os.path.dirname(src), "compressed_output")
            dst = os.path.join(out_dir, base + ".mp4")
            if os.path.abspath(src) == os.path.abspath(dst):
                dst = os.path.join(out_dir, base + "_compressed.mp4")
            jobs.append((src, dst))
        return jobs

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        files = self.list_files.count()
        if files == 0:
            QMessageBox.information(self, "提示", "请先添加视频文件。")
            return
        if ffprobe_utils.find_ffmpeg() is None:
            QMessageBox.warning(self, "缺少 ffmpeg",
                                "未找到 ffmpeg.exe。\n请把它放入程序目录的 bin 文件夹后重试。")
            return
        codec = "libx265" if self.radio_h265.isChecked() else "libx264"
        crf = self.slider_crf.value()
        preset = self.combo_preset.currentText()
        max_height = SCALE_OPTIONS[self.combo_scale.currentIndex()][1]

        self.list_log.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, files * 100)
        self.progress.setValue(0)
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.lbl_status.setText(f"正在压缩 … 共 {files} 个文件")

        self._worker = CompressWorker(self._build_jobs(), codec, crf, preset, max_height, self._out_dir)
        self._worker.progress_file.connect(self._on_file_start)
        self._worker.progress_tick.connect(self._on_tick)
        self._worker.log.connect(self._on_log)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_file_start(self, index, total, name):
        self.lbl_status.setText(f"（{index}/{total}）正在压缩：{name}")

    def _on_tick(self, percent):
        base = (self.progress.value() // 100) * 100
        self.progress.setValue(base + percent)

    def _on_log(self, msg, _path):
        self.list_log.addItem(msg)
        self.list_log.scrollToBottom()
        self.progress.setValue(min(self.progress.value() + 100, self.progress.maximum()))

    def _on_done(self, ok, fail, skipped):
        self.progress.setVisible(False)
        self.btn_convert.setEnabled(True)
        self.btn_cancel.setVisible(False)
        summary = f"完成：成功 {ok} 个"
        if fail:
            summary += f"，失败 {fail} 个"
        if skipped:
            summary += f"，跳过 {skipped} 个"
        self.lbl_status.setText(summary)
        QMessageBox.information(self, "完成", summary)

    def _cancel(self):
        if self._worker:
            self.lbl_status.setText("正在取消…")
            self._worker.cancel()

    def _stop_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)

    # ── 右键 ──────────────────────────────────────
    def _menu_files(self, pos):
        item = self.list_files.itemAt(pos)
        if not item:
            return
        self.list_files.setCurrentItem(item)
        menu = QMenu(self)
        act_open = menu.addAction("打开文件位置")
        act_remove = menu.addAction("移除此项")
        act = menu.exec(self.list_files.mapToGlobal(pos))
        if act == act_open:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(item.text())])  # noqa: S606
        elif act == act_remove:
            row = self.list_files.row(item)
            self.list_files.takeItem(row)

    # ── 拖拽 ──────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path):
                for ext in self._video_exts():
                    paths.extend(glob.glob(os.path.join(path, "*" + ext)))
            elif os.path.splitext(path)[1].lower() in self._video_exts():
                paths.append(path)
        if paths:
            self._add_to_list(sorted(set(paths)))
        event.acceptProposedAction()
