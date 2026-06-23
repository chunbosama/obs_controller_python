"""
gui/preview.py  ——  双画面预览区（PROGRAM / PREVIEW）+ 转场快捷按钮（PyQt5 版）
"""
from __future__ import annotations

import io
import base64
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import (
    QGroupBox, QLabel, QHBoxLayout, QVBoxLayout, QPushButton,
    QSlider, QWidget, QSizePolicy,
)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt, QTimer, QEvent

from .utils import PREVIEW_W, PREVIEW_H, CLR_GREEN, CLR_RED, run_in_thread

if TYPE_CHECKING:
    from .app import OBSGui


class PreviewPanel(QGroupBox):
    """左侧双画面预览区（PROGRAM + PREVIEW）及转场快捷按钮。"""

    def __init__(self, parent, app: "OBSGui"):
        super().__init__(" 📺 预览监视器 ", parent)
        self.app = app
        self._preview_locked_scene: str | None = None
        # 缓存当前 program 场景名，避免每次刷新额外发一次 get_current_scene 请求
        self._cached_program_scene: str | None = None

        self._init_ui()

        # 定时器：250ms 刷新一次，兼顾实时性和请求频率
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frames)
        # 防止事件触发和定时器同时刷新导致请求堆积
        self._last_refresh_ts: float = 0.0
        # 帧序号，用于日志追踪
        self._frame_seq: int = 0
        # 防止并发抓取
        self._fetching: bool = False

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 上方：两个预览画面并排
        canvas_row = QHBoxLayout()

        # PROGRAM
        prog_col = QVBoxLayout()
        prog_label = QLabel("🔴  PROGRAM")
        prog_label.setAlignment(Qt.AlignCenter)
        prog_label.setStyleSheet("font-weight: bold;")
        prog_col.addWidget(prog_label)

        self.program_label = QLabel()
        self.program_label.setMinimumSize(320, 180)
        self.program_label.setAlignment(Qt.AlignCenter)
        self.program_label.setStyleSheet(
            f"background-color: #1a1a1a; border: 2px solid {CLR_RED};"
        )
        self.program_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.program_label.setText("PROGRAM\n（未连接）")
        prog_col.addWidget(self.program_label)
        canvas_row.addLayout(prog_col)

        # PREVIEW
        prev_col = QVBoxLayout()
        prev_label = QLabel("🟢  PREVIEW")
        prev_label.setAlignment(Qt.AlignCenter)
        prev_label.setStyleSheet("font-weight: bold;")
        prev_col.addWidget(prev_label)

        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(320, 180)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            f"background-color: #1a1a1a; border: 2px solid {CLR_GREEN};"
        )
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setText("PREVIEW\n（未连接）")
        prev_col.addWidget(self.preview_label)
        canvas_row.addLayout(prev_col)

        layout.addLayout(canvas_row)

        # 下方：转场控制行
        ctrl = QHBoxLayout()

        btn_cut = QPushButton("CUT")
        btn_cut.setProperty("danger", True)
        btn_cut.setFixedWidth(70)
        btn_cut.clicked.connect(self.app.do_cut)
        ctrl.addWidget(btn_cut)

        btn_fade = QPushButton("FADE")
        btn_fade.setFixedWidth(70)
        btn_fade.clicked.connect(self.app.do_fade)
        ctrl.addWidget(btn_fade)

        btn_black = QPushButton("🌑 黑场")
        btn_black.setProperty("outline", True)
        btn_black.setFixedWidth(80)
        btn_black.clicked.connect(self.app.do_fade_to_black)
        ctrl.addWidget(btn_black)

        ctrl.addSpacing(10)

        ctrl.addWidget(QLabel("T-Bar:"))
        self.tbar_slider = QSlider(Qt.Horizontal)
        self.tbar_slider.setRange(0, 100)
        self.tbar_slider.setValue(0)
        self.tbar_slider.setFixedWidth(180)
        self.tbar_slider.valueChanged.connect(self._on_tbar)
        ctrl.addWidget(self.tbar_slider)

        ctrl.addStretch()

        btn_refresh = QPushButton("刷新列表")
        btn_refresh.setProperty("outline", True)
        btn_refresh.clicked.connect(self.app.refresh_all)
        ctrl.addWidget(btn_refresh)

        layout.addLayout(ctrl)

    # ── 预览更新循环 ─────────────────────────────────────────

    def start_loop(self) -> None:
        """连接成功后调用，启动 250ms 实时刷新循环。"""
        print("[preview] start_loop called")
        self.program_label.setText("连接中…")
        self.preview_label.setText("连接中…")
        self._cached_program_scene = None
        self._last_refresh_ts = 0.0
        self._fetching = False
        self._timer.start(250)
        print(f"[preview] timer started, isActive={self._timer.isActive()}")
        # 立即触发第一次刷新
        self._update_frames()

    def stop_loop(self) -> None:
        """断开连接时停止循环。"""
        self._timer.stop()
        self._preview_locked_scene = None
        self._cached_program_scene = None
        self.program_label.setText("PROGRAM\n（未连接）")
        self.program_label.setPixmap(QPixmap())
        self.preview_label.setText("PREVIEW\n（未连接）")
        self.preview_label.setPixmap(QPixmap())

    def trigger_refresh(self) -> None:
        """事件驱动的即时刷新，带 100ms 冷却防止请求堆积。"""
        import time
        now = time.time()
        if now - self._last_refresh_ts < 0.1:
            return
        self._last_refresh_ts = now
        self._update_frames()

    def preview_one_shot(self, scene_name: str) -> None:
        """在 PREVIEW 画面上显示指定场景的截图。"""
        ctrl = self.app.ctrl
        if ctrl is None:
            self.app.log("预览失败: 未连接到 OBS", "WARNING")
            return

        self._preview_locked_scene = scene_name
        self.app.log(f"正在预览场景: {scene_name}", "INFO")

        # 根据标签实际大小动态计算截图尺寸（保持 16:9 比例，避免拉伸变形）
        label_size = self.preview_label.size()
        width = max(label_size.width(), 320)
        height = max(int(width * 9 / 16), 180)

        def fetch():
            return ctrl.get_source_screenshot(
                source_name=scene_name,
                img_format="jpg", width=width, height=height,
                quality=60,
            )

        run_in_thread(
            fetch,
            lambda b64: self._put_image(self.preview_label, b64),
            lambda exc: self.app.log(f"预览截图失败 [{scene_name}]: {exc}", "WARNING"),
        )

    def _update_frames(self) -> None:
        """获取 PROGRAM 和 PREVIEW 的截图并更新画面。"""
        ctrl = self.app.ctrl
        if ctrl is None:
            print("[preview] _update_frames: ctrl is None, skip")
            return

        # 防止上一帧还未处理完时重复提交
        if self._fetching:
            return
        self._fetching = True

        self._frame_seq += 1
        seq = self._frame_seq
        override = self._preview_locked_scene
        cached_scene = self._cached_program_scene

        print(f"[preview] #{seq} _update_frames start, fetching=True")

        # 根据标签实际大小动态计算截图尺寸（保持 16:9 比例）
        prog_size = self.program_label.size()
        prev_size = self.preview_label.size()
        prog_width = max(prog_size.width(), 320)
        prog_height = max(int(prog_width * 9 / 16), 180)
        prev_width = max(prev_size.width(), 320)
        prev_height = max(int(prev_width * 9 / 16), 180)

        def fetch_both():
            """在后台线程中串行获取两个截图。"""
            import concurrent.futures
            print(f"[preview] #{seq} fetch_both thread started")

            # PROGRAM —— 带 5 秒超时
            scene = cached_scene
            if not scene:
                try:
                    scene = ctrl.get_current_scene()
                    print(f"[preview] #{seq} current scene = {scene}")
                except Exception as e:
                    print(f"[preview] #{seq} get_current_scene failed: {e}")
                    scene = ""
            prog_b64 = ""
            if scene:
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        fut = ex.submit(
                            ctrl.get_source_screenshot,
                            source_name=scene,
                            img_format="jpg", width=prog_width, height=prog_height,
                            quality=60,
                        )
                        prog_b64 = fut.result(timeout=5)
                    print(f"[preview] #{seq} PROGRAM screenshot OK, len={len(prog_b64)}")
                except concurrent.futures.TimeoutError:
                    print(f"[preview] #{seq} PROGRAM screenshot TIMEOUT")
                except Exception as exc:
                    print(f"[preview] #{seq} PROGRAM screenshot failed: {exc}")

            # PREVIEW —— 带 5 秒超时
            if override:
                prev_scene = override
            else:
                try:
                    prev_scene = ctrl.get_current_preview_scene() or ctrl.get_current_scene()
                    print(f"[preview] #{seq} preview scene = {prev_scene}")
                except Exception as e:
                    print(f"[preview] #{seq} get_preview_scene failed: {e}")
                    try:
                        prev_scene = ctrl.get_current_scene()
                    except Exception:
                        prev_scene = ""
            prev_b64 = ""
            if prev_scene:
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        fut = ex.submit(
                            ctrl.get_source_screenshot,
                            source_name=prev_scene,
                            img_format="jpg", width=prev_width, height=prev_height,
                            quality=60,
                        )
                        prev_b64 = fut.result(timeout=5)
                    print(f"[preview] #{seq} PREVIEW screenshot OK, len={len(prev_b64)}")
                except concurrent.futures.TimeoutError:
                    print(f"[preview] #{seq} PREVIEW screenshot TIMEOUT")
                except Exception as exc:
                    print(f"[preview] #{seq} PREVIEW screenshot failed: {exc}")

            print(f"[preview] #{seq} fetch_both done")
            return (scene, prog_b64, prev_b64)

        def on_result(result):
            self._fetching = False
            scene, prog_b64, prev_b64 = result
            print(f"[preview] #{seq} on_result: scene={scene}, prog_len={len(prog_b64)}, prev_len={len(prev_b64)}")
            if scene:
                self._cached_program_scene = scene
            if prog_b64:
                self._put_image(self.program_label, prog_b64)
            if prev_b64:
                self._put_image(self.preview_label, prev_b64)

        def on_error(exc):
            self._fetching = False
            print(f"[preview] #{seq} on_error: {exc}")

        run_in_thread(fetch_both, on_result, on_error)

    def _put_image(self, label: QLabel, b64: str) -> None:
        """解码 base64 JPEG 并显示到 QLabel。"""
        if not b64:
            print("[preview] _put_image: empty b64, skip")
            return
        try:
            print(f"[preview] _put_image: decoding {len(b64)} chars, first 40: {b64[:40]}")
            if isinstance(b64, str) and "," in b64:
                b64 = b64.split(",", 1)[1]
            raw = base64.b64decode(b64)
            img = QImage.fromData(raw)
            if img.isNull():
                print("[preview] _put_image: QImage is null")
                return
            label_size = label.size()
            w = max(label_size.width(), 1)
            h = max(label_size.height(), 1)
            scaled = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(QPixmap.fromImage(scaled))
            label.setText("")
            print(f"[preview] _put_image: displayed {img.width()}x{img.height()} → {w}x{h}")
        except Exception as exc:
            print(f"[preview] _put_image ERROR: {exc}")

    # ── T-Bar 回调 ────────────────────────────────────────────

    def _on_tbar(self, val: int) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        v = val / 100.0
        run_in_thread(lambda: ctrl.set_tbar_position(v))

    # ── 响应式布局 ────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        """处理面板大小改变事件，确保预览画面正确缩放。"""
        super().resizeEvent(event)
        # 可以在这里添加额外的处理逻辑
        # 例如：强制更新预览画面
        if self.app.ctrl is not None and self._timer.isActive():
            # 触发一次预览更新
            pass  # Qt 的布局系统会自动处理 QLabel 的大小
