"""
gui/preview.py  ——  双画面预览区（PROGRAM / PREVIEW）+ T-Bar 转场控制
"""
from __future__ import annotations
import io
import base64
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

import ttkbootstrap as ttk_bs
from PIL import Image, ImageTk

from .utils import PREVIEW_W, PREVIEW_H, CLR_BG, CLR_PANEL, CLR_RED, CLR_GREEN, FONT_BOLD, FONT_TITLE

if TYPE_CHECKING:
    from .app import OBSGui


class PreviewPanel:
    """左侧双画面预览区（PROGRAM + PREVIEW）及转场快捷按钮。"""

    PLACEHOLDER_COLOR = "#1a1a1a"

    def __init__(self, parent: tk.Widget, app: "OBSGui"):
        self.app = app
        self.root = app.root
        self._program_photo: ImageTk.PhotoImage | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_locked_scene: str | None = None

        self._build(parent)
        self._after_id: str | None = None

    # ── 构建 UI ──────────────────────────────────────────────

    def _build(self, parent: tk.Widget) -> None:
        frame = ttk_bs.Labelframe(parent, text=" 📺 预览监视器 ")
        frame.pack(fill="both", expand=True, padx=(6, 3), pady=6)

        # 上方：两个 Canvas 并排
        canvas_row = ttk_bs.Frame(frame)
        canvas_row.pack(fill="x")

        self.preview_canvas = self._make_canvas(
            canvas_row, "🟢  PREVIEW", CLR_GREEN
        )
        ttk_bs.Separator(canvas_row, orient="vertical").pack(
            side="left", fill="y", padx=4
        )
        self.program_canvas = self._make_canvas(
            canvas_row, "🔴  PROGRAM", CLR_RED
        )

        # 画布占位文字
        self._draw_placeholder(self.program_canvas, "PROGRAM")
        self._draw_placeholder(self.preview_canvas, "PREVIEW")

        # 下方：转场控制行
        ctrl = ttk_bs.Frame(frame)
        ctrl.pack(fill="x", pady=(6, 0))

        ttk_bs.Button(
            ctrl, text="CUT", bootstyle="danger-outline", width=6,
            command=self.app.do_cut
        ).pack(side="left", padx=4)

        ttk_bs.Button(
            ctrl, text="FADE", bootstyle="info-outline", width=6,
            command=self.app.do_fade
        ).pack(side="left", padx=2)

        ttk_bs.Button(
            ctrl, text="🌑 黑场", bootstyle="dark-outline", width=8,
            command=self.app.do_fade_to_black
        ).pack(side="left", padx=2)

        ttk_bs.Label(ctrl, text="T-Bar:").pack(side="left", padx=(10, 4))
        self.tbar_var = tk.DoubleVar(value=0.0)
        self.tbar_scale = ttk_bs.Scale(
            ctrl, from_=0.0, to=1.0, orient="horizontal",
            variable=self.tbar_var, length=180,
            command=self._on_tbar
        )
        self.tbar_scale.pack(side="left", padx=4)

        ttk_bs.Button(
            ctrl, text="刷新列表", bootstyle="secondary-outline",
            command=self.app.refresh_all
        ).pack(side="right", padx=4)

    def _make_canvas(
        self, parent: tk.Widget, label: str, border_color: str
    ) -> tk.Canvas:
        col = ttk_bs.Frame(parent)
        col.pack(side="left")

        ttk_bs.Label(col, text=label, font=FONT_BOLD).pack()
        cv = tk.Canvas(
            col,
            width=PREVIEW_W, height=PREVIEW_H,
            bg=self.PLACEHOLDER_COLOR,
            highlightthickness=2,
            highlightbackground=border_color,
        )
        cv.pack()
        return cv

    def _draw_placeholder(self, canvas: tk.Canvas, text: str) -> None:
        canvas.create_text(
            PREVIEW_W // 2, PREVIEW_H // 2,
            text=f"{text}\n（未连接）",
            fill="#555555",
            font=FONT_TITLE,
            tags="placeholder",
            justify="center",
        )

    # ── 预览更新循环 ─────────────────────────────────────────

    def start_loop(self) -> None:
        """连接成功后调用，启动 500 ms 刷新循环。"""
        # 清除占位符文字，显示"连接中…"
        for cv in (self.program_canvas, self.preview_canvas):
            cv.delete("all")
            cv.create_text(
                PREVIEW_W // 2, PREVIEW_H // 2,
                text="连接中…", fill="#666666", font=FONT_TITLE,
                tags="status",
            )
        self._error_count = 0
        self._schedule()

    def stop_loop(self) -> None:
        """断开连接时停止循环。"""
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._preview_locked_scene = None
        self._draw_placeholder(self.program_canvas, "PROGRAM")
        self._draw_placeholder(self.preview_canvas, "PREVIEW")

    def preview_one_shot(self, scene_name: str) -> None:
        """在 PREVIEW 画布上显示指定场景的截图（不切换节目场景）。
        立即在后台线程获取截图并显示；同时设置锁定标志，后续 500ms 循环
        将一直使用此场景作为 PREVIEW 画布的截图源，直到用户点击另一个场景。
        """
        ctrl = self.app.ctrl
        if ctrl is None:
            self.app.log(f"预览失败: 未连接到 OBS", "WARNING")
            return

        self._preview_locked_scene = scene_name
        self.app.log(f"正在预览场景: {scene_name}", "INFO")

        import threading
        import traceback as _tb

        def fetch():
            try:
                b64 = ctrl.get_source_screenshot(
                    source_name=scene_name,
                    img_format="jpg", width=PREVIEW_W, height=PREVIEW_H,
                    quality=60,
                )
                self.app.log(f"场景 [{scene_name}] 截图成功", "DEBUG")
                self.root.after(0, lambda b=b64: self._put_image(
                    self.preview_canvas, b, "preview"
                ))
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"场景 [{scene_name}] 截图失败: {err_msg}", "ERROR")
                _tb.print_exc()
                self.root.after(0, lambda m=err_msg: self._show_error(
                    self.preview_canvas, "PREVIEW", m
                ))

        threading.Thread(target=fetch, daemon=True).start()

    def _schedule(self) -> None:
        self._after_id = self.root.after(500, self._update_frames)

    def _update_frames(self) -> None:
        """每 500 ms 获取一次截图并更新两块画布（在子线程中执行 API 调用）。"""
        ctrl = self.app.ctrl
        if ctrl is None:
            self._schedule()
            return

        import threading
        import traceback as _tb

        def fetch_and_draw():
            # PREVIEW 锁定场景（由 preview_one_shot 设置，持久锁定直到用户点击其他场景）
            override = self._preview_locked_scene
            if override:
                self.app.log(f"预览覆盖: 使用场景 [{override}]", "DEBUG")

            # PROGRAM 画面（当前输出场景截图）
            try:
                cur_scene = ctrl.get_current_scene()
                self.app.log(f"PROGRAM 截图: 场景=[{cur_scene}]", "DEBUG")
                prog_b64 = ctrl.get_source_screenshot(
                    source_name=cur_scene,
                    img_format="jpg", width=PREVIEW_W, height=PREVIEW_H,
                    quality=60,
                )
                self.root.after(0, lambda b=prog_b64: self._put_image(
                    self.program_canvas, b, "program"
                ))
            except Exception as e:
                err = str(e)
                self.app.log(f"PROGRAM 截图失败: {err}", "ERROR")
                _tb.print_exc()
                self.root.after(0, lambda m=err: self._show_error(
                    self.program_canvas, "PROGRAM", m
                ))

            # PREVIEW 画面（override > Studio 预览 > 当前场景）
            try:
                if override:
                    prev_scene = override
                else:
                    prev_scene = (ctrl.get_current_preview_scene()
                                or ctrl.get_current_scene())
                self.app.log(f"PREVIEW 截图: 场景=[{prev_scene}]", "DEBUG")
                prev_b64 = ctrl.get_source_screenshot(
                    source_name=prev_scene,
                    img_format="jpg", width=PREVIEW_W, height=PREVIEW_H,
                    quality=60,
                )
                self.root.after(0, lambda b=prev_b64: self._put_image(
                    self.preview_canvas, b, "preview"
                ))
            except Exception as e:
                err = str(e)
                self.app.log(f"PREVIEW 截图失败: {err}", "ERROR")
                _tb.print_exc()
                self.root.after(0, lambda m=err: self._show_error(
                    self.preview_canvas, "PREVIEW", m
                ))

        threading.Thread(target=fetch_and_draw, daemon=True).start()
        self._schedule()

    def _show_error(self, canvas: tk.Canvas, label: str, msg: str) -> None:
        """在画布上显示错误信息（替代静默失败）。"""
        canvas.delete("all")
        short = msg[:60] + ("…" if len(msg) > 60 else "")
        canvas.create_text(
            PREVIEW_W // 2, PREVIEW_H // 2 - 10,
            text=f"{label}\n错误: {short}",
            fill="#e74c3c", font=("Segoe UI", 8), tags="error",
            justify="center", width=PREVIEW_W - 20,
        )

    def _put_image(
        self, canvas: tk.Canvas, b64: str, which: str
    ) -> None:
        """解码 base64 JPEG 并显示到 Canvas（主线程调用）。"""
        import traceback as _tb
        try:
            # 去掉 data-URI 前缀（如有）
            if isinstance(b64, str) and "," in b64:
                b64 = b64.split(",", 1)[1]
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw)).resize(
                (PREVIEW_W, PREVIEW_H), Image.BILINEAR
            )
            photo = ImageTk.PhotoImage(img)
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=photo)
            # 必须保持引用，防止 GC 回收
            if which == "program":
                self._program_photo = photo
            else:
                self._preview_photo = photo
        except Exception as e:
            _tb.print_exc()
            self._show_error(canvas, which.upper(), str(e))

    # ── T-Bar 回调 ────────────────────────────────────────────

    def _on_tbar(self, val: str) -> None:
        from .utils import run_in_thread
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        v = float(val)
        run_in_thread(
            self.root,
            lambda: ctrl.set_tbar_position(v),
        )
