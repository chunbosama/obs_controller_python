"""
gui/log_window.py  ——  左下角日志输出窗口（PyQt5 版）
支持分级彩色日志、时间戳、自动滚动
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import (
    QGroupBox, QTextEdit, QVBoxLayout,
)
from PyQt5.QtGui import QTextCharFormat, QColor, QFont
from PyQt5.QtCore import Qt

from .utils import CLR_GREEN, CLR_RED, CLR_YELLOW, CLR_SUBTEXT

if TYPE_CHECKING:
    from .app import OBSGui


class LogWindow(QGroupBox):
    """左下角日志输出面板。"""

    MAX_LINES = 500

    LEVEL_STYLES = {
        "INFO":    ("#a0a0c0", "[INFO]"),
        "SUCCESS": (CLR_GREEN, "[OK]   "),
        "WARNING": (CLR_YELLOW, "[WARN] "),
        "ERROR":   (CLR_RED,   "[ERR]  "),
        "DEBUG":   (CLR_SUBTEXT, "[DBG]  "),
    }

    def __init__(self, parent, app: "OBSGui"):
        super().__init__(" 📜 日志输出 ", parent)
        self.app = app
        self._line_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setStyleSheet(
            "QTextEdit { background-color: #161624; color: #a0a0c0; border: none; }"
        )
        layout.addWidget(self._text)

        # 预定义颜色格式
        self._formats = {}
        for level, (color, _) in self.LEVEL_STYLES.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._formats[level] = fmt

        self._ts_fmt = QTextCharFormat()
        self._ts_fmt.setForeground(QColor("#888888"))

    def log(self, message: str, level: str = "INFO") -> None:
        """线程安全写入日志（PyQt5 信号机制已在主线程，但保留接口）。"""
        self._write(message, level)

    def clear(self) -> None:
        self._text.clear()
        self._line_count = 0

    def _write(self, message: str, level: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        level_key = level.upper()
        if level_key not in self.LEVEL_STYLES:
            level_key = "INFO"
        style = self.LEVEL_STYLES[level_key]
        icon = style[1]

        cursor = self._text.textCursor()
        cursor.movePosition(cursor.End)

        # 时间戳
        cursor.insertText(f"[{now}] ", self._ts_fmt)
        # 等级 + 内容
        cursor.insertText(f"{icon} {message}\n", self._formats.get(level_key, self._formats["INFO"]))

        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

        self._line_count += 1
        self._trim_if_needed()

    def _trim_if_needed(self) -> None:
        """超出 MAX_LINES 时，一次性删除前半段内容（块操作，比逐行高效）。"""
        if self._line_count <= self.MAX_LINES:
            return
        keep = self.MAX_LINES // 2
        trim_count = self._line_count - keep

        # 用块选择一次删除多余行
        doc = self._text.document()
        cursor = self._text.textCursor()
        cursor.movePosition(cursor.Start)
        # 跳过 trim_count 行
        for _ in range(trim_count):
            cursor.movePosition(cursor.Down, cursor.KeepAnchor)
        cursor.movePosition(cursor.StartOfLine, cursor.KeepAnchor)
        cursor.removeSelectedText()
        self._line_count = keep
