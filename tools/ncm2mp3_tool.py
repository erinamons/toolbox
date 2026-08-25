# -*- coding: utf-8 -*-
"""工具：NCM 转 MP3/FLAC（网易云音乐加密格式解密，挂载到工具箱）。

仅限转换自己账号下载/已购的歌曲做个人备份。

NCM 结构（参照 taurusxin/ncmdump 公开实现）：
    magic   8B  "CTENFDAM"
    gap     2B
    key_len 4B LE + key_data   XOR 0x64 → AES-ECB(core_key) → 去填充 → 去 17B "neteasecloudmusic"
    meta_len 4B LE + meta_data XOR 0x63 → 去 22B 头 → base64 → AES-ECB(meta_key) → 去填充 → 去 6B "music:" → JSON
    crc     4B + img_ver 1B
    frame_len 4B LE + img_len 4B LE + 封面图 img_len 字节 + 补齐 (frame_len - img_len) 字节
    audio   剩余全部，key_box 流解密（密钥流周期 256）
格式识别：解密后前 3 字节 "ID3" → mp3；"fLaC" → flac。
"""
import base64
import glob
import json
import os
import shutil
import struct
import subprocess
from binascii import a2b_hex

from PySide6.QtCore import QEvent, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
)

from tools.base import ToolWidget

# ── NCM 固定密钥（公开常量） ──────────────────────────
CORE_KEY = a2b_hex("687A4852416D736F356B496E62617857")
META_KEY = a2b_hex("2331346C6A6B5F215C5D2630553C2728")
MAGIC = b"CTENFDAM"


def _ecb_unpad(data: bytes) -> bytes:
    """宽松 PKCS7 去填充（与 C++ 参考实现一致：末字节 >16 视为无填充）。"""
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16:
        return data[:-pad]
    return data


def build_key_box(key: bytes) -> list:
    """NCM 的 RC4 变体 KSA（与标准 RC4 的区别：j 的累积方式）。"""
    box = list(range(256))
    last_byte = 0
    key_offset = 0
    klen = len(key)
    for i in range(256):
        swap = box[i]
        c = (swap + last_byte + key[key_offset]) & 0xFF
        key_offset += 1
        if key_offset >= klen:
            key_offset = 0
        box[i] = box[c]
        box[c] = swap
        last_byte = c
    return box


def _xor_stream(data: bytes, ks: bytes) -> bytes:
    """用 256 字节周期的密钥流异或（大整数异或，速度足够快）。"""
    if not data:
        return data
    reps = len(data) // 256 + 1
    stream = (ks * reps)[: len(data)]
    n = len(data)
    return (
        int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")
    ).to_bytes(n, "little")


def ncm_dump(data: bytes):
    """解密 NCM 字节流 → (audio_bytes, meta_dict, cover_bytes)。"""
    from Crypto.Cipher import AES  # pycryptodome

    if data[:8] != MAGIC:
        raise ValueError("不是 NCM 文件（魔数不匹配）")
    pos = 10  # magic 8 + gap 2

    # 密钥区
    (key_len,) = struct.unpack_from("<I", data, pos)
    pos += 4
    if key_len <= 0:
        raise ValueError("损坏的 NCM 文件（密钥区长度为 0）")
    key_data = bytearray(data[pos : pos + key_len])
    pos += key_len
    for i in range(key_len):
        key_data[i] ^= 0x64
    key_data = _ecb_unpad(AES.new(CORE_KEY, AES.MODE_ECB).decrypt(bytes(key_data)))
    key = key_data[17:]  # 去 "neteasecloudmusic"
    if not key:
        raise ValueError("密钥解析失败")

    # 元数据区（可能缺失）
    meta = {}
    (meta_len,) = struct.unpack_from("<I", data, pos)
    pos += 4
    if meta_len > 0:
        m = bytearray(data[pos : pos + meta_len])
        pos += meta_len
        for i in range(meta_len):
            m[i] ^= 0x63
        try:
            m = base64.b64decode(bytes(m[22:]), validate=False)
            m = _ecb_unpad(AES.new(META_KEY, AES.MODE_ECB).decrypt(m))[6:]  # 去 "music:"
            meta = json.loads(m.decode("utf-8", errors="replace"))
        except (ValueError, json.JSONDecodeError):
            meta = {}

    # crc 4B + 图片版本 1B
    pos += 5
    (frame_len,) = struct.unpack_from("<I", data, pos)
    pos += 4
    (img_len,) = struct.unpack_from("<I", data, pos)
    pos += 4
    cover = b""
    if 0 < img_len <= frame_len:
        cover = data[pos : pos + img_len]
    pos += frame_len  # 图 + 补齐

    # 音频区：流解密
    box = build_key_box(key)
    ks = bytes(
        box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF] for j in range(1, 256)
    ) + bytes([box[(box[0] + box[(box[0] + 0) & 0xFF]) & 0xFF]])
    audio = _xor_stream(data[pos:], ks)
    return audio, meta, cover


def _detect_format(audio: bytes, meta: dict) -> str:
    if audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if audio[:4] == b"fLaC":
        return "flac"
    fmt = str(meta.get("format", "")).lower()
    return fmt if fmt in ("mp3", "flac") else "mp3"


def _artists_str(meta: dict) -> str:
    arts = []
    for a in meta.get("artist", []):
        if isinstance(a, list) and a:
            arts.append(str(a[0]))
        elif isinstance(a, str):
            arts.append(a)
    return "/".join(arts)


def _safe_name(s: str) -> str:
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    return s.strip()


def _unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    for i in range(1, 1000):
        p = f"{stem} ({i}){ext}"
        if not os.path.exists(p):
            return p
    return path


class NcmWorker(QThread):
    """后台批量解密线程。"""

    log = Signal(str, object)      # (文本, [输出文件路径])
    progress = Signal(int, int)
    done = Signal(int, int)        # (成功数, 总数)

    def __init__(self, files, out_dir, use_meta_name, export_cover):
        super().__init__()
        self.files = files
        self.out_dir = out_dir
        self.use_meta_name = use_meta_name
        self.export_cover = export_cover

    def run(self):
        ok = 0
        for i, f in enumerate(self.files):
            try:
                paths, fmt = self._convert_one(f)
                ok += 1
                extra = " +封面" if len(paths) > 1 else ""
                self.log.emit(
                    f"[OK] {os.path.basename(f)} -> {os.path.basename(paths[0])} ({fmt}){extra}",
                    paths,
                )
            except Exception as e:
                self.log.emit(f"[FAIL] {os.path.basename(f)}: {e}", [])
            self.progress.emit(i + 1, len(self.files))
        self.done.emit(ok, len(self.files))

    def _convert_one(self, src):
        with open(src, "rb") as f:
            data = f.read()
        audio, meta, cover = ncm_dump(data)
        fmt = _detect_format(audio, meta)

        out_dir = self.out_dir or os.path.join(
            os.path.dirname(os.path.abspath(src)), "ncm_output"
        )
        os.makedirs(out_dir, exist_ok=True)

        name = ""
        if self.use_meta_name and meta.get("musicName"):
            artist = _artists_str(meta)
            name = f"{artist} - {meta['musicName']}" if artist else str(meta["musicName"])
            name = _safe_name(name)
        if not name:
            name = os.path.splitext(os.path.basename(src))[0]

        paths = [_unique_path(os.path.join(out_dir, f"{name}.{fmt}"))]
        with open(paths[0], "wb") as f:
            f.write(audio)
        if self.export_cover and cover:
            cover_path = _unique_path(os.path.join(out_dir, f"{name}.jpg"))
            with open(cover_path, "wb") as f:
                f.write(cover)
            paths.append(cover_path)
        return paths, fmt


class NCM2MP3Tool(ToolWidget):
    name = "NCM 转 MP3"
    description = "把网易云 NCM 解密为 MP3/FLAC"
    icon = "🎵"
    icon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ncm.png"
    )

    def __init__(self, on_back=None, parent=None):
        self._worker = None
        super().__init__(on_back, parent)

    def build_ui(self, layout):
        # ── 文件操作按钮 ──────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加 NCM 文件")
        self.btn_add_dir = QPushButton("添加文件夹")
        self.btn_clear = QPushButton("清空列表")
        btn_row.addWidget(self.btn_add_files)
        btn_row.addWidget(self.btn_add_dir)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_clear)
        layout.addLayout(btn_row)

        # ── 文件列表（可拖拽） ────────────────────────
        self.list_files = QListWidget()
        self.list_files.setMinimumHeight(110)
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_files.customContextMenuRequested.connect(self._menu_files)
        layout.addWidget(self.list_files)

        # ── 输出目录 ─────────────────────────────────
        out_row = QHBoxLayout()
        lbl = QLabel("输出目录:")
        lbl.setAlignment(Qt.AlignVCenter)
        out_row.addWidget(lbl)
        self.edit_outdir = QLineEdit()
        self.edit_outdir.setPlaceholderText("留空 = NCM 同目录下的 ncm_output")
        self.btn_browse = QPushButton("浏览")
        out_row.addWidget(self.edit_outdir, 1)
        out_row.addWidget(self.btn_browse)
        layout.addLayout(out_row)

        # ── 选项 + 打开输出目录 ───────────────────────
        opt_row = QHBoxLayout()
        self.chk_meta_name = QCheckBox("按元数据命名（歌手 - 歌名）")
        self.chk_meta_name.setChecked(True)
        self.chk_cover = QCheckBox("导出专辑封面")
        opt_row.addWidget(self.chk_meta_name)
        opt_row.addWidget(self.chk_cover)
        opt_row.addStretch(1)
        self.btn_open_out = QPushButton("打开输出目录")
        opt_row.addWidget(self.btn_open_out)
        layout.addLayout(opt_row)

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
        self.lbl_status = QLabel("就绪：将 NCM 拖入窗口，或点击「添加 NCM 文件」（仅限个人备份）")
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
            self.btn_add_files: "添加 NCM 文件（可多选）",
            self.btn_add_dir: "添加文件夹 — 自动扫描其中的 NCM",
            self.btn_clear: "清空列表",
            self.btn_browse: "选择输出目录",
            self.btn_open_out: "在资源管理器中打开输出目录",
            self.btn_convert: "开始转换 — 解密 NCM 为 MP3/FLAC",
            self.chk_meta_name: "用歌曲元数据命名输出文件（歌手 - 歌名）",
            self.chk_cover: "同时导出专辑封面为 JPG",
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
            self, "选择 NCM 文件（可多选）", "", "NCM 文件 (*.ncm);;所有文件 (*.*)"
        )
        self._add_to_list(files)

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择包含 NCM 的文件夹")
        if d:
            self._add_to_list(sorted(glob.glob(os.path.join(d, "*.ncm"))))

    def _add_to_list(self, files):
        existing = {self.list_files.item(i).text() for i in range(self.list_files.count())}
        for f in files:
            if f.lower().endswith(".ncm") and f not in existing:
                self.list_files.addItem(f)
                existing.add(f)
        self._update_status()

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.edit_outdir.setText(d)

    def _open_outdir(self):
        d = self.edit_outdir.text().strip() or ""
        if not d and self.list_files.count() > 0:
            d = os.path.join(os.path.dirname(self.list_files.item(0).text()), "ncm_output")
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa: S606

    def _start_convert(self):
        if self._worker and self._worker.isRunning():
            return
        files = [self.list_files.item(i).text() for i in range(self.list_files.count())]
        if not files:
            QMessageBox.information(self, "提示", "请先添加 NCM 文件。")
            return
        out_dir = self.edit_outdir.text().strip() or None

        self.list_log.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.btn_convert.setEnabled(False)
        self.lbl_status.setText(f"正在转换 ... 共 {len(files)} 个文件")

        self._worker = NcmWorker(
            files, out_dir, self.chk_meta_name.isChecked(), self.chk_cover.isChecked()
        )
        self._worker.log.connect(self._on_log)
        self._worker.progress.connect(lambda cur, tot: self.progress.setValue(cur))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_log(self, msg, paths):
        item = QListWidgetItem(msg)
        item.setData(Qt.UserRole, paths)
        self.list_log.addItem(item)
        self.list_log.scrollToBottom()

    def _on_done(self, ok, total):
        self.progress.setVisible(False)
        self.btn_convert.setEnabled(True)
        self.lbl_status.setText(f"完成：{ok}/{total} 个 NCM 转换成功。")
        QMessageBox.information(self, "完成", f"转换完成！\n{ok}/{total} 个 NCM 解密成功。")

    def _update_status(self):
        n = self.list_files.count()
        self.lbl_status.setText(f"已添加 {n} 个 NCM 文件，点击「开始转换」")

    # ── 右键菜单（与 PDF 工具一致） ──────────────────
    def _menu_files(self, pos):
        self._popup_menu(self.list_files, pos)

    def _menu_log(self, pos):
        self._popup_menu(self.list_log, pos)

    def _popup_menu(self, lst, pos):
        item = lst.itemAt(pos)
        if not item:
            return
        lst.setCurrentItem(item)
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
        if not paths:
            act_open.setEnabled(False)
            act_save.setEnabled(False)
            act_folder.setEnabled(False)

        act = menu.exec(lst.mapToGlobal(pos))
        if act == act_open and paths:
            os.startfile(paths[0])  # noqa: S606
        elif act == act_folder and paths:
            if len(paths) == 1:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(paths[0])])
            else:
                os.startfile(os.path.dirname(paths[0]))
        elif act == act_save and paths:
            self._save_as(paths[0])
        elif act == act_del:
            lst.takeItem(lst.row(item))
            if lst is self.list_files:
                self._update_status()

    def _save_as(self, src):
        dest, _ = QFileDialog.getSaveFileName(
            self, "另存为", os.path.basename(src), "音频文件 (*.mp3 *.flac);;所有文件 (*.*)"
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
                paths.extend(sorted(glob.glob(os.path.join(path, "*.ncm"))))
            elif path.lower().endswith(".ncm"):
                paths.append(path)
        if paths:
            self._add_to_list(paths)
            self.lbl_status.setText(f"已拖入 {len(paths)} 个 NCM 文件，点击「开始转换」")
        event.acceptProposedAction()
