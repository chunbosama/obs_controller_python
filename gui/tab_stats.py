"""
gui/tab_stats.py  ——  统计 / 系统信息面板（右下角迷你面板模式，PyQt5 版）
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGridLayout, QWidget,
)
from PyQt5.QtCore import Qt

from .utils import run_in_thread, FONT_BIG, FONT_BOLD, FONT_LABEL, FONT_MONO

if TYPE_CHECKING:
    from .app import OBSGui


class StatCard(QGroupBox):
    """单项统计卡片：大数字 + 单位标签。"""

    def __init__(self, parent, title: str, color: str = "#375a7f"):
        super().__init__(f" {title} ", parent)
        self.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {color};
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 14px;
                color: {color};
            }}
            QGroupBox::title {{
                color: {color};
            }}
        """)
        layout = QVBoxLayout(self)
        self._label = QLabel("--")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(f"font-size: 16pt; font-weight: bold; color: {color};")
        layout.addWidget(self._label)

    def set(self, value: str) -> None:
        self._label.setText(value)


class StatsTab(QGroupBox):
    """统计/系统信息：嵌入右下角的紧凑统计面板。"""

    def __init__(self, parent, app: "OBSGui"):
        super().__init__(" 📊 实时统计 ", parent)
        self.app = app
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        # ── 统计卡片 ──
        card_row = QHBoxLayout()

        # 修复：StatCard 父对象应为 self（QGroupBox），而非 card_row.widget()（返回 None）
        self._fps_card  = StatCard(self, "FPS",  "#3dd68c")
        self._cpu_card  = StatCard(self, "CPU%", "#fbbf24")
        self._mem_card  = StatCard(self, "MEM MB", "#4f8fc0")
        self._disk_card = StatCard(self, "磁盘 GB", "#8888a8")

        card_row.addWidget(self._fps_card)
        card_row.addWidget(self._cpu_card)
        card_row.addWidget(self._mem_card)
        card_row.addWidget(self._disk_card)
        layout.addLayout(card_row)

        # ── 版本/平台信息 + 快照按钮 ──
        info_row = QHBoxLayout()

        ver_layout = QVBoxLayout()
        self._ver_vars: dict[str, QLabel] = {}
        for key, label in [("obsVersion", "OBS"), ("platform", "平台")]:
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(40)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            var = QLabel("--")
            var.setStyleSheet("font-family: Consolas; color: #375a7f;")
            row.addWidget(var)
            self._ver_vars[key] = var
            ver_layout.addLayout(row)

        self._ver_vars["obsWebSocketVersion"] = QLabel("--")
        info_row.addLayout(ver_layout)
        info_row.addStretch()

        # 快照按钮
        btn_snap_save = QPushButton("💾")
        btn_snap_save.setProperty("outline", True)
        btn_snap_save.setFixedWidth(32)
        btn_snap_save.clicked.connect(self._save_snapshot)
        info_row.addWidget(btn_snap_save)

        btn_snap_load = QPushButton("📂")
        btn_snap_load.setProperty("outline", True)
        btn_snap_load.setFixedWidth(32)
        btn_snap_load.clicked.connect(self._load_snapshot)
        info_row.addWidget(btn_snap_load)

        self._snap_status = QLabel("")
        self._snap_status.setStyleSheet("color: #00bc8c;")
        info_row.addWidget(self._snap_status)

        layout.addLayout(info_row)

    # ── 刷新统计数据 ──────────────────────────────────────────

    def refresh(self) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        run_in_thread(ctrl.get_stats, self._on_stats)
        run_in_thread(ctrl.get_version, self._on_version)

    def _on_stats(self, stats) -> None:
        def _get(obj, *keys):
            for k in keys:
                if isinstance(obj, dict):
                    v = obj.get(k)
                else:
                    v = getattr(obj, k, None)
                if v is not None:
                    return v
            return None

        fps  = _get(stats, "activeFps", "active_fps")
        cpu  = _get(stats, "cpuUsage",  "cpu_usage")
        mem  = _get(stats, "memoryUsage", "memory_usage")
        disk = _get(stats, "availableDiskSpace", "available_disk_space")

        self._fps_card.set(f"{fps:.1f}" if fps is not None else "--")
        self._cpu_card.set(f"{cpu:.1f}" if cpu is not None else "--")
        self._mem_card.set(f"{mem:.0f}" if mem is not None else "--")
        self._disk_card.set(f"{disk/1024:.1f}" if disk is not None else "--")

    def _on_version(self, ver) -> None:
        def _get(obj, *keys):
            for k in keys:
                if isinstance(obj, dict):
                    v = obj.get(k)
                else:
                    v = getattr(obj, k, None)
                if v is not None:
                    return v
            return "--"

        if "obsVersion" in self._ver_vars:
            self._ver_vars["obsVersion"].setText(_get(ver, "obsVersion", "obs_version"))
        if "platform" in self._ver_vars:
            self._ver_vars["platform"].setText(_get(ver, "platform", "platform"))

    # ── 快照 ─────────────────────────────────────────────────

    def _save_snapshot(self) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return

        def do_save():
            self._snapshot = ctrl.snapshot_state()

        run_in_thread(
            do_save,
            lambda _: self._snap_status.setText("✅ 已保存"),
        )

    def _load_snapshot(self) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        snapshot = getattr(self, "_snapshot", None)
        if snapshot is None:
            self._snap_status.setText("⚠️ 先保存")
            return
        run_in_thread(
            lambda: ctrl.restore_state(snapshot),
            lambda _: self._snap_status.setText("✅ 已恢复"),
        )
