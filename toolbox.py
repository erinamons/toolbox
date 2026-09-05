#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具箱（Toolbox）— Win95 风格
==============================
聚合多个小工具的启动器。新增工具步骤：
  1. 在 tools/ 下新建 xxx_tool.py，继承 tools.base.ToolWidget（实现 name/description/icon/build_ui）
  2. 在下方 TOOLS 列表里注册即可
"""
import html
import os
import sys
import threading

from PySide6.QtCore import QObject, Qt, QSize, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import updater
from tools.pdf2jpg_tool import PDF2JPGTool
from tools.ncm2mp3_tool import NCM2MP3Tool
from tools.mediainfo_tool import MediaInfoTool
from tools.compress_tool import CompressTool

# ── 工具注册表：新工具在此追加 ─────────────────────
TOOLS = [
    PDF2JPGTool,
    NCM2MP3Tool,
    MediaInfoTool,
    CompressTool,
]

APP_VERSION = "1.1"

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "toolbox.png")

HELP_TEXT = """<h2>工具箱 使用帮助</h2>
<p>这是一个 Win95 风格的小工具集，把常用小功能聚合在一起。</p>

<h3>📄 PDF 转 JPG</h3>
<p>把 PDF 的每一页转换为 JPG 图片。</p>
<ul>
  <li>支持 1x / 2x / 3x 三档清晰度，2x 为默认（清晰与体积均衡）</li>
  <li>输出目录留空时，自动存到 PDF 同目录下的 <code>jpg_output</code> 文件夹</li>
  <li>单页 PDF 输出 <code>文件名.jpg</code>，多页则输出 <code>文件名_p1.jpg</code> 等</li>
</ul>

<h3>🎵 NCM 转 MP3</h3>
<p>把网易云音乐的 NCM 加密文件解密还原为 MP3 或 FLAC（无损）。</p>
<ul>
  <li>自动识别内层格式：MP3 / FLAC，无需手动选择</li>
  <li>勾选「按元数据命名」时，用 <code>歌手 - 歌名</code> 作为输出文件名</li>
  <li>勾选「导出专辑封面」可同时保存封面图片</li>
</ul>
<h3>🎬 MediaInfo</h3>
<p>拖入视频/音频文件，查看完整技术参数（编码、分辨率、帧率、音轨、字幕、章节等）。</p>
<ul>
  <li>支持批量：一次拖入多个文件或整个文件夹，列表中点击切换查看</li>
  <li>「复制当前/全部信息」可导出 MediaInfo 风格纯文本，方便发帖求助时粘贴</li>
  <li>依赖 <code>bin/ffprobe.exe</code>（ffmpeg 官方 build 内含），安装版已自带</li>
</ul>
<h3>🗜 视频压缩</h3>
<p>本地视频压制（小丸工具箱式）：H.264 兼容 / H.265 更小体积，CRF 质量滑条，批量队列。</p>
<ul>
  <li>质量滑条：CRF 18（高画质）→ 32（高压缩），默认 23 均衡</li>
  <li>速度预设 veryfast 适合日常，slow 花时间换更小体积</li>
  <li>输出统一 MP4（H.265 建议用支持 HEVC 的播放器），完成后显示前后体积对比</li>
  <li>依赖 <code>bin/ffmpeg.exe</code>（安装包已自带）</li>
</ul>
<p><b>注意</b>：请仅用于转换自己账号下载 / 已购歌曲的个人备份，勿用于传播。</p>

<h3>🖱 通用操作</h3>
<ul>
  <li><b>拖拽</b>：把文件或文件夹直接拖进窗口即可批量添加</li>
  <li><b>右键菜单</b>：在文件列表或输出列表上点右键，可打开、打开文件夹、另存为、删除当前项</li>
  <li><b>悬停提示</b>：鼠标停在任意控件上，底部状态栏会显示该控件的用途</li>
</ul>

<h3>⌨ 快捷键</h3>
<ul>
  <li><b>F1</b> —— 打开本帮助</li>
  <li><b>Esc</b> —— 从工具页返回首页</li>
  <li><b>Alt+F4</b> —— 退出程序</li>
</ul>
"""

ABOUT_TEXT = """<div style="text-align:center">
<h2>工具箱</h2>
<p>版本 v{version}</p>
<p>Win95 经典风格的小工具集合</p>
<p>当前收录 {n} 个工具：{names}</p>
<hr>
<p style="color:#555">NCM 解密功能仅供个人备份已购歌曲使用，请勿用于传播。</p>
</div>"""


class UpdateSignals(QObject):
    """跨线程信号桥：更新工作线程（纯标准库）→ 主线程 UI。

    Qt 信号从非 GUI 线程 emit 时自动走 QueuedConnection，
    回调在主线程执行，GUI 操作安全。
    """
    check_done = Signal(object, bool)   # UpdateInfo | None, manual
    progress = Signal(int, int)         # downloaded_bytes, total_bytes
    download_done = Signal(str)         # 校验通过的新版临时文件路径
    download_failed = Signal(str)       # 错误信息


class ToolboxWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("工具箱")
        self.setWindowIcon(QIcon(LOGO_PATH))
        self.resize(620, 500)
        self.setMinimumSize(560, 440)
        self.setStyleSheet(self._load_qss())
        self._update_state = "idle"      # idle / checking / downloading
        self._cancel_download = threading.Event()
        self._sig = UpdateSignals()
        self._sig.check_done.connect(self._on_check_done)
        self._sig.progress.connect(self._on_download_progress)
        self._sig.download_done.connect(self._on_download_done)
        self._sig.download_failed.connect(self._on_download_failed)
        self._build()
        self._bind_shortcuts()
        # 启动 1.5 秒后静默检查更新（不阻塞 UI）
        QTimer.singleShot(1500, self._silent_check)

    @staticmethod
    def _load_qss():
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "win95.qss")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def _bind_shortcuts(self):
        # F1 → 帮助
        self._sc_help = QShortcut(QKeySequence(Qt.Key_F1), self)
        self._sc_help.activated.connect(self._show_help)
        # Esc → 返回首页
        self._sc_home = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._sc_home.activated.connect(self.go_home)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        # ── 顶部菜单栏（真实 QMenuBar） ─────────────────
        root.addWidget(self._build_menu())

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # ── 首页：Win95 风格 ──────────────────────────
        home = QWidget()
        v = QVBoxLayout(home)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        for tool_cls in TOOLS:
            btn = QPushButton()
            btn.setObjectName("toolBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(32, 32))
            if getattr(tool_cls, "icon_path", "") and os.path.isfile(tool_cls.icon_path):
                btn.setIcon(QIcon(tool_cls.icon_path))
                btn.setText(f"  {tool_cls.name}\n        {tool_cls.description}")
            else:
                btn.setText(f"{tool_cls.icon}  {tool_cls.name}\n        {tool_cls.description}")
            btn.clicked.connect(lambda checked, i=TOOLS.index(tool_cls): self._open_tool(i))
            v.addWidget(btn)

        v.addStretch(1)

        status = QLabel(f"已安装 {len(TOOLS)} 个工具 · 点击卡片打开 · F1 查看帮助")
        status.setObjectName("statusBar")
        v.addWidget(status)

        self.stack.addWidget(home)

        # ── 工具页 ────────────────────────────────────
        self.tool_pages = []
        for tool_cls in TOOLS:
            page = tool_cls(on_back=self.go_home)
            self.tool_pages.append(page)
            self.stack.addWidget(page)

    def _build_menu(self):
        menubar = QMenuBar()
        menubar.setObjectName("menuBar")

        # 文件(F)
        m_file = menubar.addMenu("文件(&F)")
        act_about = m_file.addAction("关于工具箱(&A)...")
        act_about.triggered.connect(self._show_about)
        m_file.addSeparator()
        act_quit = m_file.addAction("退出(&X)")
        act_quit.triggered.connect(QApplication.quit)

        # 帮助(H)
        m_help = menubar.addMenu("帮助(&H)")
        act_help = m_help.addAction("使用帮助(&C)\tF1")
        act_help.triggered.connect(self._show_help)
        m_help.addSeparator()
        act_check = m_help.addAction("检查更新(&U)...")
        act_check.triggered.connect(self._manual_check)
        act_about2 = m_help.addAction("关于工具箱(&A)...")
        act_about2.triggered.connect(self._show_about)

        return menubar

    def _open_tool(self, idx):
        self.stack.setCurrentIndex(idx + 1)

    def go_home(self):
        self.stack.setCurrentIndex(0)

    # ── 自动更新 ─────────────────────────────────────
    def _silent_check(self):
        """启动后静默检查，仅在有更新时弹窗，失败静默。"""
        self._start_check(manual=False)

    def _manual_check(self):
        """菜单手动检查：无论结果如何都给出反馈。"""
        self._start_check(manual=True)

    def _start_check(self, manual):
        if self._update_state != "idle":
            if manual:
                QMessageBox.information(self, "检查更新", "更新操作正在进行中，请稍候。")
            return
        self._update_state = "checking"
        threading.Thread(
            target=self._check_worker, args=(manual,), daemon=True
        ).start()

    def _check_worker(self, manual):
        info = updater.check_update(APP_VERSION)   # 失败返回 None
        self._sig.check_done.emit(info, manual)

    def _on_check_done(self, info, manual):
        self._update_state = "idle"
        if info is not None:
            self._pending_update = info
            self._show_update_dialog(info, manual)
            return
        if manual:
            if updater.last_error:
                QMessageBox.warning(
                    self, "检查更新",
                    f"检查更新失败：\n{updater.last_error}"
                )
            else:
                QMessageBox.information(
                    self, "检查更新",
                    f"已是最新版本（v{APP_VERSION}）。"
                )

    def _show_update_dialog(self, info, manual):
        notes = html.escape(info.notes).replace("\n", "<br>")
        size_mb = info.size / 1048576 if info.size else None
        size_txt = f"（约 {size_mb:.1f} MB）" if size_mb else ""
        msg = QMessageBox(self)
        msg.setWindowTitle("发现新版本")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            f"<b>新版本 v{html.escape(info.latest)} 可用</b>{size_txt}<br>"
            f"当前版本 v{APP_VERSION}"
        )
        if notes:
            msg.setInformativeText(notes)
        btn_update = msg.addButton("立即更新", QMessageBox.AcceptRole)
        btn_later = msg.addButton("稍后", QMessageBox.RejectRole)
        btn_skip = msg.addButton("跳过此版", QMessageBox.NoRole)
        if info.mandatory:
            btn_later.setVisible(False)
            btn_skip.setVisible(False)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is btn_update:
            self._start_download(info)
        elif clicked is btn_skip:
            updater.set_skip_version(info.latest)
        # 稍后 / 关闭：什么都不做，下次启动静默检查还会再提示

    def _start_download(self, info):
        if self._update_state != "idle":
            return
        self._update_state = "downloading"
        self._cancel_download.clear()

        total = info.size
        self._dl_dlg = QProgressDialog(
            f"正在下载新版本 v{info.latest} …", "取消", 0,
            100 if total else 0, self
        )
        self._dl_dlg.setWindowTitle("更新")
        self._dl_dlg.setWindowModality(Qt.WindowModal)
        self._dl_dlg.setMinimumDuration(0)     # 立即显示
        self._dl_dlg.canceled.connect(self._cancel_download.set)
        if not total:
            self._dl_dlg.setLabelText(
                f"正在下载新版本 v{info.latest} …（大小未知）"
            )

        threading.Thread(
            target=self._download_worker, args=(info,), daemon=True
        ).start()

    def _download_worker(self, info):
        try:
            tmp = updater.download(
                info,
                progress_cb=lambda d, t: self._sig.progress.emit(d, t),
                cancel_event=self._cancel_download,
            )
        except updater.UpdateError as e:
            self._sig.download_failed.emit(str(e))
            return
        except Exception as e:                 # 兜底：工作线程绝不让异常外泄
            self._sig.download_failed.emit(f"下载过程出现未预期错误：{e}")
            return
        self._sig.download_done.emit(tmp)

    def _on_download_progress(self, done, total):
        dlg = getattr(self, "_dl_dlg", None)
        if dlg is None:
            return
        if total > 0:
            dlg.setRange(0, 100)
            dlg.setValue(int(done * 100 / total))
            dlg.setLabelText(
                f"已下载 {done / 1048576:.1f} / {total / 1048576:.1f} MB"
            )
        else:
            dlg.setRange(0, 0)                 # 未知大小 → 繁忙指示
            dlg.setLabelText(f"已下载 {done / 1048576:.1f} MB")

    def _on_download_done(self, tmp_path):
        dlg = getattr(self, "_dl_dlg", None)
        if dlg is not None:
            dlg.reset()
            dlg.close()
        self._update_state = "idle"

        if self._cancel_download.is_set():
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return

        self._pending_exe = tmp_path
        confirm = QMessageBox.question(
            self, "安装更新",
            "新版本已下载并通过校验。\n"
            "立即安装并重启工具箱？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm == QMessageBox.Yes:
            try:
                updater.install_and_restart(tmp_path)   # 成功则不返回
            except updater.UpdateError as e:
                QMessageBox.critical(self, "安装失败", str(e))
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        else:
            # 稍后安装：保留临时文件，退出前再问一次
            self._keep_exe = tmp_path
            QMessageBox.information(
                self, "安装更新",
                "已保留下载的更新文件。\n本次退出时将再次询问是否安装。"
            )

    def _on_download_failed(self, err):
        dlg = getattr(self, "_dl_dlg", None)
        if dlg is not None:
            dlg.reset()
            dlg.close()
        self._update_state = "idle"
        if self._cancel_download.is_set():
            return                              # 用户主动取消，不弹错误
        QMessageBox.critical(self, "更新失败", err)

    def closeEvent(self, event):
        """退出时机处理：若留有已下载未安装的更新，再问一次。"""
        exe = getattr(self, "_keep_exe", None)
        if exe and os.path.isfile(exe):
            confirm = QMessageBox.question(
                self, "安装更新",
                "退出前安装已下载的新版本？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if confirm == QMessageBox.Yes:
                try:
                    updater.install_and_restart(exe)    # 成功则不返回
                except updater.UpdateError:
                    pass                                # 安装失败，清理后正常退出
            # 拒绝安装或安装失败：清理临时文件，下次有需要重新下载
            try:
                os.remove(exe)
            except OSError:
                pass
            self._keep_exe = None
        event.accept()

    # ── 帮助 / 关于对话框 ─────────────────────────────
    def _show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("工具箱帮助")
        dlg.resize(460, 480)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(HELP_TEXT)
        lay.addWidget(browser, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        dlg.exec()

    def _show_about(self):
        names = "、".join(t.name for t in TOOLS)
        dlg = QDialog(self)
        dlg.setWindowTitle("关于工具箱")
        dlg.setFixedWidth(360)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        if os.path.isfile(LOGO_PATH):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(QIcon(LOGO_PATH).pixmap(48, 48))
            icon_lbl.setAlignment(Qt.AlignHCenter)
            lay.addWidget(icon_lbl)

        text = QLabel(ABOUT_TEXT.format(version=APP_VERSION, n=len(TOOLS), names=names))
        text.setTextFormat(Qt.RichText)
        text.setAlignment(Qt.AlignHCenter)
        lay.addWidget(text)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_update = QPushButton("检查更新")
        btn_update.clicked.connect(lambda: (dlg.accept(), self._manual_check()))
        btn_row.addWidget(btn_update)
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        dlg.exec()


def main():
    updater.cleanup_old_files()          # 清理上次升级残留的 .old
    app = QApplication(sys.argv)
    win = ToolboxWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
