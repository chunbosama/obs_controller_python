"""
gui/tab_audio.py  ——  音频混音台标签页（PyQt5 版）
每路音频：名称 | 音量滑块 | dB 显示 | 静音按钮 | VU 表
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSlider, QGroupBox, QScrollArea, QSizePolicy,
)
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtCore import Qt

from .utils import run_in_thread, FONT_BOLD, CLR_GREEN, CLR_YELLOW, CLR_RED

if TYPE_CHECKING:
    from .app import OBSGui


# VU 表颜色阈值
VU_COLORS = [
    (-60, -18, CLR_GREEN),
    (-18,  -6, CLR_YELLOW),
    ( -6,   0, CLR_RED),
]

VU_W, VU_H = 120, 10


class VUMeter(QWidget):
    """简易 VU 电平表。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(80, 8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._db = -60.0

    def set_db(self, db: float) -> None:
        self._db = max(-60.0, min(0.0, db))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setPen(Qt.NoPen)

        # 获取实际大小
        w = self.width()
        h = self.height()

        # 背景
        p.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        ratio = (self._db + 60) / 60.0
        fill_w = int(w * ratio)

        x = 0
        for lo, hi, color in VU_COLORS:
            seg_ratio_lo = (lo + 60) / 60.0
            seg_ratio_hi = (hi + 60) / 60.0
            seg_x0 = int(w * seg_ratio_lo)
            seg_x1 = int(w * seg_ratio_hi)
            if fill_w > seg_x0:
                p.fillRect(seg_x0, 0, min(fill_w, seg_x1) - seg_x0, h, QColor(color))

        p.end()


class AudioChannel(QWidget):
    """单路音频 UI 行。"""

    def __init__(self, parent, name: str, app: "OBSGui"):
        super().__init__(parent)
        self.name = name
        self.app = app
        self._muted = False

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)

        # 名称
        name_label = QLabel(name[:22])
        name_label.setFixedWidth(160)
        row.addWidget(name_label)

        # 音量滑块
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(100)
        self._slider.setFixedWidth(160)
        self._slider.valueChanged.connect(self._on_volume)
        row.addWidget(self._slider)

        # dB 显示
        self._db_label = QLabel("  0 dB")
        self._db_label.setFixedWidth(60)
        row.addWidget(self._db_label)

        # 静音按钮
        self._mute_btn = QPushButton("🔊")
        self._mute_btn.setFixedWidth(36)
        self._mute_btn.clicked.connect(self._on_mute)
        row.addWidget(self._mute_btn)

        # VU 表
        self._vu = VUMeter()
        row.addWidget(self._vu)

        row.addStretch()

    def _on_volume(self, val: int) -> None:
        mul = val / 100.0
        db_str = f"{(val - 60):.0f} dB"
        self._db_label.setText(db_str.rjust(7))
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        run_in_thread(lambda: ctrl.set_input_volume(self.name, mul=mul))

    def _on_mute(self) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        self._muted = not self._muted
        self._mute_btn.setText("🔇" if self._muted else "🔊")
        run_in_thread(lambda: ctrl.set_input_mute(self.name, self._muted))

    def update_vu(self, db: float) -> None:
        self._vu.set_db(db)

    def set_volume(self, mul: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(int(mul * 100))
        self._slider.blockSignals(False)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._mute_btn.setText("🔇" if muted else "🔊")


class AudioTab(QWidget):
    """音频混音台标签页。"""

    def __init__(self, parent, app: "OBSGui"):
        super().__init__(parent)
        self.app = app
        self._channels: dict[str, AudioChannel] = {}
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部工具行
        top = QHBoxLayout()
        top.addWidget(QLabel("音频混音台"))
        top.addStretch()
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setProperty("outline", True)
        btn_refresh.clicked.connect(self.refresh)
        top.addWidget(btn_refresh)
        layout.addLayout(top)

        # 通道容器（带滚动区域）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()

        scroll.setWidget(self._container)
        layout.addWidget(scroll)

    def refresh(self) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        run_in_thread(ctrl.get_audio_inputs, self._on_inputs_loaded)

    def _on_inputs_loaded(self, inputs: list) -> None:
        # 清空旧通道
        for ch in self._channels.values():
            ch.deleteLater()
        self._channels.clear()

        for inp in inputs:
            name = inp if isinstance(inp, str) else inp.get("name", "")
            if not name:
                continue
            ch = AudioChannel(self._container, name, self.app)
            self._channels[name] = ch
            # 在 stretch 之前插入
            self._container_layout.insertWidget(
                self._container_layout.count() - 1, ch
            )
            # 获取当前音量
            run_in_thread(
                lambda n=name: self.app.ctrl.get_input_volume(n),
                lambda vol, n=name: self._apply_volume(n, vol),
            )

    def _apply_volume(self, name: str, vol) -> None:
        ch = self._channels.get(name)
        if ch is None:
            return
        if isinstance(vol, dict):
            mul = vol.get("volume_mul", 1.0)
        elif hasattr(vol, "input_volume_mul"):
            mul = vol.input_volume_mul
        else:
            mul = 1.0
        ch.set_volume(mul)

    def update_vu(self, name: str, db: float) -> None:
        ch = self._channels.get(name)
        if ch:
            ch.update_vu(db)

    def update_mute(self, name: str, muted: bool) -> None:
        ch = self._channels.get(name)
        if ch:
            ch.set_muted(muted)
