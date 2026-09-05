# -*- coding: utf-8 -*-
"""工具：MediaInfo 视频信息（拖入媒体文件查看完整技术参数）。"""
import glob
import os

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from tools.base import ToolWidget
from tools import ffprobe_utils

SECTION_ICONS = {
    "General": "📦",
    "Video": "🎞",
    "Audio": "🔊",
    "Text": "💬",
    "Chapters": "🔖",
}


class ProbeWorker(QThread):
    """后台 ffprobe 解析线程，逐个文件回传结果。"""

    one_done = Signal(str, object, str)   # (路径, info dict 或 None, 错误信息)
    all_done = Signal(int, int)           # (成功数, 失败数)

    def __init__(self, files):
        super().__init__()
        self.files = files
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        ok = fail = 0
        for path in self.files:
            if self._cancelled:
                break
            try:
                info = ffprobe_utils.probe(path)
                self.one_done.emit(path, info, "")
                ok += 1
            except RuntimeError as e:
                self.one_done.emit(path, None, str(e))
                fail += 1
        self.all_done.emit(ok, fail)


class MediaInfoTool(ToolWidget):
    name = "MediaInfo"
    description = "拖入视频/音频，查看完整技术参数"
    icon = "🎬"
    icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "mediainfo.png")

    def __init__(self, on_back=None, parent=None):
        self._worker = None
        self._results = {}      # path -> info dict
        self._errors = {}       # path -> 错误信息
        super().__init__(on_back, parent)

    # ── UI ─────────────────────────────────────────
    def build_ui(self, layout):
        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件")
        self.btn_add_dir = QPushButton("添加文件夹")
        self.btn_clear = QPushButton("清空列表")
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_dir)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

        self.list_files = QListWidget()
        self.list_files.setMaximumHeight(110)
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_files.currentItemChanged.connect(self._on_select_file)
        self.list_files.customContextMenuRequested.connect(self._menu_files)
        layout.addWidget(self.list_files)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["参数", "值"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)

        action_row = QHBoxLayout()
        self.btn_copy_one = QPushButton("复制当前信息")
        self.btn_copy_all = QPushButton("复制全部信息")
        self.btn_open_bin = QPushButton("打开 bin 目录")
        self.btn_open_bin.setToolTip("ffprobe.exe 需要放在此目录下")
        action_row.addWidget(self.btn_copy_one)
        action_row.addWidget(self.btn_copy_all)
        action_row.addStretch(1)
        action_row.addWidget(self.btn_open_bin)
        layout.addLayout(action_row)

        self.lbl_status = QLabel("就绪：将视频/音频拖入窗口，或点击「添加文件」")
        layout.addWidget(self.lbl_status)

        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_clear.clicked.connect(self._clear_all)
        self.btn_copy_one.clicked.connect(self._copy_current)
        self.btn_copy_all.clicked.connect(self._copy_all)
        self.btn_open_bin.clicked.connect(self._open_bin_dir)
        self.setAcceptDrops(True)
        self._check_ffprobe()

    # ── ffprobe 可用性 ─────────────────────────────
    def _check_ffprobe(self):
        if ffprobe_utils.find_ffprobe() is None:
            self.lbl_status.setText(
                "⚠ 未找到 ffprobe.exe：请把 ffprobe.exe 放入程序目录的 bin 文件夹（ffmpeg 官方 build 内含）"
            )

    def _open_bin_dir(self):
        import subprocess
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bin_dir = os.path.join(base, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        subprocess.Popen(["explorer", os.path.normpath(bin_dir)])  # noqa: S606

    # ── 添加文件 ───────────────────────────────────
    def _add_files(self):
        patterns = " ".join(f"*{ext}" for ext in sorted(ffprobe_utils.MEDIA_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择媒体文件（可多选）", "",
            f"媒体文件 ({patterns});;所有文件 (*.*)",
        )
        self._add_to_list(files)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择包含媒体文件的文件夹")
        if not d:
            return
        files = []
        for ext in ffprobe_utils.MEDIA_EXTENSIONS:
            files.extend(glob.glob(os.path.join(d, "*" + ext)))
        self._add_to_list(sorted(set(files)))

    def _add_to_list(self, files):
        existing = {self.list_files.item(i).text() for i in range(self.list_files.count())}
        added = 0
        for f in files:
            if f and f not in existing and os.path.isfile(f):
                self.list_files.addItem(f)
                added += 1
        if not added:
            return
        self._update_status()
        self._start_probe()

    def _clear_all(self):
        self._stop_worker()
        self.list_files.clear()
        self.tree.clear()
        self._results.clear()
        self._errors.clear()
        self.lbl_status.setText("就绪：将视频/音频拖入窗口，或点击「添加文件」")

    def _update_status(self):
        n = self.list_files.count()
        resolved = len(self._results)
        self.lbl_status.setText(f"已添加 {n} 个文件，已解析 {resolved} 个。选中文件查看详情。")

    # ── 解析流程 ───────────────────────────────────
    def _pending_files(self):
        return [
            self.list_files.item(i).text()
            for i in range(self.list_files.count())
            if self.list_files.item(i).text() not in self._results
            and self.list_files.item(i).text() not in self._errors
        ]

    def _start_probe(self):
        pending = self._pending_files()
        if not pending or (self._worker and self._worker.isRunning()):
            return
        self._worker = ProbeWorker(pending)
        self._worker.one_done.connect(self._on_one_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _stop_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)

    def _on_one_done(self, path, info, error):
        if info is not None:
            self._results[path] = info
            self._errors.pop(path, None)
        else:
            self._errors[path] = error or "解析失败"
            self._results.pop(path, None)
        # 若当前选中的正是该文件，刷新树
        item = self.list_files.currentItem()
        if item and item.text() == path:
            self._render(path)
        elif not self.list_files.currentItem():
            self.list_files.setCurrentRow(0)
        self._update_status()

    def _on_all_done(self, ok, fail):
        summary = f"解析完成：成功 {ok} 个"
        if fail:
            summary += f"，失败 {fail} 个"
        self.lbl_status.setText(summary)

    def _on_select_file(self, current, _previous):
        if not current:
            self.tree.clear()
            return
        self._render(current.text())

    # ── 渲染 ───────────────────────────────────────
    def _render(self, path):
        self.tree.clear()
        if path in self._errors:
            node = QTreeWidgetItem(self.tree, ["错误", self._errors[path]])
            node.setFirstColumnSpanned(True)
            return
        info = self._results.get(path)
        if info is None:
            QTreeWidgetItem(self.tree, ["解析中…", ""])
            return
        self._fill_tree(path, info)

    def _fill_tree(self, path, info):
        def add_section(title, lines):
            if not lines:
                return
            head = QTreeWidgetItem(self.tree, [f"{SECTION_ICONS.get(title.split(' ')[0], '•')} {title}", ""])
            head.setFirstColumnSpanned(True)
            font = head.font(0)
            font.setBold(True)
            head.setFont(0, font)
            for key, value in lines:
                if value:
                    QTreeWidgetItem(head, [key, str(value)])
            head.setExpanded(True)

        fmt = info.get("format") or {}
        general = []
        general.append(("格式", fmt.get("format_long_name") or fmt.get("format_name", "")))
        if fmt.get("size"):
            general.append(("文件大小", ffprobe_utils.fmt_size(fmt["size"])))
        if fmt.get("duration"):
            general.append(("时长", ffprobe_utils.fmt_duration(fmt["duration"])))
        if fmt.get("bit_rate"):
            general.append(("总码率", ffprobe_utils.fmt_bitrate(fmt["bit_rate"])))
        tags = fmt.get("tags") or {}
        if tags.get("encoder"):
            general.append(("写入程序", tags["encoder"]))
        if tags.get("creation_time"):
            general.append(("创建时间", str(tags["creation_time"])[:19].replace("T", " ")))
        add_section("General", general)

        counters = {"video": 0, "audio": 0, "subtitle": 0}
        titles = {"video": "Video", "audio": "Audio", "subtitle": "Text"}
        for stream in info.get("streams", []):
            kind = stream.get("codec_type")
            if kind not in counters:
                continue
            counters[kind] += 1
            n = counters[kind]
            title = titles[kind] + (f" #{n}" if n > 1 else "")
            lines = []
            lang = (stream.get("tags") or {}).get("language")
            if lang:
                lines.append(("语言", ffprobe_utils.fmt_language(lang)))
            codec = stream.get("codec_long_name") or stream.get("codec_name", "")
            lines.append(("编码", codec))
            if stream.get("profile"):
                lines.append(("Profile", stream["profile"]))
            if kind == "video":
                w, h = stream.get("width"), stream.get("height")
                if w and h:
                    lines.append(("分辨率", f"{w} x {h}"))
                if stream.get("pix_fmt"):
                    lines.append(("像素格式", stream["pix_fmt"]))
                rate = ffprobe_utils.fmt_frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
                if rate:
                    lines.append(("帧率", rate))
                if stream.get("bit_rate"):
                    lines.append(("码率", ffprobe_utils.fmt_bitrate(stream["bit_rate"])))
                if stream.get("color_range") or stream.get("color_space"):
                    lines.append(("色彩", " / ".join(x for x in (
                        stream.get("color_space"), stream.get("color_transfer"),
                        stream.get("color_primaries")) if x)))
                if stream.get("nb_frames"):
                    lines.append(("总帧数", stream["nb_frames"]))
            elif kind == "audio":
                if stream.get("sample_rate"):
                    try:
                        lines.append(("采样率", f"{int(stream['sample_rate']):,} Hz".replace(",", " ")))
                    except (TypeError, ValueError):
                        pass
                if stream.get("channels"):
                    layout = stream.get("channel_layout") or ""
                    lines.append(("声道", f"{stream['channels']}" + (f" ({layout})" if layout else "")))
                if stream.get("bit_rate"):
                    lines.append(("码率", ffprobe_utils.fmt_bitrate(stream["bit_rate"])))
            if stream.get("duration"):
                lines.append(("时长", ffprobe_utils.fmt_duration(stream["duration"])))
            add_section(title, lines)

        chapters = info.get("chapters") or []
        if chapters:
            lines = []
            for i, chapter in enumerate(chapters, 1):
                ctags = chapter.get("tags") or {}
                lines.append((f"章节 {i:02d}", ctags.get("title") or ""))
            add_section("Chapters", lines)

    # ── 复制 ───────────────────────────────────────
    def _copy_current(self):
        item = self.list_files.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选中一个文件。")
            return
        path = item.text()
        info = self._results.get(path)
        if info is None:
            QMessageBox.information(self, "提示", "该文件尚未解析成功。")
            return
        text = ffprobe_utils.to_mediainfo_text(path, info)
        QGuiApplication.clipboard().setText(text)
        self.lbl_status.setText("已复制当前文件信息（MediaInfo 风格文本）。")

    def _copy_all(self):
        if not self._results:
            QMessageBox.information(self, "提示", "暂无已解析的文件。")
            return
        parts = []
        for i in range(self.list_files.count()):
            path = self.list_files.item(i).text()
            info = self._results.get(path)
            if info is not None:
                parts.append(ffprobe_utils.to_mediainfo_text(path, info).rstrip())
        QGuiApplication.clipboard().setText(("\n\n" + "-" * 46 + "\n\n").join(parts))
        self.lbl_status.setText(f"已复制 {len(parts)} 个文件的信息。")

    # ── 右键菜单 ───────────────────────────────────
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
            self._results.pop(item.text(), None)
            self._errors.pop(item.text(), None)
            self._update_status()

    # ── 拖拽 ───────────────────────────────────────
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
                for ext in ffprobe_utils.MEDIA_EXTENSIONS:
                    paths.extend(glob.glob(os.path.join(path, "*" + ext)))
            elif os.path.splitext(path)[1].lower() in ffprobe_utils.MEDIA_EXTENSIONS:
                paths.append(path)
        if paths:
            self._add_to_list(sorted(set(paths)))
            self.lbl_status.setText(f"已拖入 {len(paths)} 个媒体文件，正在解析…")
        event.acceptProposedAction()
