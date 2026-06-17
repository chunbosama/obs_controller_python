"""
gui/utils.py  ——  PyQt5 公共常量 & 线程安全工具
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool
from typing import Callable, Any, Optional


# ── 颜色常量（暗色主题） ──────────────────────────────────────────
CLR_BG        = "#1e1e2e"   # 深紫蓝背景，对比度比纯黑更舒适
CLR_PANEL     = "#252535"   # 面板背景
CLR_ACCENT    = "#4f8fc0"   # 主强调色（亮蓝）
CLR_GREEN     = "#3dd68c"   # 绿色（成功/录制中）
CLR_RED       = "#f25f5c"   # 红色（危险/停止）
CLR_YELLOW    = "#fbbf24"   # 黄色（警告/暂停）
CLR_TEXT      = "#e8e8f0"   # 主文本
CLR_SUBTEXT   = "#8888a8"   # 次级文本

# ── 字体 ────────────────────────────────────────────────────────
FONT_LABEL    = ("Segoe UI", 9)
FONT_BOLD     = ("Segoe UI", 9, "bold")
FONT_TITLE    = ("Segoe UI", 10, "bold")
FONT_BIG      = ("Segoe UI", 18, "bold")
FONT_MONO     = ("Consolas", 9)

PREVIEW_W = 480
PREVIEW_H = 270


# ── 全局线程池 ────────────────────────────────────────────────────
_thread_pool = QThreadPool.globalInstance()

# 保持 Worker/Signals 的 Python 引用，防止 GC 过早回收 C++ 底层对象
_pending_refs: set = set()


class _WorkerSignals(QObject):
    """Worker 的信号集。"""
    finished = pyqtSignal(object)   # 正常结果
    error    = pyqtSignal(Exception)  # 异常


class _Worker(QRunnable):
    """在 QThreadPool 中执行 fn，通过信号回传结果。"""

    def __init__(self, fn: Callable[[], Any], signals: _WorkerSignals):
        super().__init__()
        self.fn = fn
        self.signals = signals

    def run(self):
        try:
            result = self.fn()
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(exc)


def _cleanup_refs(worker: _Worker, signals: _WorkerSignals, *args) -> None:
    """Worker 完成后释放引用。"""
    _pending_refs.discard(worker)
    _pending_refs.discard(signals)


def run_in_thread(
    fn: Callable[[], Any],
    ok_cb: Optional[Callable[[Any], None]] = None,
    err_cb: Optional[Callable[[Exception], None]] = None,
) -> None:
    """在 QThreadPool 线程中执行 fn，结果通过信号回调到主线程。"""
    signals = _WorkerSignals()
    worker = _Worker(fn, signals)

    # 保持引用防止 GC 过早回收 C++ 对象
    _pending_refs.add(worker)
    _pending_refs.add(signals)

    # Worker 完成后自动释放引用
    signals.finished.connect(lambda *a: _cleanup_refs(worker, signals, *a))
    signals.error.connect(lambda *a: _cleanup_refs(worker, signals, *a))

    if ok_cb:
        signals.finished.connect(ok_cb)
    if err_cb:
        signals.error.connect(err_cb)

    _thread_pool.start(worker)


def format_timecode(ms: int) -> str:
    """毫秒 → HH:MM:SS 字符串。"""
    if ms < 0:
        return "--:--:--"
    s  = ms // 1000
    h  = s  // 3600
    m  = (s % 3600) // 60
    s  = s  % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ── 通用暗色 QSS 样式表 ──────────────────────────────────────────
DARK_STYLE = """
/* ── 基础 ──────────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #e8e8f0;
    font-family: "Segoe UI";
    font-size: 9pt;
}

/* ── GroupBox ────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #3a3a5c;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #9898b8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #9898b8;
}

/* ── Button 基础 ──────────────────────────────────────────── */
QPushButton {
    background-color: #2e3a5c;
    border: 1px solid #4f6a9a;
    border-radius: 5px;
    padding: 5px 14px;
    color: #e8e8f0;
    min-height: 22px;
    font-size: 9pt;
}
QPushButton:hover {
    background-color: #3d4e7a;
    border-color: #6680b0;
}
QPushButton:pressed {
    background-color: #222840;
}
QPushButton:disabled {
    background-color: #28282e;
    color: #55556a;
    border-color: #38384a;
}

/* ── Button 语义变体 ──────────────────────────────────────── */
QPushButton[danger="true"] {
    background-color: #7a2020;
    border-color: #a03030;
    color: #ffcccc;
}
QPushButton[danger="true"]:hover {
    background-color: #9a2828;
}
QPushButton[success="true"] {
    background-color: #1a5c3a;
    border-color: #28884e;
    color: #a0ffcc;
}
QPushButton[success="true"]:hover {
    background-color: #226848;
}
QPushButton[warning="true"] {
    background-color: #6c4a10;
    border-color: #a06818;
    color: #ffe8a0;
}
QPushButton[warning="true"]:hover {
    background-color: #7c5818;
}
QPushButton[outline="true"] {
    background-color: transparent;
    border: 1px solid #4f6a9a;
    color: #8aaccc;
}
QPushButton[outline="true"]:hover {
    background-color: #1e2c48;
    color: #c0d8f0;
}

/* ── 输入框 ───────────────────────────────────────────────── */
QLineEdit {
    background-color: #252535;
    border: 1px solid #3a3a5c;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e8e8f0;
    selection-background-color: #4f6a9a;
}
QLineEdit:focus {
    border-color: #4f8fc0;
    background-color: #2a2a42;
}

/* ── ComboBox ────────────────────────────────────────────── */
QComboBox {
    background-color: #252535;
    border: 1px solid #3a3a5c;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e8e8f0;
    min-height: 22px;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: #252535;
    color: #e8e8f0;
    border: 1px solid #3a3a5c;
    selection-background-color: #2e3a5c;
    selection-color: #c0d8f0;
    outline: none;
}

/* ── ListWidget ───────────────────────────────────────────── */
QListWidget {
    background-color: #252535;
    border: 1px solid #3a3a5c;
    border-radius: 4px;
    color: #e8e8f0;
    outline: none;
}
QListWidget::item {
    padding: 5px 8px;
    border-radius: 3px;
}
QListWidget::item:hover {
    background-color: #2a2a48;
}
QListWidget::item:selected {
    background-color: #2e3a5c;
    color: #c0d8f0;
}

/* ── TableWidget ──────────────────────────────────────────── */
QTableWidget {
    background-color: #252535;
    border: 1px solid #3a3a5c;
    gridline-color: #32324a;
    color: #e8e8f0;
    selection-background-color: #2e3a5c;
    border-radius: 4px;
}
QTableWidget::item {
    padding: 3px 6px;
}
QTableWidget::item:selected {
    background-color: #2e3a5c;
    color: #c0d8f0;
}
QHeaderView::section {
    background-color: #2a2a42;
    color: #9898b8;
    border: none;
    border-bottom: 1px solid #3a3a5c;
    border-right: 1px solid #3a3a5c;
    padding: 5px 8px;
    font-weight: bold;
    font-size: 9pt;
}

/* ── TabWidget ────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #3a3a5c;
    border-radius: 0 4px 4px 4px;
    background-color: #1e1e2e;
    top: -1px;
}
QTabBar::tab {
    background-color: #252535;
    border: 1px solid #3a3a5c;
    border-bottom: none;
    padding: 6px 16px;
    color: #8888a8;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
    font-size: 9pt;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #c0d8f0;
    border-bottom: 1px solid #1e1e2e;
}
QTabBar::tab:hover:!selected {
    background-color: #2a2a42;
    color: #b0b8d0;
}

/* ── Slider ───────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 6px;
    background: #38385a;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #4f8fc0;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
    border: 2px solid #6aaada;
}
QSlider::handle:horizontal:hover {
    background: #6aaada;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1a5c3a, stop:1 #3dd68c);
    border-radius: 3px;
}

/* ── SpinBox ──────────────────────────────────────────────── */
QSpinBox {
    background-color: #252535;
    border: 1px solid #3a3a5c;
    border-radius: 4px;
    padding: 3px 6px;
    color: #e8e8f0;
}
QSpinBox:focus {
    border-color: #4f8fc0;
}

/* ── TextEdit ─────────────────────────────────────────────── */
QTextEdit {
    background-color: #161624;
    color: #c0c0d8;
    border: 1px solid #3a3a5c;
    border-radius: 4px;
    font-family: Consolas, monospace;
    font-size: 9pt;
    selection-background-color: #2e3a5c;
}

/* ── Splitter ─────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #3a3a5c;
}
QSplitter::handle:horizontal {
    width: 3px;
}
QSplitter::handle:vertical {
    height: 3px;
}
QSplitter::handle:hover {
    background-color: #4f8fc0;
}

/* ── ScrollBar ────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #252535;
    width: 8px;
    border: none;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #4a4a6a;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: #6060a0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #252535;
    height: 8px;
    border: none;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #4a4a6a;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── StatusBar ────────────────────────────────────────────── */
QStatusBar {
    background-color: #161624;
    color: #8888a8;
    border-top: 1px solid #3a3a5c;
    font-size: 9pt;
}
QStatusBar::item {
    border-right: 1px solid #3a3a5c;
    padding: 0 8px;
}

/* ── Label semantic 快捷类 ─────────────────────────────────── */
QLabel[status="connected"] {
    color: #3dd68c;
}
QLabel[status="disconnected"] {
    color: #f25f5c;
}

/* ── ScrollArea ───────────────────────────────────────────── */
QScrollArea {
    border: none;
    background: transparent;
}
"""
