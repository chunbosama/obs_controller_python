"""
gui/app.py  ——  主窗口类 OBSGui
负责：连接工具栏、主布局（左预览+右 Notebook）、状态栏、
      事件注册、轮询调度、全局线程安全
"""
from __future__ import annotations
import json
import os
import sys
import tkinter as tk
from tkinter import messagebox
from typing import Optional

# 持久化配置文件路径（与项目目录同级）
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "obs_config.json",
)

# 节目单占位提示文字（类级常量，供加载/保存时引用）
_RUNDOWN_PLACEHOLDER = "在此粘贴节目单…"

import ttkbootstrap as ttk_bs
from ttkbootstrap.constants import *

from obs_controller import OBSController

from .utils   import run_in_thread, format_timecode, FONT_LABEL, FONT_BOLD, CLR_GREEN, CLR_RED
from .preview   import PreviewPanel
from .log_window import LogWindow
from .tab_scene      import SceneTab
from .tab_audio      import AudioTab
from .tab_record     import RecordTab
from .tab_transition import TransitionTab
from .tab_filter     import FilterTab
from .tab_replay     import ReplayTab
from .tab_stats      import StatsTab


class StatusBar:
    """底部状态栏：连接 | 当前场景 | 录制时码 | 推流时码 | FPS | CPU"""

    def __init__(self, parent: tk.Widget):
        frame = ttk_bs.Frame(parent, bootstyle="dark")
        frame.pack(fill="x", side="bottom")

        ttk_bs.Separator(parent, orient="horizontal").pack(
            fill="x", side="bottom"
        )

        def _seg(text="", width=0, anchor="w", bootstyle="default"):
            v = tk.StringVar(value=text)
            lbl = ttk_bs.Label(frame, textvariable=v, width=width,
                               anchor=anchor, font=FONT_LABEL,
                               bootstyle=bootstyle, padding=(6, 2))
            lbl.pack(side="left")
            ttk_bs.Separator(frame, orient="vertical").pack(
                side="left", fill="y", pady=2
            )
            return v

        self._conn  = _seg("● 未连接",  18, bootstyle="danger")
        self._scene = _seg("场景: --",   22)
        self._rec   = _seg("REC --:--:--", 16, bootstyle="secondary")
        self._str   = _seg("STR --:--:--", 16, bootstyle="secondary")
        self._fps   = _seg("FPS --",     10, "center")
        self._cpu   = _seg("CPU --%",    10, "center")

    def set_connected(self, host: str, port: int) -> None:
        self._conn.set(f"● {host}:{port}")

    def set_disconnected(self) -> None:
        self._conn.set("● 未连接")

    def set_scene(self, name: str) -> None:
        self._scene.set(f"场景: {name[:18]}")

    def set_rec_tc(self, tc: str) -> None:
        self._rec.set(f"REC {tc}")

    def set_stream_tc(self, tc: str) -> None:
        self._str.set(f"STR {tc}")

    def set_fps(self, fps: float) -> None:
        self._fps.set(f"FPS {fps:.1f}")

    def set_cpu(self, cpu: float) -> None:
        self._cpu.set(f"CPU {cpu:.0f}%")


class OBSGui:
    """OBS 全功能控制台主窗口。"""

    def __init__(self):
        self.ctrl: Optional[OBSController] = None

        # ── 主窗口 ──
        self.root = ttk_bs.Window(
            title="OBS 全功能控制台",
            themename="darkly",
            size=(1280, 760),
            minsize=(960, 600),
        )
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_status_bar()
        self._build_main_area()
        self._load_config()            # 恢复上次的连接参数和节目单

        # 轮询 after-id 集合
        self._after_stats   : str | None = None
        self._after_timecode: str | None = None
        self._after_heartbeat: str | None = None

    # ══════════════════════════════════════════════════════════
    # 布局构建
    # ══════════════════════════════════════════════════════════

    def _build_toolbar(self, parent: tk.Widget) -> None:
        """右上角紧凑连接工具栏（嵌入 parent）。"""
        bar = ttk_bs.Frame(parent, padding=(4, 3))
        bar.pack(fill="x", side="top")

        # 状态指示灯
        self._led = tk.Canvas(bar, width=12, height=12,
                              highlightthickness=0, bg="#2b2b2b")
        self._led.pack(side="left", padx=(2, 4))
        self._led_circle = self._led.create_oval(2, 2, 10, 10, fill=CLR_RED)

        self._conn_label = ttk_bs.Label(bar, text="未连接",
                                        bootstyle="secondary", font=FONT_LABEL)
        self._conn_label.pack(side="left", padx=(0, 8))

        ttk_bs.Separator(bar, orient="vertical").pack(side="left", fill="y", pady=2, padx=4)

        ttk_bs.Label(bar, text="Host:", font=FONT_LABEL).pack(side="left")
        self._host_var = tk.StringVar(value="localhost")
        ttk_bs.Entry(bar, textvariable=self._host_var, width=12,
                     font=FONT_LABEL).pack(side="left", padx=(2, 6))

        ttk_bs.Label(bar, text="Port:", font=FONT_LABEL).pack(side="left")
        self._port_var = tk.StringVar(value="4455")
        ttk_bs.Entry(bar, textvariable=self._port_var, width=5,
                     font=FONT_LABEL).pack(side="left", padx=(2, 6))

        ttk_bs.Label(bar, text="Pwd:", font=FONT_LABEL).pack(side="left")
        self._pwd_var = tk.StringVar()
        ttk_bs.Entry(bar, textvariable=self._pwd_var, width=10,
                     show="*", font=FONT_LABEL).pack(side="left", padx=(2, 8))

        self._conn_btn = ttk_bs.Button(
            bar, text="连接", bootstyle="success-outline", width=5,
            command=self._on_connect,
        )
        self._conn_btn.pack(side="left", padx=2)

        self._disc_btn = ttk_bs.Button(
            bar, text="断开", bootstyle="danger-outline", width=5,
            command=self._on_disconnect, state="disabled",
        )
        self._disc_btn.pack(side="left", padx=2)

    def _build_status_bar(self) -> None:
        self.status_bar = StatusBar(self.root)

    def _build_main_area(self) -> None:
        """主区域：左侧预览+日志 + 右侧（工具栏 + Notebook + 统计面板）。"""
        paned = ttk_bs.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # ── 左：预览 + 日志 ──────────────────────────────────────
        left = ttk_bs.Frame(paned)
        paned.add(left, weight=0)

        # 上部：预览监视器（尽可能撑满）
        preview_frame = ttk_bs.Frame(left)
        preview_frame.pack(side="top", fill="both", expand=True,
                         padx=6, pady=(6, 2))
        self.preview_panel = PreviewPanel(preview_frame, self)

        # 下部：日志 + 节目单（水平左右可拖动分割）
        bottom_paned = ttk_bs.Panedwindow(left, orient="horizontal")
        bottom_paned.pack(side="bottom", fill="x", padx=6, pady=(2, 6))

        # 左半：日志窗口
        log_frame = ttk_bs.Frame(bottom_paned)
        bottom_paned.add(log_frame, weight=1)
        self.log_window = LogWindow(log_frame, self)
        self.log_window.frame.pack(fill="both", expand=True)
        log_frame.configure(height=75)
        log_frame.pack_propagate(False)

        # 右半：节目单文本框
        rundown_frame = ttk_bs.Labelframe(
            bottom_paned, text=" 📋 节目单 ", padding=(2, 2)
        )
        bottom_paned.add(rundown_frame, weight=1)
        rundown_frame.configure(height=75)

        rd_container = ttk_bs.Frame(rundown_frame)
        rd_container.pack(fill="both", expand=True)

        self.rundown_text = tk.Text(
            rd_container,
            wrap="word",
            font=("Segoe UI", 9),
            bg="#1c1c2e",
            fg="#e0e0ff",
            insertbackground="#e0e0ff",
            relief="flat",
            borderwidth=0,
            padx=6, pady=4,
            highlightthickness=0,
        )
        rd_sb = ttk_bs.Scrollbar(
            rd_container, orient="vertical", command=self.rundown_text.yview
        )
        self.rundown_text.configure(yscrollcommand=rd_sb.set)
        rd_sb.pack(side="right", fill="y")
        self.rundown_text.pack(side="left", fill="both", expand=True)

        # 占位提示（第一次获得焦点时自动清除）
        self.rundown_text.insert("1.0", _RUNDOWN_PLACEHOLDER)
        self.rundown_text.tag_configure("placeholder", foreground="#555577")
        self.rundown_text.tag_add("placeholder", "1.0", "end")

        def _on_focus_in(e):
            if self.rundown_text.get("1.0", "end-1c") == _RUNDOWN_PLACEHOLDER:
                self.rundown_text.delete("1.0", "end")
                self.rundown_text.tag_remove("placeholder", "1.0", "end")

        def _on_focus_out(e):
            if not self.rundown_text.get("1.0", "end-1c").strip():
                self.rundown_text.insert("1.0", _RUNDOWN_PLACEHOLDER)
                self.rundown_text.tag_add("placeholder", "1.0", "end")

        self.rundown_text.bind("<FocusIn>",  _on_focus_in)
        self.rundown_text.bind("<FocusOut>", _on_focus_out)

        # ── 右：工具栏 + Notebook + 统计面板 ─────────────────────
        right = ttk_bs.Frame(paned)
        paned.add(right, weight=1)

        # 顶部：紧凑连接工具栏
        toolbar_sep_frame = ttk_bs.Frame(right)
        toolbar_sep_frame.pack(fill="x", side="top")
        self._build_toolbar(toolbar_sep_frame)
        ttk_bs.Separator(right, orient="horizontal").pack(fill="x", side="top")

        # 底部：统计迷你面板（先 pack bottom，保证 Notebook 在中间撑满）
        stats_frame = ttk_bs.Frame(right)
        stats_frame.pack(fill="x", side="bottom", padx=6, pady=(2, 4))
        ttk_bs.Separator(right, orient="horizontal").pack(fill="x", side="bottom")

        # 中间：Notebook（功能标签页，不含统计）
        self.notebook = ttk_bs.Notebook(right, bootstyle="dark")
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(4, 2))

        self.scene_tab      = SceneTab(self.notebook, self)
        self.audio_tab      = AudioTab(self.notebook, self)
        self.record_tab     = RecordTab(self.notebook, self)
        self.transition_tab = TransitionTab(self.notebook, self)
        self.filter_tab     = FilterTab(self.notebook, self)
        self.replay_tab     = ReplayTab(self.notebook, self)

        # 统计面板嵌入右下角（不作为 Notebook Tab）
        self.stats_tab = StatsTab(stats_frame, self)

    # ══════════════════════════════════════════════════════════
    # 连接 / 断开
    # ══════════════════════════════════════════════════════════

    def _on_connect(self) -> None:
        host = self._host_var.get().strip() or "localhost"
        try:
            port = int(self._port_var.get().strip())
        except ValueError:
            port = 4455
        pwd = self._pwd_var.get().strip() or None

        self._conn_label.config(text="连接中…")
        self._conn_btn.config(state="disabled")

        def do_connect():
            # OBSController.__init__ 在创建时自动建立连接（ReqClient 构造即连接）
            pwd_str = pwd if pwd else ""
            ctrl = OBSController(host=host, port=port, password=pwd_str)
            # 尝试调用一个简单请求验证连接是否成功
            ctrl.get_version()
            return ctrl

        run_in_thread(
            self.root, do_connect,
            ok_cb=lambda ctrl: self._after_connect(ctrl, host, port),
            err_cb=self._on_connect_error,
        )

    def _after_connect(self, ctrl: OBSController, host: str, port: int) -> None:
        self.ctrl = ctrl
        self._conn_btn.config(state="disabled")
        self._disc_btn.config(state="normal")
        self._conn_label.config(text=f"已连接 {host}:{port}")
        self._led.itemconfig(self._led_circle, fill=CLR_GREEN)
        self.status_bar.set_connected(host, port)

        self.log(f"已连接到 OBS {host}:{port}", "SUCCESS")

        # 启动预览循环
        self.preview_panel.start_loop()

        # 注册事件
        self._register_events()

        # 刷新所有标签页
        self.refresh_all()

        # 启动轮询
        self._start_polls()

    def _on_connect_error(self, exc: Exception) -> None:
        self._conn_btn.config(state="normal")
        self._conn_label.config(text="连接失败")
        self.log(f"连接失败: {exc}", "ERROR")
        messagebox.showerror("连接失败", str(exc))

    def _on_disconnect(self) -> None:
        self._stop_polls()
        self.preview_panel.stop_loop()

        if self.ctrl:
            try:
                self.ctrl.close()
            except Exception:
                pass
            self.ctrl = None

        self._conn_btn.config(state="normal")
        self._disc_btn.config(state="disabled")
        self._conn_label.config(text="未连接")
        self._led.itemconfig(self._led_circle, fill=CLR_RED)
        self.status_bar.set_disconnected()
        self.log("已断开 OBS 连接", "WARNING")

    # ══════════════════════════════════════════════════════════
    # 事件注册
    # ══════════════════════════════════════════════════════════

    def _register_events(self) -> None:
        if self.ctrl is None:
            return

        def on_scene_changed(data):
            name = (data.get("sceneName") if isinstance(data, dict)
                    else getattr(data, "scene_name", ""))
            if name:
                self.root.after(0, lambda: self.status_bar.set_scene(name))
                self.root.after(0, lambda: self.scene_tab.refresh())

        def on_scene_created(data):
            # 场景创建后立即刷新列表（无论来自 GUI 还是 OBS 直接操作）
            self.root.after(0, self.scene_tab.refresh)

        def on_scene_removed(data):
            # 场景删除后立即刷新列表
            self.root.after(0, self.scene_tab.refresh)

        def on_scene_name_changed(data):
            # 场景重命名后立即刷新列表
            self.root.after(0, self.scene_tab.refresh)

        def on_record_state(data):
            state = (data.get("outputState") if isinstance(data, dict)
                     else getattr(data, "output_state", ""))
            active  = "STARTED" in state.upper()
            paused  = "PAUSED"  in state.upper()
            self.root.after(0, lambda: self.record_tab.set_recording_state(active, paused))

        def on_stream_state(data):
            state = (data.get("outputState") if isinstance(data, dict)
                     else getattr(data, "output_state", ""))
            active = "STARTED" in state.upper()
            self.root.after(0, lambda: self.record_tab.set_streaming_state(active))

        def on_input_mute(data):
            name   = (data.get("inputName") if isinstance(data, dict)
                      else getattr(data, "input_name", ""))
            muted  = (data.get("inputMuted") if isinstance(data, dict)
                      else getattr(data, "input_muted", False))
            if name:
                self.root.after(0, lambda: self.audio_tab.update_mute(name, muted))

        try:
            self.ctrl.register_callback("CurrentProgramSceneChanged", on_scene_changed)
            self.ctrl.register_callback("SceneCreated",               on_scene_created)
            self.ctrl.register_callback("SceneRemoved",               on_scene_removed)
            self.ctrl.register_callback("SceneNameChanged",           on_scene_name_changed)
            self.ctrl.register_callback("RecordStateChanged",         on_record_state)
            self.ctrl.register_callback("StreamStateChanged",         on_stream_state)
            self.ctrl.register_callback("InputMuteStateChanged",      on_input_mute)
        except Exception:
            pass  # 部分版本 API 不支持

    # ══════════════════════════════════════════════════════════
    # 轮询
    # ══════════════════════════════════════════════════════════

    def _start_polls(self) -> None:
        self._poll_stats()
        self._poll_timecode()
        self._poll_heartbeat()

    def _stop_polls(self) -> None:
        for attr in ("_after_stats", "_after_timecode", "_after_heartbeat"):
            aid = getattr(self, attr, None)
            if aid:
                self.root.after_cancel(aid)
                setattr(self, attr, None)

    def _poll_stats(self) -> None:
        if self.ctrl is None:
            return

        def fetch():
            return self.ctrl.get_stats()

        def update(stats):
            def _g(obj, *keys):
                for k in keys:
                    v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
                    if v is not None:
                        return v
                return None

            fps = _g(stats, "activeFps", "active_fps")
            cpu = _g(stats, "cpuUsage",  "cpu_usage")
            if fps is not None:
                self.status_bar.set_fps(fps)
            if cpu is not None:
                self.status_bar.set_cpu(cpu)
            self.stats_tab._on_stats(stats)

        run_in_thread(self.root, fetch, update)
        self._after_stats = self.root.after(2000, self._poll_stats)

    def _poll_timecode(self) -> None:
        if self.ctrl is None:
            return

        def fetch():
            rec_tc    = ""
            stream_tc = ""
            try:
                r = self.ctrl.get_record_status()
                ms = r.get("outputTimecode") if isinstance(r, dict) else getattr(r, "output_timecode", None)
                if ms:
                    rec_tc = ms
            except Exception:
                pass
            try:
                s = self.ctrl.get_stream_status()
                ms = s.get("outputTimecode") if isinstance(s, dict) else getattr(s, "output_timecode", None)
                if ms:
                    stream_tc = ms
            except Exception:
                pass
            return rec_tc, stream_tc

        def update(pair):
            rec_tc, stream_tc = pair
            if rec_tc:
                self.status_bar.set_rec_tc(rec_tc)
                self.record_tab.update_rec_timecode(rec_tc)
            if stream_tc:
                self.status_bar.set_stream_tc(stream_tc)
                self.record_tab.update_stream_timecode(stream_tc)

        run_in_thread(self.root, fetch, update)
        self._after_timecode = self.root.after(1000, self._poll_timecode)

    def _poll_heartbeat(self) -> None:
        if self.ctrl is None:
            return

        def check():
            try:
                self.ctrl.get_stats()
                return True
            except Exception:
                return False

        def on_result(ok: bool):
            if not ok:
                self._led.itemconfig(self._led_circle, fill="#888888")
                self.log("心跳检测失败，OBS 可能已断开", "WARNING")

        run_in_thread(self.root, check, on_result)
        self._after_heartbeat = self.root.after(5000, self._poll_heartbeat)

    # ══════════════════════════════════════════════════════════
    # 全局刷新
    # ══════════════════════════════════════════════════════════

    def refresh_all(self) -> None:
        """连接后刷新所有标签页数据。"""
        self.scene_tab.refresh()
        self.audio_tab.refresh()
        self.transition_tab.refresh()
        self.filter_tab.refresh()
        self.replay_tab.refresh()
        self.stats_tab.refresh()

        # 更新当前场景
        run_in_thread(
            self.root,
            self.ctrl.get_current_scene,
            lambda s: self.status_bar.set_scene(s),
        )

    # ══════════════════════════════════════════════════════════
    # 预览面板回调（供 PreviewPanel 调用）
    # ══════════════════════════════════════════════════════════

    def do_cut(self) -> None:
        if self.ctrl is None:
            return
        run_in_thread(self.root, self.ctrl.trigger_studio_mode_transition)

    def do_fade(self) -> None:
        if self.ctrl is None:
            return
        run_in_thread(
            self.root,
            lambda: (self.ctrl.set_current_transition("Fade"),
                     self.ctrl.set_transition_duration(500)),
            lambda _: run_in_thread(
                self.root, self.ctrl.trigger_studio_mode_transition
            ),
        )

    def do_fade_to_black(self) -> None:
        """淡出到黑场 / 从黑场恢复（toggle 式）。"""
        if self.ctrl is None:
            return
        ctrl = self.ctrl
        self.log("黑场切换…", "INFO")

        def toggle():
            cur = ctrl.get_current_scene()
            if cur == ctrl.BLACK_SCENE_NAME:
                restored = ctrl.fade_from_black()
                return ("restore", restored)
            else:
                saved = ctrl.fade_to_black()
                return ("black", saved)

        def update(result):
            action, scene = result
            if action == "black":
                self.log(f"已淡出到黑场（原场景: {scene}）", "SUCCESS")
            else:
                self.log(f"已从黑场恢复 → {scene}", "SUCCESS")

        def on_error(exc):
            self.log(f"黑场切换失败: {exc}", "ERROR")

        run_in_thread(self.root, toggle, update, err_cb=on_error)

    def preview_scene(self, scene_name: str) -> None:
        """场景列表选中时，在 PREVIEW 画布上显示该场景的截图（不切换节目场景）。"""
        if self.ctrl is None:
            return
        self.preview_panel.preview_one_shot(scene_name)

    def log(self, message: str, level: str = "INFO") -> None:
        """写入左下角日志窗口（线程安全）。"""
        self.log_window.log(message, level)

    # ══════════════════════════════════════════════════════════
    # 持久化（记忆功能）
    # ══════════════════════════════════════════════════════════

    def _load_config(self) -> None:
        """启动时从 obs_config.json 恢复连接参数和节目单内容。"""
        try:
            if not os.path.exists(_CONFIG_PATH):
                return
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return

        # 恢复连接参数
        if cfg.get("host"):
            self._host_var.set(cfg["host"])
        if cfg.get("port"):
            self._port_var.set(str(cfg["port"]))
        if cfg.get("password"):
            self._pwd_var.set(cfg["password"])

        # 恢复节目单内容（非空时覆盖占位文字）
        rundown = cfg.get("rundown", "")
        if rundown.strip():
            current = self.rundown_text.get("1.0", "end-1c")
            if current == _RUNDOWN_PLACEHOLDER:
                self.rundown_text.delete("1.0", "end")
                self.rundown_text.tag_remove("placeholder", "1.0", "end")
            self.rundown_text.insert("1.0", rundown)

    def _get_rundown_text(self) -> str:
        """获取节目单实际内容（占位文字当作空）。"""
        text = self.rundown_text.get("1.0", "end-1c")
        if text == _RUNDOWN_PLACEHOLDER:
            return ""
        return text

    def _save_config(self) -> None:
        """退出时将连接参数和节目单写入 obs_config.json。"""
        config = {
            "host": self._host_var.get().strip(),
            "port": self._port_var.get().strip(),
            "password": self._pwd_var.get().strip(),
            "rundown": self._get_rundown_text(),
        }
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════
    # 关闭处理
    # ══════════════════════════════════════════════════════════

    def _on_close(self) -> None:
        self._save_config()           # 记住本次使用的连接参数和节目单
        self._on_disconnect()
        self.root.destroy()

    # ══════════════════════════════════════════════════════════
    # 启动
    # ══════════════════════════════════════════════════════════

    def run(self) -> None:
        self.root.mainloop()
