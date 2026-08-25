# -*- coding: utf-8 -*-
"""工具基类：所有工具继承 ToolWidget，实现 build_ui 即可。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ToolWidget(QWidget):
    """工具基类。

    子类需定义：
        name        : 工具名称（显示在卡片上）
        description : 一句话描述（显示在卡片上）
        icon        : 一个 emoji 图标（当 icon_path 为空时使用）
        icon_path   : PNG 图标绝对路径（可选，覆盖 emoji）
        build_ui    : 把工具界面构建到传入的 layout 中
    """

    name = "工具"
    description = ""
    icon = "🧰"
    icon_path = ""

    def __init__(self, on_back=None, parent=None):
        super().__init__(parent)
        self.on_back = on_back
        self._build_frame()

    def _build_frame(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # 顶部：返回 + 标题
        header = QHBoxLayout()
        if self.on_back:
            back_btn = QPushButton("← 返回")
            back_btn.setObjectName("backBtn")
            back_btn.clicked.connect(self.on_back)
            header.addWidget(back_btn)
        # 标题：有 PNG 图标时用图标，否则用 emoji
        if getattr(self, "icon_path", "") and os.path.isfile(self.icon_path):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                QPixmap(self.icon_path).scaledToHeight(22, Qt.SmoothTransformation)
            )
            header.addWidget(icon_lbl)
            title = QLabel(self.name)
        else:
            title = QLabel(f"{self.icon}  {self.name}")
        title.setObjectName("toolTitle")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        # 内容区（由子类填充）
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        root.addLayout(self.body)
        self.build_ui(self.body)

        # 弹性空间放在内容之后，空间不足时优先压缩这里，避免溢出重叠
        root.addStretch()

    def build_ui(self, layout):
        """子类实现：把界面控件加入 layout。"""
        raise NotImplementedError
