#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF → JPG 转换工具（GUI 版）
==============================
基于 PySide6 的现代化界面：
  - 添加 PDF 文件 / 文件夹，多选
  - 输出目录可选（默认 PDF 同目录 jpg_output）
  - 分辨率可选 1x / 2x / 3x
  - 后台线程转换，进度条 + 实时日志
  - 完成后一键打开输出目录
"""
import glob
import os
import subprocess
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


def ensure_pymupdf():
    """确保 pymupdf 可用，缺失时自动 pip 安装。"""
    try:
        import pymupdf  # noqa: F401
        return pymupdf
    except ImportError:
        try:
            import fitz  # 兼容旧版包名
            return fitz
        except ImportError:
            pass
    print("未检测到 PyMuPDF，正在自动安装 ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf"])
    import pymupdf
    return pymupdf


class ConvertWorker(QThread):
    """后台转换线程，避免阻塞界面。"""

    log = Signal(str)          # 单文件结果
    progress = Signal(int, int)  # (当前, 总数)
    done = Signal(int, int)      # (成功文件数, 生成 JPG 总数)

    def __init__(self, files, zoom, out_dir):
        super().__init__()
        self.files = files
        self.zoom = zoom
        self.out_dir = out_dir
        self.pymupdf = ensure_pymupdf()

    def run(self):
        ok = 0
        total_jpg = 0
        for i, f in enumerate(self.files):
            try:
                paths = self._convert_one(f)
                ok += 1
                total_jpg += len(paths)
                self.log.emit(f"[OK] {os.path.basename(f)} -> {len(paths)} 张")
            except Exception as e:
                self.log.emit(f"[FAIL] {os.path.basename(f)}: {e}")
            self.progress.emit(i + 1, len(self.files))
        self.done.emit(ok, total_jpg)

    def _convert_one(self, src):
        src = os.path.abspath(src)
        out_dir = self.out_dir or os.path.join(os.path.dirname(src), "jpg_output")
        os.makedirs(out_dir, exist_ok=True)

        doc = self.pymupdf.open(src)
        base = os.path.splitext(os.path.basename(src))[0]
        paths = []
        try:
            for i, page in enumerate(doc):
                pix = page.get_pixmap(
                    matrix=self.pymupdf.Matrix(self.zoom, self.zoom), alpha=False
                )
                name = f"{base}.jpg" if doc.page_count == 1 else f"{base}_p{i + 1}.jpg"
                path = os.path.join(out_dir, name)
                pix.save(path)
                paths.append(path)
        finally:
            doc.close()
        return paths


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 转 JPG 工具")
        self.resize(640, 520)
        self.setAcceptDrops(True)  # 支持拖拽添加文件
        self._build_ui()
        self._worker = None

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── 文件操作按钮 ──────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加 PDF 文件")
        self.btn_add_dir = QPushButton("添加文件夹")
        self.btn_clear = QPushButton("清空列表")
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_dir)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_clear)
        root.addLayout(btn_row)

        # ── 文件列表 ─────────────────────────────────
        self.list_files = QListWidget()
        self.list_files.setMinimumHeight(180)
        root.addWidget(self.list_files)

        # ── 输出目录 ─────────────────────────────────
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录:"))
        self.edit_outdir = QLineEdit()
        self.edit_outdir.setPlaceholderText("留空 = PDF 同目录下的 jpg_output")
        self.btn_browse = QPushButton("浏览")
        out_row.addWidget(self.edit_outdir, 1)
        out_row.addWidget(self.btn_browse)
        root.addLayout(out_row)

        # ── 分辨率 ───────────────────────────────────
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("分辨率:"))
        self.zoom_group = QButtonGroup(self)
        self.radio_1x = QRadioButton("1x 快速")
        self.radio_2x = QRadioButton("2x 清晰")
        self.radio_3x = QRadioButton("3x 高清")
        for rb in (self.radio_1x, self.radio_2x, self.radio_3x):
            self.zoom_group.addButton(rb)
            zoom_row.addWidget(rb)
        self.radio_2x.setChecked(True)
        zoom_row.addStretch(1)
        self.btn_open_out = QPushButton("打开输出目录")
        zoom_row.addWidget(self.btn_open_out)
        root.addLayout(zoom_row)

        # ── 转换按钮 + 进度 ──────────────────────────
        self.btn_convert = QPushButton("开始转换")
        self.btn_convert.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold;"
            " padding: 8px; background: #2563eb; color: white;"
            " border: none; border-radius: 6px; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #94a3b8; }"
        )
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.btn_convert)
        root.addWidget(self.progress)

        # ── 日志 + 状态栏 ────────────────────────────
        self.list_log = QListWidget()
        self.list_log.setMaximumHeight(110)
        root.addWidget(self.list_log)
        self.lbl_status = QLabel("就绪：将 PDF 拖入窗口，或点击「添加 PDF 文件」")
        root.addWidget(self.lbl_status)

        # ── 事件绑定 ─────────────────────────────────
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_clear.clicked.connect(self.list_files.clear)
        self.btn_browse.clicked.connect(self._browse_outdir)
        self.btn_open_out.clicked.connect(self._open_outdir)
        self.btn_convert.clicked.connect(self._start_convert)

    # ── 槽函数 ──────────────────────────────────────
    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 PDF 文件（可多选）", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        self._add_to_list(files)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择包含 PDF 的文件夹")
        if d:
            self._add_to_list(sorted(glob.glob(os.path.join(d, "*.pdf"))))

    def _add_to_list(self, files):
        existing = {self.list_files.item(i).text() for i in range(self.list_files.count())}
        for f in files:
            if f not in existing:
                self.list_files.addItem(f)
        self._update_status()

    # ── 拖拽支持 ────────────────────────────────────
    def dragEnterEvent(self, event):
        """拖入时：仅接受本地文件/文件夹。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """松开时：提取 PDF 文件（文件夹自动扫描其中的 PDF）。"""
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path):
                paths.extend(sorted(glob.glob(os.path.join(path, "*.pdf"))))
            elif path.lower().endswith(".pdf"):
                paths.append(path)
        if paths:
            self._add_to_list(paths)
            self.lbl_status.setText(f"已拖入 {len(paths)} 个 PDF 文件，点击「开始转换」")
        event.acceptProposedAction()

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.edit_outdir.setText(d)

    def _open_outdir(self):
        d = self.edit_outdir.text().strip() or ""
        if not d and self.list_files.count() > 0:
            d = os.path.join(os.path.dirname(self.list_files.item(0).text()), "jpg_output")
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa: S606 - Windows 打开资源管理器

    def _start_convert(self):
        if self._worker and self._worker.isRunning():
            return
        files = [self.list_files.item(i).text() for i in range(self.list_files.count())]
        if not files:
            QMessageBox.information(self, "提示", "请先添加 PDF 文件。")
            return
        if self.radio_1x.isChecked():
            zoom = 1.0
        elif self.radio_3x.isChecked():
            zoom = 3.0
        else:
            zoom = 2.0
        out_dir = self.edit_outdir.text().strip() or None

        self.list_log.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.btn_convert.setEnabled(False)
        self.lbl_status.setText(f"正在转换 ... 共 {len(files)} 个文件")

        self._worker = ConvertWorker(files, zoom, out_dir)
        self._worker.log.connect(self._on_log)
        self._worker.progress.connect(lambda cur, tot: self.progress.setValue(cur))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_log(self, msg):
        self.list_log.addItem(msg)
        self.list_log.scrollToBottom()

    def _on_done(self, ok, total_jpg):
        self.progress.setVisible(False)
        self.btn_convert.setEnabled(True)
        self.lbl_status.setText(f"完成：{ok} 个 PDF 转换成功，共生成 {total_jpg} 张 JPG。")
        QMessageBox.information(self, "完成", f"转换完成！\n{ok} 个 PDF，共生成 {total_jpg} 张 JPG。")

    def _update_status(self):
        n = self.list_files.count()
        self.lbl_status.setText(f"已添加 {n} 个 PDF 文件，点击「开始转换」")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
