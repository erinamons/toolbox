# -*- coding: utf-8 -*-
"""工具：PDF 转 JPG（PySide6 版，挂载到工具箱）。"""
import glob
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QEvent, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
)

from tools.base import ToolWidget


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
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf"])
    import pymupdf
    return pymupdf


class ConvertWorker(QThread):
    """后台转换线程，避免阻塞界面。"""

    log = Signal(str, object)      # (文本, [输出文件路径列表])
    progress = Signal(int, int)    # (当前, 总数)
    done = Signal(int, int)        # (成功文件数, 生成 JPG 总数)

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
                self.log.emit(f"[OK] {os.path.basename(f)} -> {len(paths)} 张", paths)
            except Exception as e:
                self.log.emit(f"[FAIL] {os.path.basename(f)}: {e}", [])
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


class PDF2JPGTool(ToolWidget):
    name = "PDF 转 JPG"
    description = "把 PDF 每页转换为 JPG 图片"
    icon = "📄"
    icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "pdf.png")

    def __init__(self, on_back=None, parent=None):
        self._worker = None
        super().__init__(on_back, parent)

    def build_ui(self, layout):
        # ── 文件操作按钮 ──────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加 PDF 文件")
        self.btn_add_dir = QPushButton("添加文件夹")
        self.btn_clear = QPushButton("清空列表")
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_dir)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

        # ── 文件列表（可拖拽） ────────────────────────
        self.list_files = QListWidget()
        self.list_files.setMinimumHeight(120)
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_files.customContextMenuRequested.connect(self._menu_files)
        layout.addWidget(self.list_files)

        # ── 输出目录 ─────────────────────────────────
        out_row = QHBoxLayout()
        lbl = QLabel("输出目录:")
        lbl.setAlignment(Qt.AlignVCenter)
        out_row.addWidget(lbl)
        self.edit_outdir = QLineEdit()
        self.edit_outdir.setPlaceholderText("留空 = PDF 同目录下的 jpg_output")
        self.btn_browse = QPushButton("浏览")
        out_row.addWidget(self.edit_outdir, 1)
        out_row.addWidget(self.btn_browse)
        layout.addLayout(out_row)

        # ── 分辨率 + 打开输出目录 ─────────────────────
        zoom_row = QHBoxLayout()
        lbl_zoom = QLabel("分辨率:")
        lbl_zoom.setAlignment(Qt.AlignVCenter)
        zoom_row.addWidget(lbl_zoom)
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
        layout.addLayout(zoom_row)

        # ── 转换按钮 + 进度 ──────────────────────────
        self.btn_convert = QPushButton("开始转换")
        self.btn_convert.setObjectName("primaryBtn")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.btn_convert)
        layout.addWidget(self.progress)

        # ── 日志 + 状态 ──────────────────────────────
        self.list_log = QListWidget()
        self.list_log.setMaximumHeight(90)
        self.list_log.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_log.customContextMenuRequested.connect(self._menu_log)
        layout.addWidget(self.list_log)
        self.lbl_status = QLabel("就绪：将 PDF 拖入窗口，或点击「添加 PDF 文件」")
        layout.addWidget(self.lbl_status)

        # ── 事件绑定 ─────────────────────────────────
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_clear.clicked.connect(self.list_files.clear)
        self.btn_browse.clicked.connect(self._browse_outdir)
        self.btn_open_out.clicked.connect(self._open_outdir)
        self.btn_convert.clicked.connect(self._start_convert)
        self.setAcceptDrops(True)
        self._bind_hints()

    # ── 悬停操作提示（底部状态栏） ──────────────────
    def _bind_hints(self):
        self._hints = {
            self.list_files: "文件列表 — 右键：打开 / 打开文件夹 / 另存为... / 删除当前项",
            self.list_log: "输出列表 — 右键：打开 / 打开文件夹 / 另存为... / 删除当前项",
            self.btn_add_files: "添加 PDF 文件（可多选）",
            self.btn_add_dir: "添加文件夹 — 自动扫描其中的 PDF",
            self.btn_clear: "清空列表",
            self.btn_browse: "选择 JPG 输出目录",
            self.btn_open_out: "在资源管理器中打开输出目录",
            self.btn_convert: "开始转换 — 将 PDF 逐页转为 JPG",
        }
        for w in self._hints:
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj in self._hints:
            if event.type() == QEvent.Enter:
                self._status_backup = self.lbl_status.text()
                self.lbl_status.setText(self._hints[obj])
            elif event.type() == QEvent.Leave:
                self.lbl_status.setText(
                    getattr(self, "_status_backup", self.lbl_status.text())
                )
        return super().eventFilter(obj, event)

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
        zoom = 1.0 if self.radio_1x.isChecked() else 3.0 if self.radio_3x.isChecked() else 2.0
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

    def _on_log(self, msg, paths):
        item = QListWidgetItem(msg)
        item.setData(Qt.UserRole, paths)  # 存储输出文件路径，供右键菜单使用
        self.list_log.addItem(item)
        self.list_log.scrollToBottom()

    def _on_done(self, ok, total_jpg):
        self.progress.setVisible(False)
        self.btn_convert.setEnabled(True)
        self.lbl_status.setText(f"完成：{ok} 个 PDF 转换成功，共生成 {total_jpg} 张 JPG。")
        QMessageBox.information(self, "完成", f"转换完成！\n{ok} 个 PDF，共生成 {total_jpg} 张 JPG。")

    def _update_status(self):
        n = self.list_files.count()
        self.lbl_status.setText(f"已添加 {n} 个 PDF 文件，点击「开始转换」")

    # ── 右键菜单 ────────────────────────────────────
    def _menu_files(self, pos):
        self._popup_menu(self.list_files, pos)

    def _menu_log(self, pos):
        self._popup_menu(self.list_log, pos)

    def _popup_menu(self, lst, pos):
        item = lst.itemAt(pos)
        if not item:
            return
        # 先把右键行设为当前行（点击反馈高亮）
        lst.setCurrentItem(item)
        # 取路径：文件列表用 item.text()，日志列表从 UserRole 读
        if lst is self.list_files:
            paths = [item.text()]
        else:
            data = item.data(Qt.UserRole)
            paths = list(data) if isinstance(data, list) else []

        menu = QMenu(self)
        act_open = menu.addAction("打开")
        act_folder = menu.addAction("打开文件夹")
        act_save = menu.addAction("另存为...")
        menu.addSeparator()
        act_del = menu.addAction("删除当前项")
        # 0 张图片时禁用打开/另存（仅日志列表可能遇到）
        if not paths:
            act_open.setEnabled(False)
            act_save.setEnabled(False)
            act_folder.setEnabled(False)

        act = menu.exec(lst.mapToGlobal(pos))
        if act == act_open and paths:
            os.startfile(paths[0])  # noqa: S606
        elif act == act_folder and paths:
            if len(paths) == 1:
                # 单张：在资源管理器中定位并选中
                subprocess.Popen(["explorer", "/select,", os.path.normpath(paths[0])])
            else:
                # 多张：直接打开整个输出目录
                os.startfile(os.path.dirname(paths[0]))
        elif act == act_save and paths:
            self._save_as(paths[0])
        elif act == act_del:
            row = lst.row(item)
            lst.takeItem(row)
            if lst is self.list_files:
                self._update_status()

    def _save_as(self, src):
        dest, _ = QFileDialog.getSaveFileName(
            self, "另存为", os.path.basename(src),
            "JPG 图片 (*.jpg);;所有文件 (*.*)",
        )
        if not dest:
            return
        try:
            shutil.copy(src, dest)
            self.lbl_status.setText(f"已另存为：{dest}")
        except OSError as e:
            QMessageBox.warning(self, "另存为失败", str(e))

    # ── 拖拽支持 ────────────────────────────────────
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
                paths.extend(sorted(glob.glob(os.path.join(path, "*.pdf"))))
            elif path.lower().endswith(".pdf"):
                paths.append(path)
        if paths:
            self._add_to_list(paths)
            self.lbl_status.setText(f"已拖入 {len(paths)} 个 PDF 文件，点击「开始转换」")
        event.acceptProposedAction()
