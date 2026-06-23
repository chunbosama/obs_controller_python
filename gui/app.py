"""
gui/app.py  ——  主窗口类 OBSGui（PyQt5 版）
负责：连接工具栏、主布局（左预览+右 TabWidget）、状态栏、
      事件注册、轮询调度、全局线程安全
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QLabel, QLineEdit,
    QPushButton, QStatusBar, QMessageBox, QFrame,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPalette

from obs_controller import OBSController

from .utils import (
    run_in_thread, DARK_STYLE, CLR_GREEN, CLR_RED,
)
from .preview import PreviewPanel
from .log_window import LogWindow
from .tab_scene import SceneTab
from .tab_audio import AudioTab
from .tab_record import RecordTab
from .tab_transition import TransitionTab
from .tab_filter import FilterTab
from .tab_replay import ReplayTab
from .tab_stats import StatsTab


class OBSGui(QMainWindow):
    """OBS 全功能控制台主窗口。"""

    def __init__(self):
        super().__init__()
        self.ctrl: Optional[OBSController] = None

        self.setWindowTitle("OBS 全功能控制台")
        self.setMinimumSize(960, 600)
        self.resize(1280, 760)
        self.setStyleSheet(DARK_STYLE)

        self._build_status_bar()
        self._build_main_area()

        # 轮询定时器
        self._timer_stats = QTimer(self)
        self._timer_stats.timeout.connect(self._poll_stats)
        self._timer_timecode = QTimer(self)
        self._timer_timecode.timeout.connect(self._poll_timecode)
        self._timer_heartbeat = QTimer(self)
        self._timer_heartbeat.timeout.connect(self._poll_heartbeat)

    # ══════════════════════════════════════════════════════════
    # 布局构建
    # ══════════════════════════════════════════════════════════

    def _build_toolbar(self) -> QWidget:
        """连接工具栏。"""
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet("QWidget { background-color: #161624; border-bottom: 1px solid #3a3a5c; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(6)

        # 状态指示灯
        self._led = QLabel("●")
        self._led.setStyleSheet(f"color: {CLR_RED}; font-size: 13pt; background: transparent;")
        layout.addWidget(self._led)

        self._conn_label = QLabel("未连接")
        self._conn_label.setStyleSheet("color: #55556a; font-size: 9pt; background: transparent;")
        self._conn_label.setFixedWidth(140)
        layout.addWidget(self._conn_label)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #3a3a5c; background: transparent;")
        layout.addWidget(sep)

        lbl_h = QLabel("Host:")
        lbl_h.setStyleSheet("color: #8888a8; background: transparent;")
        layout.addWidget(lbl_h)
        self._host_edit = QLineEdit("localhost")
        self._host_edit.setFixedWidth(110)
        layout.addWidget(self._host_edit)

        lbl_p = QLabel("Port:")
        lbl_p.setStyleSheet("color: #8888a8; background: transparent;")
        layout.addWidget(lbl_p)
        self._port_edit = QLineEdit("4455")
        self._port_edit.setFixedWidth(52)
        layout.addWidget(self._port_edit)

        lbl_pw = QLabel("密码:")
        lbl_pw.setStyleSheet("color: #8888a8; background: transparent;")
        layout.addWidget(lbl_pw)
        self._pwd_edit = QLineEdit()
        self._pwd_edit.setFixedWidth(96)
        self._pwd_edit.setEchoMode(QLineEdit.Password)
        self._pwd_edit.setPlaceholderText("（留空）")
        layout.addWidget(self._pwd_edit)

        self._conn_btn = QPushButton("连接")
        self._conn_btn.setProperty("success", True)
        self._conn_btn.setFixedWidth(76)
        self._conn_btn.clicked.connect(self._on_connect)
        layout.addWidget(self._conn_btn)

        self._disc_btn = QPushButton("断开")
        self._disc_btn.setProperty("danger", True)
        self._disc_btn.setFixedWidth(60)
        self._disc_btn.setEnabled(False)
        self._disc_btn.clicked.connect(self._on_disconnect)
        layout.addWidget(self._disc_btn)

        layout.addStretch()
        return bar

    def _build_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self._sb_conn = QLabel("● 未连接")
        self._sb_conn.setStyleSheet(f"color: {CLR_RED};")
        self.status_bar.addWidget(self._sb_conn)

        self._sb_scene = QLabel("场景: --")
        self.status_bar.addWidget(self._sb_scene)

        self._sb_rec = QLabel("REC --:--:--")
        self.status_bar.addWidget(self._sb_rec)

        self._sb_str = QLabel("STR --:--:--")
        self.status_bar.addWidget(self._sb_str)

        self._sb_fps = QLabel("FPS --")
        self.status_bar.addPermanentWidget(self._sb_fps)

        self._sb_cpu = QLabel("CPU --%")
        self.status_bar.addPermanentWidget(self._sb_cpu)

    def _build_main_area(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        main_layout.addWidget(self._build_toolbar())

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #444444;")
        main_layout.addWidget(sep)

        # 主分割器
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # ── 左：预览 + 日志 ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 3, 6)

        self.preview_panel = PreviewPanel(left, self)
        left_layout.addWidget(self.preview_panel, stretch=1)

        self.log_window = LogWindow(left, self)
        left_layout.addWidget(self.log_window)

        splitter.addWidget(left)

        # ── 右：TabWidget + 统计面板 ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(3, 6, 6, 6)

        # TabWidget
        self.tab_widget = QTabWidget()
        right_layout.addWidget(self.tab_widget, stretch=1)

        self.scene_tab = SceneTab(self.tab_widget, self)
        self.tab_widget.addTab(self.scene_tab, "🎬 场景")

        self.audio_tab = AudioTab(self.tab_widget, self)
        self.tab_widget.addTab(self.audio_tab, "🎚 音频")

        self.record_tab = RecordTab(self.tab_widget, self)
        self.tab_widget.addTab(self.record_tab, "⏺ 录制/推流")

        self.transition_tab = TransitionTab(self.tab_widget, self)
        self.tab_widget.addTab(self.transition_tab, "🎞 转场")

        self.filter_tab = FilterTab(self.tab_widget, self)
        self.tab_widget.addTab(self.filter_tab, "✨ 滤镜")

        self.replay_tab = ReplayTab(self.tab_widget, self)
        self.tab_widget.addTab(self.replay_tab, "📼 回放/截图")

        # 统计面板
        self.stats_tab = StatsTab(right, self)
        right_layout.addWidget(self.stats_tab)

        splitter.addWidget(right)
        # 使用比例而不是固定值，使 splitter 自适应窗口大小
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        # 设置初始比例为 1:1.5
        total_width = self.width()
        splitter.setSizes([int(total_width * 0.4), int(total_width * 0.6)])

    # ══════════════════════════════════════════════════════════
    # 状态栏方法
    # ══════════════════════════════════════════════════════════

    def set_connected(self, host: str, port: int) -> None:
        self._sb_conn.setText(f"● {host}:{port}")
        self._sb_conn.setStyleSheet(f"color: {CLR_GREEN};")

    def set_disconnected(self) -> None:
        self._sb_conn.setText("● 未连接")
        self._sb_conn.setStyleSheet(f"color: {CLR_RED};")

    def set_scene(self, name: str) -> None:
        self._sb_scene.setText(f"场景: {name[:18]}")

    def set_rec_tc(self, tc: str) -> None:
        self._sb_rec.setText(f"REC {tc}")

    def set_stream_tc(self, tc: str) -> None:
        self._sb_str.setText(f"STR {tc}")

    def set_fps(self, fps: float) -> None:
        self._sb_fps.setText(f"FPS {fps:.1f}")

    def set_cpu(self, cpu: float) -> None:
        self._sb_cpu.setText(f"CPU {cpu:.0f}%")

    # ══════════════════════════════════════════════════════════
    # 连接 / 断开
    # ══════════════════════════════════════════════════════════

    def _on_connect(self) -> None:
        host = self._host_edit.text().strip() or "localhost"
        try:
            port = int(self._port_edit.text().strip())
        except ValueError:
            port = 4455
        pwd = self._pwd_edit.text().strip() or None

        self._conn_label.setText("连接中…")
        self._conn_btn.setEnabled(False)

        def do_connect():
            pwd_str = pwd if pwd else ""
            ctrl = OBSController(host=host, port=port, password=pwd_str)
            ctrl.get_version()
            return ctrl

        run_in_thread(
            do_connect,
            lambda ctrl: self._after_connect(ctrl, host, port),
            self._on_connect_error,
        )

    def _after_connect(self, ctrl: OBSController, host: str, port: int) -> None:
        self.ctrl = ctrl
        self._conn_btn.setEnabled(False)
        self._disc_btn.setEnabled(True)
        self._conn_label.setText(f"已连接 {host}:{port}")
        self._conn_label.setStyleSheet("color: #00bc8c;")
        self._led.setStyleSheet(f"color: {CLR_GREEN}; font-size: 14pt;")
        self.set_connected(host, port)

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
        self._conn_btn.setEnabled(True)
        self._conn_label.setText("连接失败")
        self._conn_label.setStyleSheet("color: #e74c3c;")
        self.log(f"连接失败: {exc}", "ERROR")

        msg = str(exc)
        hint = ""
        if "failed to identify" in msg.lower():
            hint = ("\n\n请检查：\n"
                    "1. OBS 是否已启动并启用 WebSocket 服务器\n"
                    "2. 主机地址和端口是否正确（默认 localhost:4455）\n"
                    "3. 密码是否正确（OBS → 工具 → WebSocket 服务器设置）")
        elif "code 604" in msg.lower():
            hint = ""  # 已内部处理，仅提示
        QMessageBox.critical(self, "连接失败", msg + hint)

    def _on_disconnect(self) -> None:
        self._stop_polls()
        self.preview_panel.stop_loop()

        if self.ctrl:
            try:
                self.ctrl.close()
            except Exception:
                pass
            self.ctrl = None

        self._conn_btn.setEnabled(True)
        self._disc_btn.setEnabled(False)
        self._conn_label.setText("未连接")
        self._conn_label.setStyleSheet("color: #aaaaaa;")
        self._led.setStyleSheet(f"color: {CLR_RED}; font-size: 14pt;")
        self.set_disconnected()
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
                self.set_scene(name)
                # 更新预览面板的场景缓存，减少下一次刷新的额外请求
                self.preview_panel._cached_program_scene = name
                self.scene_tab.refresh()
                # 场景切换时立即刷新预览画面
                self.preview_panel.trigger_refresh()6

        def on_scene_created(data):
            self.scene_tab.refresh()

        def on_scene_removed(data):
            self.scene_tab.refresh()

        def on_scene_name_changed(data):
            self.scene_tab.refresh()

        def on_record_state(data):
            state = (data.get("outputState") if isinstance(data, dict)
                     else getattr(data, "output_state", ""))
            active = "STARTED" in state.upper()
            paused = "PAUSED" in state.upper()
            self.record_tab.set_recording_state(active, paused)

        def on_stream_state(data):
            state = (data.get("outputState") if isinstance(data, dict)
                     else getattr(data, "output_state", ""))
            active = "STARTED" in state.upper()
            self.record_tab.set_streaming_state(active)

        def on_input_mute(data):
            name = (data.get("inputName") if isinstance(data, dict)
                    else getattr(data, "input_name", ""))
            muted = (data.get("inputMuted") if isinstance(data, dict)
                     else getattr(data, "input_muted", False))
            if name:
                self.audio_tab.update_mute(name, muted)

        try:
            self.ctrl.register_callback("CurrentProgramSceneChanged", on_scene_changed)
            self.ctrl.register_callback("SceneCreated", on_scene_created)
            self.ctrl.register_callback("SceneRemoved", on_scene_removed)
            self.ctrl.register_callback("SceneNameChanged", on_scene_name_changed)
            self.ctrl.register_callback("RecordStateChanged", on_record_state)
            self.ctrl.register_callback("StreamStateChanged", on_stream_state)
            self.ctrl.register_callback("InputMuteStateChanged", on_input_mute)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════
    # 轮询
    # ══════════════════════════════════════════════════════════

    def _start_polls(self) -> None:
        self._poll_stats()
        self._poll_timecode()
        self._poll_heartbeat()
        self._timer_stats.start(2000)
        self._timer_timecode.start(1000)
        self._timer_heartbeat.start(5000)

    def _stop_polls(self) -> None:
        self._timer_stats.stop()
        self._timer_timecode.stop()
        self._timer_heartbeat.stop()

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
            cpu = _g(stats, "cpuUsage", "cpu_usage")
            if fps is not None:
                self.set_fps(fps)
            if cpu is not None:
                self.set_cpu(cpu)
            self.stats_tab._on_stats(stats)

        run_in_thread(fetch, update)

    def _poll_timecode(self) -> None:
        if self.ctrl is None:
            return

        def fetch():
            rec_tc = ""
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
                self.set_rec_tc(rec_tc)
                self.record_tab.update_rec_timecode(rec_tc)
            if stream_tc:
                self.set_stream_tc(stream_tc)
                self.record_tab.update_stream_timecode(stream_tc)

        run_in_thread(fetch, update)

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
                self._led.setStyleSheet("color: #888888; font-size: 14pt;")
                self.log("心跳检测失败，OBS 可能已断开", "WARNING")

        run_in_thread(check, on_result)

    # ══════════════════════════════════════════════════════════
    # 全局刷新
    # ══════════════════════════════════════════════════════════

    def refresh_all(self) -> None:
        self.scene_tab.refresh()
        self.audio_tab.refresh()
        self.transition_tab.refresh()
        self.filter_tab.refresh()
        self.replay_tab.refresh()
        self.stats_tab.refresh()

        run_in_thread(
            self.ctrl.get_current_scene,
            lambda s: self.set_scene(s),
        )

    # ══════════════════════════════════════════════════════════
    # 预览面板回调
    # ══════════════════════════════════════════════════════════

    def do_cut(self) -> None:
        if self.ctrl is None:
            return
        ctrl = self.ctrl

        def do_cut_inner():
            cut_name = ctrl._find_cut_transition()
            if not cut_name:
                self.log("未找到 Cut 类转场，请确认 OBS 中存在硬切转场", "WARN")
                return
            ctrl.set_current_transition(cut_name)
            ctrl.set_transition_duration(50)
            ctrl.trigger_studio_mode_transition()

        run_in_thread(do_cut_inner)

    def do_fade(self) -> None:
        if self.ctrl is None:
            return
        ctrl = self.ctrl

        def do_fade_inner():
            fade_name = ctrl._find_fade_transition()
            if not fade_name:
                self.log("未找到 Fade 类转场，请确认 OBS 中存在淡入淡出转场", "WARN")
                return
            ctrl.set_current_transition(fade_name)
            ctrl.set_transition_duration(500)
            ctrl.trigger_studio_mode_transition()

        run_in_thread(do_fade_inner)

    def do_fade_to_black(self) -> None:
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

        run_in_thread(toggle, update, on_error)

    def preview_scene(self, scene_name: str) -> None:
        if self.ctrl is None:
            return
        self.preview_panel.preview_one_shot(scene_name)

    def log(self, message: str, level: str = "INFO") -> None:
        self.log_window.log(message, level)

    # ══════════════════════════════════════════════════════════
    # 关闭处理
    # ══════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        self._on_disconnect()
        event.accept()
