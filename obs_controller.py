"""
OBS WebSocket Python SDK - OBS控制器封装类
基于 obsws-python 库，支持 OBS Studio WebSocket v5.0
文档: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

import obsws_python as obs
from obsws_python.error import OBSSDKError, OBSSDKTimeoutError, OBSSDKRequestError
from typing import Optional, List, Dict, Any, Callable, Union
import logging
import time
import threading

logger = logging.getLogger(__name__)

from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# ==================== 枚举定义 ====================

class MediaAction(Enum):
    """媒体输入动作枚举"""
    NONE = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_NONE"
    PLAY = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
    PAUSE = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
    STOP = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
    RESTART = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
    NEXT = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_NEXT"
    PREVIOUS = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PREVIOUS"


class BlendMode(Enum):
    """场景项混合模式枚举"""
    NORMAL = "OBS_BM_NORMAL"
    ADD = "OBS_BM_ADD"
    SUBTRACT = "OBS_BM_SUBTRACT"
    SCREEN = "OBS_BM_SCREEN"
    MULTIPLY = "OBS_BM_MULTIPLY"
    OVERLAY = "OBS_BM_OVERLAY"


class MonitorType(Enum):
    """音频监听类型枚举"""
    NONE = "OBS_MONITORING_TYPE_NONE"
    MONITOR_ONLY = "OBS_MONITORING_TYPE_MONITOR_ONLY"
    MONITOR_AND_OUTPUT = "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT"


class OutputState(Enum):
    """输出状态枚举"""
    UNKNOWN = "OBS_WEBSOCKET_OUTPUT_UNKNOWN"
    STARTING = "OBS_WEBSOCKET_OUTPUT_STARTING"
    STARTED = "OBS_WEBSOCKET_OUTPUT_STARTED"
    STOPPING = "OBS_WEBSOCKET_OUTPUT_STOPPING"
    STOPPED = "OBS_WEBSOCKET_OUTPUT_STOPPED"
    RECONNECTING = "OBS_WEBSOCKET_OUTPUT_RECONNECTING"
    RECONNECTED = "OBS_WEBSOCKET_OUTPUT_RECONNECTED"
    PAUSED = "OBS_WEBSOCKET_OUTPUT_PAUSED"
    RESUMED = "OBS_WEBSOCKET_OUTPUT_RESUMED"


# ==================== 数据类定义 ====================

@dataclass
class SceneItem:
    """场景项数据结构"""
    scene_item_id: int
    source_name: str
    source_type: str
    source_uuid: Optional[str] = None
    enabled: bool = True
    locked: bool = False
    index: int = 0


@dataclass
class FilterPreset:
    """滤镜预设数据结构"""
    name: str
    filter_kind: str
    filter_type: str
    settings: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


# ==================== 滤镜预设库 ====================

FILTER_PRESETS: Dict[str, FilterPreset] = {
    "美颜-轻度": FilterPreset(
        name="美颜-轻度",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"brightness": 0.05, "contrast": 0.05, "saturation": 0.05}
    ),
    "美颜-中度": FilterPreset(
        name="美颜-中度",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"brightness": 0.1, "contrast": 0.1, "saturation": 0.1}
    ),
    "灰度": FilterPreset(
        name="灰度",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"saturation": 0.0}
    ),
    "反色": FilterPreset(
        name="反色",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"saturation": -1.0, "brightness": 0.1}
    ),
    "怀旧": FilterPreset(
        name="怀旧",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"brightness": 0.0, "contrast": 0.15, "saturation": 0.5, "gamma": 1.2}
    ),
    "冷色调": FilterPreset(
        name="冷色调",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"saturation": 0.9, "gamma": 1.0}
    ),
    "暖色调": FilterPreset(
        name="暖色调",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"brightness": 0.05, "saturation": 0.9, "gamma": 1.0}
    ),
    "锐化": FilterPreset(
        name="锐化",
        filter_kind="sharpness_filter",
        filter_type="Sharpen",
        settings={"sharpness": 0.5}
    ),
    "增益": FilterPreset(
        name="增益",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"brightness": 0.2, "contrast": 0.1}
    ),
    "限幅": FilterPreset(
        name="限幅",
        filter_kind="color_filter",
        filter_type="Color Filter",
        settings={"brightness": -0.05, "contrast": 0.2}
    ),
}


class _ThreadSafeReq:
    """
    线程安全代理：自动为 ReqClient 的每个方法调用加锁。

    obsws-python 的 ReqClient 不是线程安全的 —— 多个线程同时调用
    self.req.* 会导致请求/响应交叉错乱（线程 A 收到线程 B 的响应）。
    此代理在每次方法调用前后获取/释放 threading.Lock，确保串行化。
    """

    def __init__(self, req_client: obs.ReqClient, lock: Optional[threading.Lock] = None):
        self._req = req_client
        self._lock = lock or threading.Lock()

    def __getattr__(self, name: str):
        attr = getattr(self._req, name)
        if callable(attr):
            def _locked(*args, **kwargs):
                with self._lock:
                    return attr(*args, **kwargs)
            return _locked
        return attr


class OBSController:
    """
    OBS WebSocket 控制器

    功能包括：
    - 场景管理（获取列表、切换场景）
    - 输入源管理（获取列表、音量控制、静音控制）
    - 场景项管理（启用/禁用、位置调整）
    - 录制控制（开始、停止、暂停）
    - 推流控制（开始、停止）
    - 媒体源控制（播放、暂停、停止）
    - 滤镜管理
    - 转场控制
    - 统计数据获取
    - 事件监听
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4455,
        password: str = "",
        timeout: Optional[float] = None,
        auto_reconnect: bool = True,
        log_level: int = logging.WARNING
    ):
        """
        初始化 OBS 控制器

        Args:
            host: OBS WebSocket 服务器地址，默认 localhost
            port: OBS WebSocket 端口，默认 4455
            password: 认证密码，默认空字符串
            timeout: 请求超时时间（秒），None 表示无超时
            auto_reconnect: 是否自动重连，默认 True
            log_level: 日志级别，默认 WARNING
        """
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.auto_reconnect = auto_reconnect

        # 设置日志
        logging.basicConfig(level=log_level)
        logger.setLevel(log_level)

        # 请求锁 —— ReqClient 非线程安全，多线程共享时必须串行化
        self._req_lock = threading.Lock()

        # 创建请求客户端（同步控制），用线程安全代理包装
        self.req = _ThreadSafeReq(
            obs.ReqClient(
                host=host,
                port=port,
                password=password,
                timeout=timeout
            ),
            lock=self._req_lock,
        )

        # 事件客户端（延迟初始化，需要注册回调时再创建）
        self.event_client: Optional[obs.EventClient] = None
        self._callbacks: Dict[str, List[Callable]] = {}

        # 自动重连与心跳线程
        self._reconnect_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._reconnect_interval: float = 5.0
        self._heartbeat_interval: float = 30.0
        self._on_reconnect_callbacks: List[Callable] = []

        logger.info(f"OBS控制器初始化完成 - {host}:{port}")

    # ==================== 通用操作 ====================

    def get_version(self) -> Dict[str, Any]:
        """
        获取 OBS 和 obs-websocket 版本信息

        Returns:
            dict: 包含以下字段:
                - obs_web_socket_version: WebSocket 插件版本
                - obs_version: OBS Studio 版本
                - rpc_version: RPC 协议版本
                - available_requests: 可用请求列表
        """
        try:
            resp = self.req.get_version()
            return {
                "obs_web_socket_version": resp.obs_web_socket_version,
                "obs_version": resp.obs_version,
                "rpc_version": resp.rpc_version,
                "available_requests": resp.available_requests
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取版本失败: {e}")
            raise

    def get_stats(self) -> Dict[str, Any]:
        """
        获取 OBS 性能统计数据

        Returns:
            dict: 包含以下字段:
                - cpu_usage: CPU 使用率（百分比）
                - memory_usage: 内存使用量（MB）
                - available_disk_space: 可用磁盘空间（GB）
                - active_fps: 当前渲染 FPS
                - average_frame_render_time: 平均帧渲染时间（毫秒）
                - render_skipped_frames: 渲染跳帧数
                - render_total_frames: 渲染总帧数
                - output_skipped_frames: 输出跳帧数
                - output_total_frames: 输出总帧数
                - websocket_session_incoming_messages: 接收消息数
                - websocket_session_outgoing_messages: 发送消息数
        """
        try:
            resp = self.req.get_stats()
            return {
                "cpu_usage": resp.cpu_usage,
                "memory_usage": resp.memory_usage,
                "available_disk_space": resp.available_disk_space,
                "active_fps": resp.active_fps,
                "average_frame_render_time": resp.average_frame_render_time,
                "render_skipped_frames": resp.render_skipped_frames,
                "render_total_frames": resp.render_total_frames,
                "output_skipped_frames": resp.output_skipped_frames,
                "output_total_frames": resp.output_total_frames,
                "websocket_incoming_messages": resp.web_socket_session_incoming_messages,
                "websocket_outgoing_messages": resp.web_socket_session_outgoing_messages
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取统计失败: {e}")
            raise

    def broadcast_event(self, event_data: Dict[str, Any]) -> bool:
        """
        向所有 WebSocket 客户端广播自定义事件

        Args:
            event_data: 事件数据对象

        Returns:
            bool: 是否成功
        """
        try:
            self.req.broadcast_custom_event(event_data)
            return True
        except OBSSDKRequestError as e:
            logger.error(f"广播事件失败: {e}")
            return False

    # ==================== 场景管理 ====================

    def get_scene_list(self) -> Dict[str, Any]:
        """
        获取所有场景列表

        Returns:
            dict: 包含以下字段:
                - current_program_scene: 当前节目场景名称
                - current_preview_scene: 当前预览场景名称
                - scenes: 场景列表，每个元素包含 sceneName 和 sceneUuid
        """
        try:
            resp = self.req.get_scene_list()
            # obsws-python 返回的 scenes 是 dict 列表，不是对象
            scenes = [
                {"name": s["sceneName"], "uuid": s.get("sceneUuid", "")}
                for s in resp.scenes
            ]
            return {
                "current_program_scene": resp.current_program_scene_name,
                "current_preview_scene": resp.current_preview_scene_name,
                "scenes": scenes
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取场景列表失败: {e}")
            raise

    def get_scene_names(self) -> List[str]:
        """
        获取所有场景名称列表

        Returns:
            list: 场景名称列表
        """
        scene_list = self.get_scene_list()
        return [s["name"] for s in scene_list["scenes"]]

    def get_current_scene(self) -> str:
        """
        获取当前节目场景名称

        Returns:
            str: 当前场景名称
        """
        try:
            resp = self.req.get_current_program_scene()
            return resp.scene_name
        except OBSSDKRequestError as e:
            logger.error(f"获取当前场景失败: {e}")
            raise

    def set_current_scene(self, scene_name: str) -> bool:
        """
        切换到指定场景

        Args:
            scene_name: 目标场景名称

        Returns:
            bool: 是否成功

        Raises:
            OBSSDKRequestError: 场景不存在或切换失败
        """
        try:
            self.req.set_current_program_scene(scene_name)
            logger.info(f"场景切换成功: {scene_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"场景切换失败 [{scene_name}]: {e}")
            raise

    def create_scene(self, scene_name: str) -> str:
        """
        创建新场景

        Args:
            scene_name: 新场景名称

        Returns:
            str: 创建的场景 UUID
        """
        try:
            resp = self.req.create_scene(scene_name)
            logger.info(f"场景创建成功: {scene_name}")
            return resp.scene_uuid
        except OBSSDKRequestError as e:
            logger.error(f"创建场景失败 [{scene_name}]: {e}")
            raise

    def remove_scene(self, scene_name: str) -> bool:
        """
        删除指定场景

        Args:
            scene_name: 要删除的场景名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.remove_scene(scene_name)
            logger.info(f"场景删除成功: {scene_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"删除场景失败 [{scene_name}]: {e}")
            raise

    # ==================== 输入源管理 ====================

    def get_input_list(self, input_kind: Optional[str] = None) -> List[Dict[str, str]]:
        """
        获取所有输入源列表

        Args:
            input_kind: 可选，限制为指定类型的输入源

        Returns:
            list: 输入源列表，每个元素包含 inputName 和 inputUuid
        """
        try:
            if input_kind:
                resp = self.req.get_input_list(input_kind)
            else:
                resp = self.req.get_input_list()
            # obsws-python 返回 dict 列表（驼峰 key）
            return [
                {"name": inp["inputName"], "uuid": inp.get("inputUuid", ""), "kind": inp.get("inputKind", "")}
                for inp in resp.inputs
            ]
        except OBSSDKRequestError as e:
            logger.error(f"获取输入源列表失败: {e}")
            raise

    def get_audio_inputs(self) -> List[Dict[str, str]]:
        """
        获取所有音频输入源（麦克风、音频输出、媒体音频等）
        通过逐个尝试 GetInputVolume，过滤掉不支持音频的输入源（code 604）。
        比硬编码 audio_kinds 更可靠，不受 OBS 版本/插件影响。
        """
        all_inputs = self.get_input_list()
        audio_inputs = []
        for inp in all_inputs:
            name = inp.get("name", "")
            if not name:
                continue
            try:
                # 尝试获取音量，若 604 则跳过
                self.req.get_input_volume(name)
                audio_inputs.append(inp)
            except OBSSDKRequestError as e:
                if getattr(e, "code", None) == 604:
                    continue
                raise
        return audio_inputs

    def get_input_volume(self, input_name: str) -> Dict[str, float]:
        """
        获取输入源音量

        Args:
            input_name: 输入源名称

        Returns:
            dict: 包含 volume_mul（倍数）和 volume_db（分贝）

        Raises:
            OBSSDKRequestError: code 604 表示输入源不支持音频；其他错误正常抛出
        """
        try:
            resp = self.req.get_input_volume(input_name)
            return {
                "volume_mul": resp.input_volume_mul,
                "volume_db": resp.input_volume_db
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取音量失败 [{input_name}]: {e}")
            raise

    def get_input_volume_safe(self, input_name: str) -> Dict[str, float]:
        """
        安全版：不支持音频的输入源（code 604）静默返回默认音量，其他错误仍抛出。

        Returns:
            dict: 包含 volume_mul（0~1）和 volume_db（dB）
        """
        try:
            return self.get_input_volume(input_name)
        except OBSSDKRequestError as e:
            if getattr(e, "code", None) == 604:
                return {"volume_mul": 1.0, "volume_db": 0.0}
            raise

    def set_input_volume(self, input_name: str, volume_db: Optional[float] = None,
                        volume_mul: Optional[float] = None) -> Dict[str, float]:
        """
        设置输入源音量

        Args:
            input_name: 输入源名称
            volume_db: 音量值（分贝），范围 -100.0 ~ 26.0
            volume_mul: 音量倍数，范围 0.0 ~ 20.0

        Note:
            优先使用 volume_db，volume_mul 会被忽略如果两个都提供了

        Returns:
            dict: 设置后的音量值
        """
        try:
            kwargs = {"input_name": input_name}
            if volume_db is not None:
                kwargs["input_volume_db"] = volume_db
            elif volume_mul is not None:
                kwargs["input_volume_mul"] = volume_mul
            else:
                raise ValueError("必须提供 volume_db 或 volume_mul")

            resp = self.req.set_input_volume(**kwargs)
            logger.info(f"音量设置成功 [{input_name}]: {resp.input_volume_db} dB")
            return {
                "volume_mul": resp.input_volume_mul,
                "volume_db": resp.input_volume_db
            }
        except OBSSDKRequestError as e:
            logger.error(f"设置音量失败 [{input_name}]: {e}")
            raise

    def get_input_mute(self, input_name: str) -> bool:
        """
        获取输入源静音状态

        Args:
            input_name: 输入源名称

        Returns:
            bool: 是否静音
        """
        try:
            resp = self.req.get_input_mute(input_name)
            return resp.input_muted
        except OBSSDKRequestError as e:
            logger.error(f"获取静音状态失败 [{input_name}]: {e}")
            raise

    def set_input_mute(self, input_name: str, muted: bool) -> bool:
        """
        设置输入源静音状态

        Args:
            input_name: 输入源名称
            muted: 是否静音

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_input_mute(input_name, muted)
            logger.info(f"静音状态设置成功 [{input_name}]: {'静音' if muted else '取消静音'}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置静音状态失败 [{input_name}]: {e}")
            raise

    def toggle_input_mute(self, input_name: str) -> bool:
        """
        切换输入源静音状态

        Args:
            input_name: 输入源名称

        Returns:
            bool: 切换后的静音状态
        """
        try:
            resp = self.req.toggle_input_mute(input_name)
            logger.info(f"静音切换 [{input_name}]: {'静音' if resp.input_muted else '取消静音'}")
            return resp.input_muted
        except OBSSDKRequestError as e:
            logger.error(f"切换静音失败 [{input_name}]: {e}")
            raise

    def get_input_audio_sync_offset(self, input_name: str) -> int:
        """
        获取输入源音频同步偏移

        Args:
            input_name: 输入源名称

        Returns:
            int: 同步偏移量（毫秒）
        """
        try:
            resp = self.req.get_input_audio_sync_offset(input_name)
            return resp.input_audio_sync_offset
        except OBSSDKRequestError as e:
            logger.error(f"获取同步偏移失败 [{input_name}]: {e}")
            raise

    def set_input_audio_sync_offset(self, input_name: str, offset_ms: int) -> int:
        """
        设置输入源音频同步偏移

        Args:
            input_name: 输入源名称
            offset_ms: 同步偏移量（毫秒）

        Returns:
            int: 设置后的同步偏移量
        """
        try:
            resp = self.req.set_input_audio_sync_offset(input_name, offset_ms)
            logger.info(f"同步偏移设置成功 [{input_name}]: {offset_ms}ms")
            return resp.input_audio_sync_offset
        except OBSSDKRequestError as e:
            logger.error(f"设置同步偏移失败 [{input_name}]: {e}")
            raise

    # ==================== 场景项管理 ====================

    def get_scene_items(self, scene_name: str) -> List[Dict[str, Any]]:
        """
        获取场景中的所有场景项

        Args:
            scene_name: 场景名称

        Returns:
            list: 场景项列表
        """
        try:
            resp = self.req.get_scene_item_list(scene_name)
            # obsws-python 返回的 scene_items 是 dict 列表（驼峰 key）
            return [
                {
                    "scene_item_id": item["sceneItemId"],
                    "source_name": item["sourceName"],
                    "source_type": item["sourceType"],
                    "enabled": item.get("sceneItemEnabled", True)
                }
                for item in resp.scene_items
            ]
        except OBSSDKRequestError as e:
            logger.error(f"获取场景项失败 [{scene_name}]: {e}")
            raise

    def set_scene_item_enabled(self, scene_name: str, scene_item_id: int,
                               enabled: bool) -> bool:
        """
        设置场景项的启用/禁用状态

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            enabled: 是否启用

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_scene_item_enabled(scene_name, scene_item_id, enabled)
            logger.info(f"场景项状态设置 [{scene_name}] ID:{scene_item_id}: {'启用' if enabled else '禁用'}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置场景项状态失败: {e}")
            raise

    def set_scene_item_enabled_by_name(self, scene_name: str, source_name: str,
                                       enabled: bool) -> bool:
        """
        根据源名称设置场景项的启用/禁用状态

        Args:
            scene_name: 场景名称
            source_name: 源名称
            enabled: 是否启用

        Returns:
            bool: 是否成功
        """
        try:
            # 先获取场景项 ID
            resp = self.req.get_scene_item_id(scene_name, source_name)
            return self.set_scene_item_enabled(scene_name, resp.scene_item_id, enabled)
        except OBSSDKRequestError as e:
            logger.error(f"设置场景项状态失败 [{source_name}]: {e}")
            raise

    def get_scene_item_transform(self, scene_name: str,
                                 scene_item_id: int) -> Dict[str, Any]:
        """
        获取场景项变换信息（位置、缩放、旋转等）

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID

        Returns:
            dict: 变换信息
        """
        try:
            resp = self.req.get_scene_item_transform(scene_name, scene_item_id)
            return resp.scene_item_transform
        except OBSSDKRequestError as e:
            logger.error(f"获取场景项变换失败: {e}")
            raise

    def set_scene_item_transform(self, scene_name: str, scene_item_id: int,
                                  transform: Dict[str, Any]) -> bool:
        """
        设置场景项变换信息

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            transform: 变换信息对象，常见字段:
                - pos_x, pos_y: 位置
                - scale_x, scale_y: 缩放
                - rotation: 旋转角度
                - crop_left, crop_right, crop_top, crop_bottom: 裁剪

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_scene_item_transform(scene_name, scene_item_id, transform)
            logger.info(f"场景项变换设置成功 [{scene_name}] ID:{scene_item_id}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置场景项变换失败: {e}")
            raise

    def set_scene_item_index(self, scene_name: str, scene_item_id: int,
                             index: int) -> bool:
        """
        设置场景项的层级位置

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            index: 目标层级位置

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_scene_item_index(scene_name, scene_item_id, index)
            logger.info(f"场景项层级设置 [{scene_name}] ID:{scene_item_id} -> {index}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置场景项层级失败: {e}")
            raise

    # ==================== 录制控制 ====================

    def get_record_status(self) -> Dict[str, Any]:
        """
        获取录制状态

        Returns:
            dict: 录制状态信息
        """
        try:
            resp = self.req.get_record_status()
            return {
                "output_active": resp.output_active,
                "output_paused": resp.output_paused,
                "output_timecode": getattr(resp, 'output_timecode', None),
                "output_duration": getattr(resp, 'output_duration', None),
                "output_bytes": getattr(resp, 'output_bytes', None)
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取录制状态失败: {e}")
            raise

    def start_record(self) -> Optional[str]:
        """
        开始录制

        Returns:
            str: 录制文件路径，或 None
        """
        try:
            resp = self.req.start_record()
            logger.info(f"录制开始: {resp.output_path}")
            return resp.output_path
        except OBSSDKRequestError as e:
            logger.error(f"开始录制失败: {e}")
            raise

    def stop_record(self) -> Optional[str]:
        """
        停止录制

        Returns:
            str: 录制文件路径，或 None
        """
        try:
            resp = self.req.stop_record()
            logger.info(f"录制停止: {resp.output_path}")
            return resp.output_path
        except OBSSDKRequestError as e:
            logger.error(f"停止录制失败: {e}")
            raise

    def toggle_record(self) -> bool:
        """
        切换录制状态

        Returns:
            bool: 当前录制是否激活
        """
        try:
            resp = self.req.toggle_record()
            logger.info(f"录制切换: {'录制中' if resp.output_active else '已停止'}")
            return resp.output_active
        except OBSSDKRequestError as e:
            logger.error(f"切换录制失败: {e}")
            raise

    def pause_record(self) -> bool:
        """
        暂停录制

        Returns:
            bool: 是否成功
        """
        try:
            self.req.pause_record()
            logger.info("录制已暂停")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"暂停录制失败: {e}")
            raise

    def resume_record(self) -> bool:
        """
        恢复录制

        Returns:
            bool: 是否成功
        """
        try:
            self.req.resume_record()
            logger.info("录制已恢复")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"恢复录制失败: {e}")
            raise

    # ==================== 推流控制 ====================

    def get_stream_status(self) -> Dict[str, Any]:
        """
        获取推流状态

        Returns:
            dict: 推流状态信息
        """
        try:
            resp = self.req.get_stream_status()
            return {
                "output_active": resp.output_active,
                "output_reconnecting": resp.output_reconnecting,
                "output_timecode": getattr(resp, 'output_timecode', None),
                "output_duration": getattr(resp, 'output_duration', None)
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取推流状态失败: {e}")
            raise

    def start_stream(self) -> bool:
        """
        开始推流

        Returns:
            bool: 是否成功
        """
        try:
            self.req.start_stream()
            logger.info("推流开始")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"开始推流失败: {e}")
            raise

    def stop_stream(self) -> bool:
        """
        停止推流

        Returns:
            bool: 是否成功
        """
        try:
            self.req.stop_stream()
            logger.info("推流已停止")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"停止推流失败: {e}")
            raise

    def toggle_stream(self) -> bool:
        """
        切换推流状态

        Returns:
            bool: 当前推流是否激活
        """
        try:
            resp = self.req.toggle_stream()
            logger.info(f"推流切换: {'推流中' if resp.output_active else '已停止'}")
            return resp.output_active
        except OBSSDKRequestError as e:
            logger.error(f"切换推流失败: {e}")
            raise

    # ==================== 虚拟摄像头 ====================

    def get_virtualcam_status(self) -> Dict[str, bool]:
        """
        获取虚拟摄像头状态

        Returns:
            dict: 包含 output_active 字段
        """
        try:
            resp = self.req.get_virtualcam_status()
            return {"output_active": resp.output_active}
        except OBSSDKRequestError as e:
            logger.error(f"获取虚拟摄像头状态失败: {e}")
            raise

    def start_virtualcam(self) -> bool:
        """
        启动虚拟摄像头

        Returns:
            bool: 是否成功
        """
        try:
            self.req.start_virtualcam()
            logger.info("虚拟摄像头启动")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"启动虚拟摄像头失败: {e}")
            raise

    def stop_virtualcam(self) -> bool:
        """
        停止虚拟摄像头

        Returns:
            bool: 是否成功
        """
        try:
            self.req.stop_virtualcam()
            logger.info("虚拟摄像头已停止")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"停止虚拟摄像头失败: {e}")
            raise

    def toggle_virtualcam(self) -> bool:
        """
        切换虚拟摄像头状态

        Returns:
            bool: 当前虚拟摄像头是否激活
        """
        try:
            resp = self.req.toggle_virtualcam()
            logger.info(f"虚拟摄像头切换: {'启动' if resp.output_active else '已停止'}")
            return resp.output_active
        except OBSSDKRequestError as e:
            logger.error(f"切换虚拟摄像头失败: {e}")
            raise

    # ==================== 转场控制 ====================

    def get_transition_list(self) -> List[Dict[str, str]]:
        """
        获取转场列表

        Returns:
            list: 转场列表
        """
        try:
            resp = self.req.get_scene_transition_list()
            # obsws-python 返回 dict 列表（驼峰 key）
            return [
                {"name": t["transitionName"], "kind": t.get("transitionKind", "")}
                for t in resp.transitions
            ]
        except OBSSDKRequestError as e:
            logger.error(f"获取转场列表失败: {e}")
            raise

    def get_current_transition(self) -> str:
        """
        获取当前转场名称

        Returns:
            str: 当前转场名称
        """
        try:
            resp = self.req.get_current_scene_transition()
            return resp.transition_name
        except OBSSDKRequestError as e:
            logger.error(f"获取当前转场失败: {e}")
            raise

    def set_current_transition(self, transition_name: str) -> bool:
        """
        设置当前转场

        Args:
            transition_name: 转场名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_current_scene_transition(transition_name)
            logger.info(f"转场切换: {transition_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置转场失败 [{transition_name}]: {e}")
            raise

    def set_transition_duration(self, duration_ms: int) -> bool:
        """
        设置转场持续时间

        Args:
            duration_ms: 持续时间（毫秒）

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_current_scene_transition_duration(duration_ms)
            logger.info(f"转场时间设置: {duration_ms}ms")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置转场时间失败: {e}")
            raise

    def _find_fade_transition(self) -> str:
        """
        查找当前 OBS 中可用的 Fade 类转场实例名称。
        OBS 转场名称是本地化的（中文版叫"淡入淡出"），不能写死 "Fade"。
        同时检查 transitionKind（类型标识，不受本地化影响）。
        返回找到的转场实例名称；如果不存在则返回空字符串。
        """
        try:
            resp = self.req.get_scene_transition_list()
            items = list(resp.transitions)  # list[dict], camelCase keys
            logger.info(f"_find_fade_transition: items={items}")
            for item in items:
                # 兼容 dict（camelCase）和对象（snake_case）两种形式
                if isinstance(item, dict):
                    name = item.get("transitionName") or item.get("transition_name") or ""
                    kind = item.get("transitionKind") or item.get("transition_kind") or ""
                else:
                    name = getattr(item, "transition_name", "") or getattr(item, "transitionName", "")
                    kind = getattr(item, "transition_kind", "") or getattr(item, "transitionKind", "")
                name_str = str(name)
                logger.info(f"  检查转场: name='{name_str}', kind='{kind}'")
                if name == "Fade" or "淡" in name_str or "fade" in name_str.lower() or kind == "fade_transition":
                    logger.info(f"  找到 Fade 类转场: name={name_str}")
                    return name_str
            logger.warning(f"未找到 Fade 类转场，原始数据: {items}")
            return ""
        except Exception as e:
            logger.warning(f"查找 Fade 转场失败: {e}")
            return ""

    # ==================== 淡出到黑场 ====================

    BLACK_SCENE_NAME = "🌑 Black"
    BLACK_SOURCE_NAME = "BlackSource"

    def fade_to_black(self, duration_ms: int = 800) -> str:
        """
        淡出到黑场：使用 Studio Mode 的 Preview + Transition 管线，
        以 Fade 转场平滑过渡到纯黑场景。

        保存当前场景、转场参数和 Studio Mode 状态，以便 fade_from_black() 完全恢复。

        Args:
            duration_ms: Fade 转场持续时间（毫秒）

        Returns:
            str: 进入黑场前的原始场景名称
        """
        import time
        try:
            # 1. 保存当前场景
            self._pre_black_scene = self.get_current_scene()
            if self._pre_black_scene == self.BLACK_SCENE_NAME:
                logger.warning("已在黑场场景中")
                return self._pre_black_scene

            # 2. 保存当前转场参数（OBS v5 无获取当前时长的 API，仅保存转场名称）
            self._pre_black_transition = self.get_current_transition()

            # 3. 保存 Studio Mode 状态，必要时启用
            self._pre_black_studio_mode = self.get_studio_mode_enabled()
            if not self._pre_black_studio_mode:
                self.set_studio_mode_enabled(True)
                time.sleep(0.05)  # 等待 OBS 进入 Studio Mode

            # 4. 确保 Black 场景存在
            self._ensure_black_scene()

            # 5. 查找并设置 Fade 类转场
            fade_name = self._find_fade_transition()
            if fade_name:
                self.set_current_transition(fade_name)
                self.set_transition_duration(duration_ms)
            else:
                logger.warning("未找到 Fade 类转场，使用当前转场")
                self.set_transition_duration(duration_ms)

            # 6. 设置预览场景为黑场，然后触发转场
            self.set_current_preview_scene(self.BLACK_SCENE_NAME)
            time.sleep(0.05)  # 等待 OBS 设置预览
            self.trigger_studio_mode_transition()

            logger.info(f"淡出到黑场完成（{duration_ms}ms），原场景: {self._pre_black_scene}")
            return self._pre_black_scene

        except OBSSDKRequestError:
            logger.exception("淡出到黑场失败")
            raise

    def fade_from_black(self, duration_ms: int = 800) -> str:
        """
        从黑场恢复：切换回淡出前的场景并完全恢复原始状态。

        Args:
            duration_ms: Fade 转场持续时间（毫秒）

        Returns:
            str: 恢复的场景名称
        """
        import time
        try:
            pre_scene = getattr(self, "_pre_black_scene", None)
            pre_transition = getattr(self, "_pre_black_transition", None)
            pre_studio = getattr(self, "_pre_black_studio_mode", False)

            if not pre_scene:
                logger.warning("没有保存的原始场景，无法从黑场恢复")
                return ""

            # 1. 查找并设置 Fade 类转场
            fade_name = self._find_fade_transition()
            if fade_name:
                self.set_current_transition(fade_name)
                self.set_transition_duration(duration_ms)
            else:
                logger.warning("未找到 Fade 类转场，使用当前转场")
                self.set_transition_duration(duration_ms)

            # 2. 预览 → 原场景，触发转场
            self.set_current_preview_scene(pre_scene)
            time.sleep(0.05)
            self.trigger_studio_mode_transition()

            # 3. 恢复原始转场名称
            fade_name = self._find_fade_transition()
            if pre_transition and pre_transition != fade_name:
                self.set_current_transition(pre_transition)

            # 4. 恢复 Studio Mode 状态
            if not pre_studio:
                self.set_studio_mode_enabled(False)

            logger.info(f"从黑场恢复: {pre_scene}")
            return pre_scene

        except OBSSDKRequestError:
            logger.exception("从黑场恢复失败")
            raise

    def get_studio_mode_enabled(self) -> bool:
        """获取 Studio Mode 是否启用。"""
        try:
            resp = self.req.get_studio_mode_enabled()
            return resp.studio_mode_enabled
        except OBSSDKRequestError as e:
            logger.error(f"获取 Studio Mode 状态失败: {e}")
            raise

    def set_studio_mode_enabled(self, enabled: bool) -> bool:
        """启用/禁用 Studio Mode。"""
        try:
            self.req.set_studio_mode_enabled(enabled)
            logger.info(f"Studio Mode: {'启用' if enabled else '禁用'}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置 Studio Mode 失败: {e}")
            raise

    def _ensure_black_scene(self) -> None:
        """确保 🌑 Black 场景存在（含纯黑颜色源）。"""
        scenes = self.get_scene_names()
        if self.BLACK_SCENE_NAME in scenes:
            return

        # 创建黑场场景
        self.create_scene(self.BLACK_SCENE_NAME)
        logger.info(f"已创建黑场场景: {self.BLACK_SCENE_NAME}")

        # 创建纯黑颜色源并添加到场景
        try:
            self.create_input(
                input_name=self.BLACK_SOURCE_NAME,
                input_kind="color_source_v3",
                input_settings={
                    "width": 1920,
                    "height": 1080,
                    "color": 4278190080,  # 0xFF000000, ARGB 纯黑
                },
                scene_name=self.BLACK_SCENE_NAME,
            )
            logger.info(f"已创建黑场颜色源: {self.BLACK_SOURCE_NAME}")
        except OBSSDKRequestError as e:
            logger.warning(f"color_source_v3 创建失败: {e}，尝试 color_source_v2")
            try:
                self.create_input(
                    input_name=self.BLACK_SOURCE_NAME,
                    input_kind="color_source_v2",
                    input_settings={
                        "width": 1920,
                        "height": 1080,
                        "color": 4278190080,
                    },
                    scene_name=self.BLACK_SCENE_NAME,
                )
                logger.info(f"已用 color_source_v2 创建黑场颜色源")
            except OBSSDKRequestError as e2:
                logger.error(f"所有颜色源类型均创建失败: {e2}")
                raise

    # ==================== 滤镜管理 ====================

    def get_filter_list(self, source_name: str) -> List[Dict[str, Any]]:
        """
        获取源上的滤镜列表

        Args:
            source_name: 源名称

        Returns:
            list: 滤镜列表
        """
        try:
            resp = self.req.get_source_filter_list(source_name)
            # obsws-python 返回 dict 列表（驼峰 key）
            return [
                {
                    "name": f["filterName"],
                    "kind": f.get("filterKind", ""),
                    "enabled": f.get("filterEnabled", True),
                    "type": f.get("filterType", "")
                }
                for f in resp.filters
            ]
        except OBSSDKRequestError as e:
            logger.error(f"获取滤镜列表失败 [{source_name}]: {e}")
            raise

    def set_filter_enabled(self, source_name: str, filter_name: str,
                          enabled: bool) -> bool:
        """
        设置滤镜启用/禁用状态

        Args:
            source_name: 源名称
            filter_name: 滤镜名称
            enabled: 是否启用

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_source_filter_enabled(source_name, filter_name, enabled)
            logger.info(f"滤镜状态设置 [{source_name}/{filter_name}]: {'启用' if enabled else '禁用'}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置滤镜状态失败: {e}")
            raise

    def set_filter_settings(self, source_name: str, filter_name: str,
                            settings: Dict[str, Any], overlay: bool = True) -> bool:
        """
        设置滤镜参数

        Args:
            source_name: 源名称
            filter_name: 滤镜名称
            settings: 滤镜设置对象
            overlay: True=叠加当前设置, False=替换全部设置

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_source_filter_settings(
                source_name, filter_name, settings, overlay
            )
            logger.info(f"滤镜设置更新 [{source_name}/{filter_name}]")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置滤镜参数失败: {e}")
            raise

    # ==================== 媒体源控制 ====================

    def get_media_input_status(self, input_name: str) -> Dict[str, str]:
        """
        获取媒体输入状态

        Args:
            input_name: 媒体输入名称

        Returns:
            dict: 包含 media_state 字段
        """
        try:
            resp = self.req.get_media_input_status(input_name)
            return {"media_state": resp.media_state}
        except OBSSDKRequestError as e:
            logger.error(f"获取媒体状态失败 [{input_name}]: {e}")
            raise

    def trigger_media_action(self, input_name: str, action: str) -> bool:
        """
        触发媒体输入动作

        Args:
            input_name: 媒体输入名称
            action: 动作类型，取值:
                - "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
                - "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
                - "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
                - "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
                - "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_NEXT"
                - "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PREVIOUS"

        Returns:
            bool: 是否成功
        """
        try:
            self.req.trigger_media_input_action(input_name, action)
            logger.info(f"媒体动作触发 [{input_name}]: {action}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"触发媒体动作失败 [{input_name}]: {e}")
            raise

    def play_media(self, input_name: str) -> bool:
        """播放媒体"""
        return self.trigger_media_action(
            input_name, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
        )

    def pause_media(self, input_name: str) -> bool:
        """暂停媒体"""
        return self.trigger_media_action(
            input_name, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
        )

    def stop_media(self, input_name: str) -> bool:
        """停止媒体"""
        return self.trigger_media_action(
            input_name, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
        )

    def restart_media(self, input_name: str) -> bool:
        """重新播放媒体"""
        return self.trigger_media_action(
            input_name, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
        )

    # ==================== 输入源设置 ====================

    def get_input_settings(self, input_name: str) -> Dict[str, Any]:
        """
        获取输入源设置

        Args:
            input_name: 输入源名称

        Returns:
            dict: 输入源设置
        """
        try:
            resp = self.req.get_input_settings(input_name)
            return {
                "settings": resp.input_settings,
                "kind": resp.input_kind
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取输入源设置失败 [{input_name}]: {e}")
            raise

    def set_input_settings(self, input_name: str, settings: Dict[str, Any],
                          overlay: bool = True) -> bool:
        """
        设置输入源参数

        Args:
            input_name: 输入源名称
            settings: 设置对象
            overlay: True=叠加当前设置, False=替换全部设置

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_input_settings(input_name, settings, overlay)
            logger.info(f"输入源设置更新 [{input_name}]")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置输入源参数失败 [{input_name}]: {e}")
            raise

    # ==================== 事件监听 ====================

    def setup_event_client(self, subs: Optional[Any] = None):
        """
        初始化事件客户端

        Args:
            subs: 订阅类型，默认 Subs.LOW_VOLUME
        """
        if self.event_client is None:
            if subs is None:
                subs = obs.Subs.LOW_VOLUME
            self.event_client = obs.EventClient(
                host=self.host,
                port=self.port,
                password=self.password,
                timeout=self.timeout,
                subs=subs
            )
            logger.info("事件客户端初始化完成")

    def on_scene_created(self, func: Callable) -> None:
        """注册场景创建回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)
        logger.debug(f"注册回调: {func.__name__}")

    def on_scene_removed(self, func: Callable) -> None:
        """注册场景删除回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_scene_changed(self, func: Callable) -> None:
        """注册场景切换回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_input_mute_changed(self, func: Callable) -> None:
        """注册输入静音状态变更回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_record_state_changed(self, func: Callable) -> None:
        """注册录制状态变更回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_stream_state_changed(self, func: Callable) -> None:
        """注册推流状态变更回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_custom_event(self, func: Callable) -> None:
        """注册自定义事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def register_callback(self, event_name: str, func: Callable) -> None:
        """
        注册任意事件回调

        Args:
            event_name: 事件名称，如 "SceneCreated" -> "on_scene_created"
            func: 回调函数
        """
        self.setup_event_client()
        callback_name = f"on_{event_name.lower()}"
        if hasattr(self.event_client.callback, 'register'):
            self.event_client.callback.register(func)
            logger.debug(f"注册回调 [{event_name}]: {func.__name__}")

    # ==================== 工具方法 ====================

    def get_summary(self) -> Dict[str, Any]:
        """
        获取 OBS 状态摘要（便捷方法）

        Returns:
            dict: 包含主要状态信息
        """
        try:
            scene_list = self.get_scene_list()
            record_status = self.get_record_status()
            stream_status = self.get_stream_status()
            stats = self.get_stats()

            return {
                "connected": True,
                "obs_version": self.get_version()["obs_version"],
                "current_scene": scene_list["current_program_scene"],
                "available_scenes": len(scene_list["scenes"]),
                "recording": record_status["output_active"],
                "streaming": stream_status["output_active"],
                "stats": {
                    "cpu": f"{stats['cpu_usage']:.1f}%",
                    "memory": f"{stats['memory_usage']:.1f}MB",
                    "fps": stats['active_fps']
                }
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e)
            }

    def wait_for_scene(self, scene_name: str, timeout: float = 10.0) -> bool:
        """
        等待切换到指定场景（轮询方式）

        Args:
            scene_name: 目标场景名称
            timeout: 超时时间（秒）

        Returns:
            bool: 是否成功切换
        """
        import time
        start = time.time()
        while time.time() - start < timeout:
            if self.get_current_scene() == scene_name:
                return True
            time.sleep(0.1)
        return False

    def close(self) -> None:
        """关闭连接"""
        self._running = False
        if self.event_client:
            self.event_client.callback.deregister_all()
            self.event_client = None
        logger.info("OBS控制器已关闭")

    # ==================== 截图 / 预览 / Studio 模式 ====================

    def get_source_screenshot(
        self, source_name: str, img_format: str = "jpg",
        width: int = 640, height: int = 360, quality: int = 80,
    ) -> str:
        """
        获取源的截图，返回 base64 编码的图片字符串。

        Args:
            source_name: 源名称（或场景名称）
            img_format: 图片格式 (jpg, png, etc.)
            width / height: 截图尺寸
            quality: JPEG 质量 1-100

        Returns:
            str: base64 编码的图片数据
        """
        try:
            resp = self.req.get_source_screenshot(
                source_name, img_format,
                width, height,
                quality,
            )
            return resp.image_data
        except OBSSDKRequestError as e:
            logger.error(f"获取截图失败 [{source_name}]: {e}")
            raise

    def __enter__(self):
        """上下文管理器入口"""
        return self

    # ==================== 热键控制 ====================

    def get_hotkey_list(self) -> List[str]:
        """
        获取 OBS 中所有热键名称列表

        Returns:
            list: 热键名称列表
        """
        try:
            resp = self.req.get_hotkey_list()
            return list(resp.hotkeys)
        except OBSSDKRequestError as e:
            logger.error(f"获取热键列表失败: {e}")
            raise

    def trigger_hotkey_by_name(self, hotkey_name: str) -> bool:
        """
        通过热键名称触发热键

        Args:
            hotkey_name: 热键名称（从 get_hotkey_list 获取）

        Returns:
            bool: 是否成功
        """
        try:
            self.req.trigger_hotkey_by_name(hotkey_name)
            logger.info(f"热键触发: {hotkey_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"触发热键失败 [{hotkey_name}]: {e}")
            raise

    def trigger_hotkey_by_sequence(
        self,
        key_id: str,
        shift: bool = False,
        control: bool = False,
        alt: bool = False,
        command: bool = False
    ) -> bool:
        """
        通过按键序列触发热键

        Args:
            key_id: 按键 ID（如 "OBS_KEY_1", "OBS_KEY_A"）
            shift: 是否按住 Shift
            control: 是否按住 Ctrl
            alt: 是否按住 Alt
            command: 是否按住 Command/Win

        Returns:
            bool: 是否成功
        """
        try:
            modifiers = {
                "shift": shift,
                "control": control,
                "alt": alt,
                "command": command
            }
            self.req.trigger_hotkey_by_key_sequence(key_id, modifiers)
            logger.info(f"按键序列触发: {key_id}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"触发按键序列失败 [{key_id}]: {e}")
            raise

    # ==================== 场景项增删改 ====================

    def get_scene_item_id(self, scene_name: str, source_name: str) -> int:
        """
        根据源名称获取场景项 ID

        Args:
            scene_name: 场景名称
            source_name: 源名称

        Returns:
            int: 场景项 ID
        """
        try:
            resp = self.req.get_scene_item_id(scene_name, source_name)
            return resp.scene_item_id
        except OBSSDKRequestError as e:
            logger.error(f"获取场景项ID失败 [{scene_name}/{source_name}]: {e}")
            raise

    def add_scene_item(
        self,
        scene_name: str,
        source_name: str,
        enabled: bool = True
    ) -> int:
        """
        向场景添加场景项

        Args:
            scene_name: 场景名称
            source_name: 源名称
            enabled: 是否启用

        Returns:
            int: 创建的场景项 ID
        """
        try:
            resp = self.req.create_scene_item(scene_name, source_name, enabled=enabled)
            logger.info(f"场景项添加成功 [{scene_name}] {source_name} -> ID:{resp.scene_item_id}")
            return resp.scene_item_id
        except OBSSDKRequestError as e:
            logger.error(f"添加场景项失败 [{scene_name}/{source_name}]: {e}")
            raise

    def remove_scene_item(self, scene_name: str, scene_item_id: int) -> bool:
        """
        从场景移除场景项

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID

        Returns:
            bool: 是否成功
        """
        try:
            self.req.remove_scene_item(scene_name, scene_item_id)
            logger.info(f"场景项移除成功 [{scene_name}] ID:{scene_item_id}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"移除场景项失败 [{scene_name}] ID:{scene_item_id}: {e}")
            raise

    def remove_scene_item_by_name(self, scene_name: str, source_name: str) -> bool:
        """
        根据源名称从场景移除场景项

        Args:
            scene_name: 场景名称
            source_name: 源名称

        Returns:
            bool: 是否成功
        """
        item_id = self.get_scene_item_id(scene_name, source_name)
        return self.remove_scene_item(scene_name, item_id)

    def duplicate_scene_item(
        self,
        scene_name: str,
        scene_item_id: int,
        dest_scene_name: Optional[str] = None
    ) -> int:
        """
        复制场景项（可跨场景）

        Args:
            scene_name: 源场景名称
            scene_item_id: 场景项 ID
            dest_scene_name: 目标场景名称，None 表示同场景复制

        Returns:
            int: 新场景项的 ID
        """
        try:
            resp = self.req.duplicate_scene_item(
                scene_name, scene_item_id,
                destination_scene_name=dest_scene_name
            )
            logger.info(
                f"场景项复制成功 [{scene_name}] ID:{scene_item_id}"
                f" -> [{dest_scene_name or scene_name}] ID:{resp.scene_item_id}"
            )
            return resp.scene_item_id
        except OBSSDKRequestError as e:
            logger.error(f"复制场景项失败: {e}")
            raise

    # ==================== 场景项变换精细控制 ====================

    def get_scene_item_blend_mode(self, scene_name: str,
                                  scene_item_id: int) -> str:
        """
        获取场景项的混合模式

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID

        Returns:
            str: 混合模式
        """
        try:
            resp = self.req.get_scene_item_blend_mode(scene_name, scene_item_id)
            return resp.scene_item_blend_mode
        except OBSSDKRequestError as e:
            logger.error(f"获取混合模式失败: {e}")
            raise

    def set_scene_item_blend_mode(self, scene_name: str,
                                  scene_item_id: int,
                                  blend_mode: Union[str, BlendMode]) -> bool:
        """
        设置场景项的混合模式

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            blend_mode: 混合模式（字符串或 BlendMode 枚举）:
                - "OBS_BM_NORMAL"      (正常)
                - "OBS_BM_ADD"         (叠加)
                - "OBS_BM_SUBTRACT"    (减去)
                - "OBS_BM_SCREEN"      (屏幕)
                - "OBS_BM_MULTIPLY"    (正片叠底)
                - "OBS_BM_OVERLAY"     (覆盖)

        Returns:
            bool: 是否成功
        """
        try:
            mode = blend_mode.value if isinstance(blend_mode, BlendMode) else blend_mode
            self.req.set_scene_item_blend_mode(scene_name, scene_item_id, mode)
            logger.info(f"混合模式设置 [{scene_name}] ID:{scene_item_id}: {mode}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置混合模式失败: {e}")
            raise

    def get_scene_item_locked(self, scene_name: str,
                              scene_item_id: int) -> bool:
        """
        获取场景项的锁定状态

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID

        Returns:
            bool: 是否锁定
        """
        try:
            resp = self.req.get_scene_item_locked(scene_name, scene_item_id)
            return resp.scene_item_locked
        except OBSSDKRequestError as e:
            logger.error(f"获取锁定状态失败: {e}")
            raise

    def set_scene_item_locked(self, scene_name: str, scene_item_id: int,
                               locked: bool) -> bool:
        """
        设置场景项的锁定状态

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            locked: 是否锁定

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_scene_item_locked(scene_name, scene_item_id, locked)
            logger.info(f"锁定状态设置 [{scene_name}] ID:{scene_item_id}: {'锁定' if locked else '解锁'}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置锁定状态失败: {e}")
            raise

    def set_scene_item_position(self, scene_name: str, scene_item_id: int,
                                 x: float, y: float) -> bool:
        """
        设置场景项位置

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            x: X 坐标（像素）
            y: Y 坐标（像素）

        Returns:
            bool: 是否成功
        """
        return self.set_scene_item_transform(scene_name, scene_item_id, {
            "pos_x": x, "pos_y": y
        })

    def set_scene_item_scale(self, scene_name: str, scene_item_id: int,
                               scale_x: float, scale_y: float) -> bool:
        """
        设置场景项缩放

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            scale_x: X 缩放比例
            scale_y: Y 缩放比例

        Returns:
            bool: 是否成功
        """
        return self.set_scene_item_transform(scene_name, scene_item_id, {
            "scale_x": scale_x, "scale_y": scale_y
        })

    def set_scene_item_rotation(self, scene_name: str, scene_item_id: int,
                                  rotation: float) -> bool:
        """
        设置场景项旋转角度

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            rotation: 旋转角度（度）

        Returns:
            bool: 是否成功
        """
        return self.set_scene_item_transform(scene_name, scene_item_id, {
            "rotation": rotation
        })

    def set_scene_item_crop(self, scene_name: str, scene_item_id: int,
                              left: int = 0, right: int = 0,
                              top: int = 0, bottom: int = 0) -> bool:
        """
        设置场景项裁剪

        Args:
            scene_name: 场景名称
            scene_item_id: 场景项 ID
            left: 左边裁剪（像素）
            right: 右边裁剪（像素）
            top: 顶部裁剪（像素）
            bottom: 底部裁剪（像素）

        Returns:
            bool: 是否成功
        """
        return self.set_scene_item_transform(scene_name, scene_item_id, {
            "crop_left": left,
            "crop_right": right,
            "crop_top": top,
            "crop_bottom": bottom
        })

    # ==================== 滤镜增删改 ====================

    def add_filter(self, source_name: str, filter_name: str,
                   filter_kind: str,
                   filter_settings: Optional[Dict[str, Any]] = None) -> bool:
        """
        为源添加滤镜

        Args:
            source_name: 源名称
            filter_name: 滤镜名称
            filter_kind: 滤镜类型（如 "color_filter", "sharpness_filter"）
            filter_settings: 滤镜初始参数

        Returns:
            bool: 是否成功
        """
        try:
            self.req.create_source_filter(
                source_name, filter_name, filter_kind,
                filter_settings=filter_settings or {}
            )
            logger.info(f"滤镜添加成功 [{source_name}/{filter_name}]")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"添加滤镜失败 [{source_name}/{filter_name}]: {e}")
            raise

    def remove_filter(self, source_name: str, filter_name: str) -> bool:
        """
        从源移除滤镜

        Args:
            source_name: 源名称
            filter_name: 滤镜名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.remove_source_filter(source_name, filter_name)
            logger.info(f"滤镜移除成功 [{source_name}/{filter_name}]")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"移除滤镜失败 [{source_name}/{filter_name}]: {e}")
            raise

    def rename_filter(self, source_name: str, old_name: str,
                      new_name: str) -> bool:
        """
        重命名源上的滤镜

        Args:
            source_name: 源名称
            old_name: 原滤镜名称
            new_name: 新滤镜名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_source_filter_name(source_name, old_name, new_name)
            logger.info(f"滤镜重命名 [{source_name}]: {old_name} -> {new_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"重命名滤镜失败: {e}")
            raise

    def get_filter(self, source_name: str, filter_name: str) -> Dict[str, Any]:
        """
        获取滤镜详细信息

        Args:
            source_name: 源名称
            filter_name: 滤镜名称

        Returns:
            dict: 滤镜信息
        """
        try:
            resp = self.req.get_source_filter(source_name, filter_name)
            return {
                "name": resp.filter_name,
                "kind": resp.filter_kind,
                "type": resp.filter_type,
                "enabled": resp.filter_enabled,
                "settings": resp.filter_settings
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取滤镜信息失败 [{source_name}/{filter_name}]: {e}")
            raise

    def reorder_filters(self, source_name: str, filter_name: str,
                        new_index: int) -> bool:
        """
        调整滤镜顺序

        Args:
            source_name: 源名称
            filter_name: 滤镜名称
            new_index: 新的索引位置

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_source_filter_index(source_name, filter_name, new_index)
            logger.info(f"滤镜顺序调整 [{source_name}/{filter_name}] -> {new_index}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"调整滤镜顺序失败: {e}")
            raise

    def get_filter_kinds(self, source_kind: str) -> List[str]:
        """
        获取指定源类型可用的滤镜类型列表

        Args:
            source_kind: 源类型

        Returns:
            list: 可用的滤镜类型列表
        """
        try:
            resp = self.req.get_source_filter_kind_list(source_kind)
            return list(resp.filter_kinds)
        except OBSSDKRequestError as e:
            logger.error(f"获取滤镜类型列表失败 [{source_kind}]: {e}")
            raise

    # ==================== 滤镜预设管理 ====================

    def apply_filter_preset(self, source_name: str, preset_name: str) -> bool:
        """
        应用滤镜预设到指定源

        Args:
            source_name: 源名称
            preset_name: 预设名称（见 FILTER_PRESETS 字典）

        Returns:
            bool: 是否成功

        Example:
            obs.apply_filter_preset("摄像头", "灰度")
            obs.apply_filter_preset("显示器捕获", "美颜-轻度")
        """
        if preset_name not in FILTER_PRESETS:
            logger.error(f"未知的滤镜预设: {preset_name}")
            raise ValueError(f"未知的滤镜预设: {preset_name}，可用预设: {list(FILTER_PRESETS.keys())}")

        preset = FILTER_PRESETS[preset_name]

        # 如果滤镜不存在则创建，否则更新设置
        existing_filters = self.get_filter_list(source_name)
        existing_names = [f["name"] for f in existing_filters]

        if preset.name not in existing_names:
            self.add_filter(source_name, preset.name, preset.filter_kind,
                            preset.settings)
        else:
            self.set_filter_settings(source_name, preset.name, preset.settings,
                                     overlay=False)

        if preset.enabled:
            self.set_filter_enabled(source_name, preset.name, True)

        logger.info(f"滤镜预设应用 [{source_name}]: {preset_name}")
        return True

    def list_filter_presets(self) -> List[str]:
        """获取所有可用滤镜预设名称"""
        return list(FILTER_PRESETS.keys())

    def add_custom_filter_preset(self, name: str, filter_kind: str,
                                  filter_type: str,
                                  settings: Dict[str, Any]) -> None:
        """
        添加自定义滤镜预设

        Args:
            name: 预设名称
            filter_kind: 滤镜类型
            filter_type: 滤镜显示名称
            settings: 滤镜参数
        """
        FILTER_PRESETS[name] = FilterPreset(
            name=name,
            filter_kind=filter_kind,
            filter_type=filter_type,
            settings=settings
        )
        logger.info(f"自定义滤镜预设已添加: {name}")

    # ==================== 录制章节 & 文件管理 ====================

    def split_record(self) -> bool:
        """
        分割当前录制文件（创建新文件继续录制）

        Returns:
            bool: 是否成功
        """
        try:
            self.req.split_record_file()
            logger.info("录制文件已分割")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"分割录制文件失败: {e}")
            raise

    def create_record_chapter(self, chapter_name: Optional[str] = None) -> bool:
        """
        在当前录制文件中创建章节标记

        Args:
            chapter_name: 章节名称（可选）

        Returns:
            bool: 是否成功
        """
        try:
            self.req.create_record_chapter(chapter_name=chapter_name)
            logger.info(f"录制章节已创建: {chapter_name or '(未命名)'}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"创建录制章节失败: {e}")
            raise

    def get_record_directory(self) -> str:
        """
        获取录制保存目录

        Returns:
            str: 录制目录路径
        """
        try:
            resp = self.req.get_record_directory()
            return resp.record_directory
        except OBSSDKRequestError as e:
            logger.error(f"获取录制目录失败: {e}")
            raise

    def set_record_directory(self, directory: str) -> bool:
        """
        设置录制保存目录

        Args:
            directory: 目标目录路径

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_record_directory(directory)
            logger.info(f"录制目录设置: {directory}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置录制目录失败: {e}")
            raise

    # ==================== 推流服务配置 ====================

    def get_stream_service_settings(self) -> Dict[str, Any]:
        """
        获取推流服务配置

        Returns:
            dict: 包含 stream_service_type 和 stream_service_settings
        """
        try:
            resp = self.req.get_stream_service_settings()
            return {
                "stream_service_type": resp.stream_service_type,
                "stream_service_settings": resp.stream_service_settings
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取推流服务配置失败: {e}")
            raise

    def set_stream_service_settings(
        self,
        stream_service_type: str,
        server: str,
        key: str
    ) -> bool:
        """
        设置推流服务配置（切换推流平台）

        Args:
            stream_service_type: 服务类型，如 "rtmp_custom"（自定义）或 "rtmp_common"（通用）
            server: 推流服务器地址
            key: 推流密钥

        Returns:
            bool: 是否成功

        Example:
            obs.set_stream_service_settings(
                "rtmp_custom",
                "rtmp://live.example.com/app",
                "your-stream-key"
            )
        """
        try:
            settings = {"server": server, "key": key}
            self.req.set_stream_service_settings(stream_service_type, settings)
            logger.info(f"推流服务配置已更新: {stream_service_type}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置推流服务配置失败: {e}")
            raise

    def send_stream_caption(self, caption_text: str) -> bool:
        """
        发送字幕到推流输出

        Args:
            caption_text: 字幕文本

        Returns:
            bool: 是否成功
        """
        try:
            self.req.send_stream_caption(caption_text)
            logger.debug(f"字幕发送: {caption_text[:50]}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"发送字幕失败: {e}")
            raise

    # ==================== 回放缓冲 (Replay Buffer) ====================

    def get_replay_buffer_status(self) -> Dict[str, Any]:
        """
        获取回放缓冲状态

        Returns:
            dict: 包含 output_active 和 output_state
        """
        try:
            resp = self.req.get_replay_buffer_status()
            return {
                "output_active": resp.output_active,
                "output_state": getattr(resp, 'output_state', None)
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取回放缓冲状态失败: {e}")
            raise

    def start_replay_buffer(self) -> bool:
        """
        启动回放缓冲

        Returns:
            bool: 是否成功
        """
        try:
            self.req.start_replay_buffer()
            logger.info("回放缓冲已启动")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"启动回放缓冲失败: {e}")
            raise

    def stop_replay_buffer(self) -> bool:
        """
        停止回放缓冲

        Returns:
            bool: 是否成功
        """
        try:
            self.req.stop_replay_buffer()
            logger.info("回放缓冲已停止")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"停止回放缓冲失败: {e}")
            raise

    def toggle_replay_buffer(self) -> bool:
        """
        切换回放缓冲状态

        Returns:
            bool: 当前回放缓冲是否激活
        """
        try:
            resp = self.req.toggle_replay_buffer()
            logger.info(f"回放缓冲切换: {'启动' if resp.output_active else '已停止'}")
            return resp.output_active
        except OBSSDKRequestError as e:
            logger.error(f"切换回放缓冲失败: {e}")
            raise

    def save_replay_buffer(self) -> bool:
        """
        保存当前回放缓冲内容为文件

        Returns:
            bool: 是否成功
        """
        try:
            self.req.save_replay_buffer()
            logger.info("回放缓冲已保存")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"保存回放缓冲失败: {e}")
            raise

    def get_last_replay(self) -> Optional[str]:
        """
        获取上次保存的回放文件路径

        Returns:
            str: 回放文件路径，或 None
        """
        try:
            resp = self.req.get_last_replay_buffer_replay()
            return getattr(resp, 'saved_replay_path', None)
        except OBSSDKRequestError as e:
            logger.error(f"获取上次回放失败: {e}")
            raise

    # ==================== 回放 & 截图事件监听 ====================

    def on_replay_buffer_saved(self, func: Callable) -> None:
        """注册回放缓冲保存事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_screenshot_saved(self, func: Callable) -> None:
        """注册截图保存事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    # ==================== 音频电平实时监控 ====================

    def setup_volume_meter_listener(self, callback: Callable,
                                      interval_ms: int = 50) -> None:
        """
        设置音频电平实时监听（高频事件，每 50ms 更新）

        Args:
            callback: 回调函数，签名为 callback(volume_data: dict)
                      volume_data 格式: {
                          "inputs": [{
                              "input_name": "Mic",
                              "input_volume_mul": 0.5,
                              "input_volume_db": -6.0
                          }, ...]
                      }
        """
        self.setup_event_client(subs=obs.Subs.HIGH_VOLUME)

        def wrapper(data):
            attrs = data.attrs()
            callback(attrs)

        self.event_client.callback.register(wrapper)
        logger.info(f"音量电平监听已启动 (间隔 ~{interval_ms}ms)")

    def get_input_volume_level(self, input_name: str) -> Dict[str, float]:
        """
        获取输入源的实时音量电平（需先启动音量监听）

        Args:
            input_name: 输入源名称

        Returns:
            dict: 包含 input_volume_mul 和 input_volume_db

        Note:
            此方法需要先通过 setup_volume_meter_listener 注册监听
        """
        try:
            resp = self.req.get_input_volume(input_name)
            return {
                "input_volume_mul": resp.input_volume_mul,
                "input_volume_db": resp.input_volume_db
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取音量电平失败 [{input_name}]: {e}")
            raise

    # ==================== 输入音频轨道控制 ====================

    def get_input_audio_tracks(self, input_name: str) -> Dict[str, bool]:
        """
        获取输入源的音频轨道启用状态

        Args:
            input_name: 输入源名称

        Returns:
            dict: 轨道启用状态，键为 "1"-"6"，值为 bool
        """
        try:
            resp = self.req.get_input_audio_tracks(input_name)
            return dict(resp.input_audio_tracks)
        except OBSSDKRequestError as e:
            logger.error(f"获取音频轨道失败 [{input_name}]: {e}")
            raise

    def set_input_audio_tracks(self, input_name: str,
                                 tracks: Dict[str, bool]) -> bool:
        """
        设置输入源的音频轨道启用状态

        Args:
            input_name: 输入源名称
            tracks: 轨道状态字典，如 {"1": True, "2": False, "3": True}

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_input_audio_tracks(input_name, tracks)
            logger.info(f"音频轨道设置 [{input_name}]: {tracks}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置音频轨道失败 [{input_name}]: {e}")
            raise

    def enable_audio_track(self, input_name: str, track_num: int) -> bool:
        """
        启用输入源的指定音频轨道

        Args:
            input_name: 输入源名称
            track_num: 轨道编号（1-6）

        Returns:
            bool: 是否成功
        """
        current = self.get_input_audio_tracks(input_name)
        current[str(track_num)] = True
        return self.set_input_audio_tracks(input_name, current)

    def disable_audio_track(self, input_name: str, track_num: int) -> bool:
        """
        禁用输入源的指定音频轨道

        Args:
            input_name: 输入源名称
            track_num: 轨道编号（1-6）

        Returns:
            bool: 是否成功
        """
        current = self.get_input_audio_tracks(input_name)
        current[str(track_num)] = False
        return self.set_input_audio_tracks(input_name, current)

    # ==================== 特殊音频输入快捷获取 ====================

    def get_special_inputs(self) -> Dict[str, str]:
        """
        获取 OBS 特殊音频输入（桌面音频、麦克风1-4）

        Returns:
            dict: 键为 desktop1/2, mic1/2/3/4，值为输入源名称
        """
        try:
            resp = self.req.get_special_inputs()
            return {
                "desktop1": resp.desktop1,
                "desktop2": resp.desktop2,
                "mic1": resp.mic1,
                "mic2": resp.mic2,
                "mic3": resp.mic3,
                "mic4": resp.mic4
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取特殊音频输入失败: {e}")
            raise

    # ==================== 输入类型管理 ====================

    def get_input_kinds(self, unversioned: bool = True) -> List[str]:
        """
        获取所有可用的输入源类型

        Args:
            unversioned: True=返回无版本后缀的类型名，False=带版本

        Returns:
            list: 输入类型列表
        """
        try:
            resp = self.req.get_input_kind_list(unversioned=unversioned)
            return list(resp.input_kinds)
        except OBSSDKRequestError as e:
            logger.error(f"获取输入类型列表失败: {e}")
            raise

    def get_input_default_settings(self, input_kind: str) -> Dict[str, Any]:
        """
        获取指定输入类型的默认设置

        Args:
            input_kind: 输入类型（如 "vlc_source", "browser_source"）

        Returns:
            dict: 默认设置对象
        """
        try:
            resp = self.req.get_input_default_settings(input_kind)
            return dict(resp.default_input_settings)
        except OBSSDKRequestError as e:
            logger.error(f"获取默认设置失败 [{input_kind}]: {e}")
            raise

    # ==================== 输入源增删改 ====================

    def create_input(
        self,
        input_name: str,
        input_kind: str,
        input_settings: Optional[Dict[str, Any]] = None,
        scene_name: Optional[str] = None
    ) -> str:
        """
        创建新输入源

        Args:
            input_name: 输入源名称
            input_kind: 输入类型（如 "browser_source", "vlc_source"）
            input_settings: 初始设置
            scene_name: 可选，指定添加到某场景

        Returns:
            str: 创建的输入源 UUID
        """
        try:
            resp = self.req.create_input(
                input_name=input_name,
                input_kind=input_kind,
                input_settings=input_settings or {},
                scene_name=scene_name
            )
            logger.info(f"输入源创建成功: {input_name} ({input_kind})")
            return resp.input_uuid
        except OBSSDKRequestError as e:
            logger.error(f"创建输入源失败 [{input_name}]: {e}")
            raise

    def remove_input(self, input_name: str) -> bool:
        """
        删除输入源

        Args:
            input_name: 输入源名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.remove_input(input_name)
            logger.info(f"输入源删除成功: {input_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"删除输入源失败 [{input_name}]: {e}")
            raise

    def rename_input(self, old_name: str, new_name: str) -> bool:
        """
        重命名输入源

        Args:
            old_name: 原名称
            new_name: 新名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_input_name(old_name, new_name)
            logger.info(f"输入源重命名: {old_name} -> {new_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"重命名输入源失败: {e}")
            raise

    # ==================== 音频监听类型控制 ====================

    def get_input_monitor_type(self, input_name: str) -> str:
        """
        获取输入源的音频监听类型

        Args:
            input_name: 输入源名称

        Returns:
            str: 监听类型
        """
        try:
            resp = self.req.get_input_audio_monitor_type(input_name)
            return resp.monitor_type
        except OBSSDKRequestError as e:
            logger.error(f"获取监听类型失败 [{input_name}]: {e}")
            raise

    def set_input_monitor_type(self, input_name: str,
                                 monitor_type: Union[str, MonitorType]) -> bool:
        """
        设置输入源的音频监听类型

        Args:
            input_name: 输入源名称
            monitor_type: 监听类型（字符串或 MonitorType 枚举）:
                - "OBS_MONITORING_TYPE_NONE"          (关闭监听)
                - "OBS_MONITORING_TYPE_MONITOR_ONLY"  (仅监听)
                - "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT" (监听并输出)

        Returns:
            bool: 是否成功
        """
        try:
            mtype = monitor_type.value if isinstance(monitor_type, MonitorType) else monitor_type
            self.req.set_input_audio_monitor_type(input_name, mtype)
            logger.info(f"监听类型设置 [{input_name}]: {mtype}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置监听类型失败 [{input_name}]: {e}")
            raise

    # ==================== 音频平衡控制 ====================

    def get_input_audio_balance(self, input_name: str) -> float:
        """
        获取输入源的音频平衡（左右声道比例）

        Args:
            input_name: 输入源名称

        Returns:
            float: 平衡值 0.0（完全左）~ 1.0（完全右），0.5 为居中
        """
        try:
            resp = self.req.get_input_audio_balance(input_name)
            return resp.input_audio_balance
        except OBSSDKRequestError as e:
            logger.error(f"获取音频平衡失败 [{input_name}]: {e}")
            raise

    def set_input_audio_balance(self, input_name: str, balance: float) -> float:
        """
        设置输入源的音频平衡

        Args:
            input_name: 输入源名称
            balance: 平衡值 0.0（完全左）~ 1.0（完全右）

        Returns:
            float: 设置后的平衡值
        """
        try:
            resp = self.req.set_input_audio_balance(input_name, balance)
            logger.info(f"音频平衡设置 [{input_name}]: {balance}")
            return resp.input_audio_balance
        except OBSSDKRequestError as e:
            logger.error(f"设置音频平衡失败 [{input_name}]: {e}")
            raise

    # ==================== 场景转场精细控制 ====================

    def get_transition_cursor(self) -> float:
        """
        获取当前转场的游标位置（0.0 ~ 1.0）

        Returns:
            float: 转场游标位置
        """
        try:
            resp = self.req.get_current_scene_transition_cursor()
            return resp.transition_cursor
        except OBSSDKRequestError as e:
            logger.error(f"获取转场游标失败: {e}")
            raise

    def get_transition_kind_list(self) -> List[str]:
        """
        获取所有可用的转场类型名称

        Returns:
            list: 转场类型列表
        """
        try:
            resp = self.req.get_transition_kind_list()
            return list(resp.transition_kinds)
        except OBSSDKRequestError as e:
            logger.error(f"获取转场类型列表失败: {e}")
            raise

    def set_transition_settings(self, transition_settings: Dict[str, Any],
                                 overlay: bool = True) -> bool:
        """
        设置当前转场的自定义参数

        Args:
            transition_settings: 转场参数对象
            overlay: True=叠加当前设置，False=替换

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_current_scene_transition_settings(
                transition_settings, overlay
            )
            logger.info("转场参数已更新")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置转场参数失败: {e}")
            raise

    def trigger_studio_mode_transition(self) -> bool:
        """
        触发演播室模式转场（将预览场景切换到节目）

        Returns:
            bool: 是否成功
        """
        try:
            self.req.trigger_studio_mode_transition()
            logger.info("演播室模式转场已触发")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"触发转场失败: {e}")
            raise

    def set_tbar_position(self, position: float, release: bool = True) -> bool:
        """
        设置 T 栏（软切）位置

        Args:
            position: 位置值（0.0 ~ 1.0）
            release: True=释放 T 栏，False=保持锁定

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_tbar_position(position, release)
            logger.info(f"T栏位置设置: {position} (release={release})")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置T栏位置失败: {e}")
            raise

    # ==================== 场景转场覆盖 ====================

    def get_scene_transition_override(self, scene_name: str) -> Optional[Dict[str, Any]]:
        """
        获取场景的转场覆盖设置

        Args:
            scene_name: 场景名称

        Returns:
            dict: 包含 transition_name 和 transition_duration，或 None（无覆盖）
        """
        try:
            resp = self.req.get_scene_scene_transition_override(scene_name)
            if resp.transition_name is None:
                return None
            return {
                "transition_name": resp.transition_name,
                "transition_duration": resp.transition_duration
            }
        except OBSSDKRequestError as e:
            logger.error(f"获取场景转场覆盖失败 [{scene_name}]: {e}")
            raise

    def set_scene_transition_override(
        self,
        scene_name: str,
        transition_name: Optional[str] = None,
        transition_duration: Optional[int] = None
    ) -> bool:
        """
        设置场景的转场覆盖（该场景专属转场）

        Args:
            scene_name: 场景名称
            transition_name: 转场名称（None=清除覆盖，使用全局转场）
            transition_duration: 转场时长（毫秒，None=保持不变）

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_scene_scene_transition_override(
                scene_name, transition_name, transition_duration
            )
            if transition_name:
                logger.info(f"场景转场覆盖设置 [{scene_name}]: {transition_name} ({transition_duration}ms)")
            else:
                logger.info(f"场景转场覆盖已清除 [{scene_name}]")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置场景转场覆盖失败 [{scene_name}]: {e}")
            raise

    # ==================== 分组管理 ====================

    def get_group_list(self) -> List[str]:
        """
        获取所有分组名称列表

        Returns:
            list: 分组名称列表
        """
        try:
            resp = self.req.get_group_list()
            return list(resp.groups)
        except OBSSDKRequestError as e:
            logger.error(f"获取分组列表失败: {e}")
            raise

    def get_group_items(self, group_name: str) -> List[Dict[str, Any]]:
        """
        获取分组中的所有场景项

        Args:
            group_name: 分组名称

        Returns:
            list: 场景项列表
        """
        try:
            resp = self.req.get_group_scene_item_list(group_name)
            # obsws-python 返回 dict 列表（驼峰 key）
            return [
                {
                    "scene_item_id": item["sceneItemId"],
                    "source_name": item["sourceName"],
                    "source_type": item["sourceType"],
                    "enabled": item.get("sceneItemEnabled", True)
                }
                for item in resp.scene_items
            ]
        except OBSSDKRequestError as e:
            logger.error(f"获取分组项列表失败 [{group_name}]: {e}")
            raise

    # ==================== 演播室模式 ====================

    def get_current_preview_scene(self) -> str:
        """
        获取当前预览场景（仅在演播室模式下有效）

        Returns:
            str: 预览场景名称，不在 Studio 模式时返回空字符串
        """
        try:
            resp = self.req.get_current_preview_scene()
            return resp.scene_name
        except OBSSDKRequestError:
            # 不在 Studio 模式时返回空字符串（正常情况）
            return ""

    def set_current_preview_scene(self, scene_name: str) -> bool:
        """
        设置当前预览场景（仅在演播室模式下有效）

        Args:
            scene_name: 预览场景名称

        Returns:
            bool: 是否成功
        """
        try:
            self.req.set_current_preview_scene(scene_name)
            logger.info(f"预览场景设置: {scene_name}")
            return True
        except OBSSDKRequestError as e:
            logger.error(f"设置预览场景失败 [{scene_name}]: {e}")
            raise

    def on_studio_mode_changed(self, func: Callable) -> None:
        """注册演播室模式状态变更回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    # ==================== 批量请求 ====================

    def batch_request(self, requests: List[Dict[str, Any]]) -> List[Any]:
        """
        批量发送多个请求（减少网络往返延迟）

        Args:
            requests: 请求列表，每个元素格式:
                {
                    "request_type": "GetVersion",      # 必填，请求类型
                    "request_id": "req1",             # 可选，请求ID（用于匹配响应）
                    "request_data": {...}              # 可选，请求参数
                }

        Returns:
            list: 响应列表，顺序与请求列表对应
        """
        try:
            responses = self.req.send_batch(requests)
            return responses
        except OBSSDKRequestError as e:
            logger.error(f"批量请求失败: {e}")
            raise

    # ==================== 自动重连 & 心跳机制 ====================

    def enable_auto_reconnect(self, interval: float = 5.0,
                               on_reconnect: Optional[Callable] = None) -> None:
        """
        启用自动重连机制

        Args:
            interval: 重连间隔（秒），默认 5 秒
            on_reconnect: 重连成功后调用的回调函数
        """
        self._reconnect_interval = interval
        self._running = True

        if on_reconnect:
            self._on_reconnect_callbacks.append(on_reconnect)

        def reconnect_worker():
            while self._running:
                try:
                    # 尝试发送一个简单请求检测连接
                    self.req.get_version()
                    time.sleep(interval)
                except (OBSSDKError, Exception) as e:
                    logger.warning(f"连接断开，{interval}秒后重连... ({e})")
                    time.sleep(interval)
                    if self._running:
                        try:
                            self.req = obs.ReqClient(
                                host=self.host,
                                port=self.port,
                                password=self.password,
                                timeout=self.timeout
                            )
                            logger.info("重连成功")
                            for cb in self._on_reconnect_callbacks:
                                try:
                                    cb()
                                except Exception:
                                    pass
                        except Exception as re:
                            logger.error(f"重连失败: {re}")

        if self._reconnect_thread is None or not self._reconnect_thread.is_alive():
            self._reconnect_thread = threading.Thread(
                target=reconnect_worker, daemon=True
            )
            self._reconnect_thread.start()
            logger.info(f"自动重连已启用 (间隔 {interval}s)")

    def disable_auto_reconnect(self) -> None:
        """禁用自动重连"""
        self._running = False
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            logger.info("自动重连已禁用")

    def start_heartbeat(self, interval: float = 30.0,
                        callback: Optional[Callable[[Dict], None]] = None) -> None:
        """
        启动心跳/状态监控线程

        Args:
            interval: 心跳间隔（秒），默认 30 秒
            callback: 每次心跳时调用的回调，接收状态字典
        """
        self._heartbeat_interval = interval
        self._running = True

        def heartbeat_worker():
            while self._running:
                try:
                    stats = self.get_stats()
                    if callback:
                        callback(stats)
                    time.sleep(interval)
                except Exception as e:
                    logger.error(f"心跳请求失败: {e}")
                    time.sleep(interval)

        if self._heartbeat_thread is None or not self._heartbeat_thread.is_alive():
            self._heartbeat_thread = threading.Thread(
                target=heartbeat_worker, daemon=True
            )
            self._heartbeat_thread.start()
            logger.info(f"心跳监控已启动 (间隔 {interval}s)")

    def stop_heartbeat(self) -> None:
        """停止心跳监控"""
        self._running = False
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            logger.info("心跳监控已停止")

    def is_connected(self) -> bool:
        """
        检测当前连接是否存活

        Returns:
            bool: 是否连接正常
        """
        try:
            self.req.get_version()
            return True
        except Exception:
            return False

    # ==================== 完整状态快照 & 恢复 ====================

    def snapshot_state(self) -> Dict[str, Any]:
        """
        保存当前 OBS 完整状态快照

        Returns:
            dict: 包含所有状态信息的快照
        """
        try:
            scene_list = self.get_scene_list()
            current_scene = scene_list["current_program_scene"]
            scenes_info = {}

            for scene in scene_list["scenes"]:
                sname = scene["name"]
                items = self.get_scene_items(sname)
                scenes_info[sname] = {
                    "items": items,
                    "transition_override": self.get_scene_transition_override(sname)
                }

            inputs = self.get_input_list()
            audio_states = {}
            for inp in inputs:
                try:
                    audio_states[inp["name"]] = {
                        "volume_db": self.get_input_volume(inp["name"])["volume_db"],
                        "muted": self.get_input_mute(inp["name"]),
                        "audio_balance": self.get_input_audio_balance(inp["name"]),
                        "audio_tracks": self.get_input_audio_tracks(inp["name"]),
                        "monitor_type": self.get_input_monitor_type(inp["name"])
                    }
                except Exception:
                    pass

            return {
                "current_scene": current_scene,
                "preview_scene": scene_list.get("current_preview_scene"),
                "transition": self.get_current_transition(),
                "transition_duration": self.get_transition_cursor(),
                "scenes": scenes_info,
                "audio_states": audio_states,
                "record_status": self.get_record_status(),
                "stream_status": self.get_stream_status(),
                "timestamp": time.time()
            }
        except Exception as e:
            logger.error(f"状态快照失败: {e}")
            raise

    def restore_state(self, snapshot: Dict[str, Any],
                       restore_inputs: bool = True,
                       restore_scenes: bool = True) -> None:
        """
        恢复之前保存的状态快照

        Args:
            snapshot: 状态快照（由 snapshot_state 生成）
            restore_inputs: 是否恢复音频状态
            restore_scenes: 是否恢复场景项启用状态
        """
        try:
            # 切换场景
            if restore_scenes and "current_scene" in snapshot:
                self.set_current_scene(snapshot["current_scene"])

            # 恢复音频状态
            if restore_inputs and "audio_states" in snapshot:
                for inp_name, state in snapshot["audio_states"].items():
                    try:
                        self.set_input_volume(inp_name, volume_db=state["volume_db"])
                        self.set_input_mute(inp_name, state["muted"])
                        self.set_input_audio_balance(inp_name, state["audio_balance"])
                        self.set_input_audio_tracks(inp_name, state["audio_tracks"])
                        self.set_input_monitor_type(inp_name, state["monitor_type"])
                    except Exception as e:
                        logger.warning(f"恢复音频状态失败 [{inp_name}]: {e}")

            logger.info("状态恢复完成")
        except Exception as e:
            logger.error(f"状态恢复失败: {e}")
            raise

    def save_state_to_file(self, filepath: str,
                             include_stats: bool = True) -> None:
        """
        将状态快照保存到文件

        Args:
            filepath: 保存路径
            include_stats: 是否包含实时统计数据
        """
        import json
        snapshot = self.snapshot_state()
        if not include_stats:
            snapshot.pop("record_status", None)
            snapshot.pop("stream_status", None)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        logger.info(f"状态快照已保存: {filepath}")

    def load_state_from_file(self, filepath: str) -> None:
        """
        从文件加载状态快照并恢复

        Args:
            filepath: 快照文件路径
        """
        import json
        with open(filepath, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        self.restore_state(snapshot)
        logger.info(f"状态快照已加载: {filepath}")

    # ==================== 脚本化场景切换动画 ====================

    def animate_scene_switch(
        self,
        target_scene: str,
        duration: float = 1.0,
        easing: str = "linear",
        fade_audio: bool = True,
        source_name: Optional[str] = None,
        target_volume_db: float = 0.0,
        source_volume_db: float = 0.0
    ) -> bool:
        """
        带动画的场景切换（音量淡入淡出 + 场景切换）

        Args:
            target_scene: 目标场景名称
            duration: 总动画时长（秒）
            easing: 缓动函数（"linear", "ease_in", "ease_out", "ease_in_out"）
            fade_audio: 是否同时做音量淡入淡出
            source_name: 需要淡出的音频源名称（可选）
            target_volume_db: 切换后目标音频源的音量（dB）
            source_volume_db: 切换前当前音频源的音量（dB）

        Returns:
            bool: 是否成功
        """
        steps = 50
        step_duration = duration / steps

        # 预定义缓动函数
        easing_funcs = {
            "linear": lambda t: t,
            "ease_in": lambda t: t * t,
            "ease_out": lambda t: t * (2 - t),
            "ease_in_out": lambda t: t * t * (3 - 2 * t) if t < 0.5 else (4 - t) * (t - 1)
        }
        ease = easing_funcs.get(easing, easing_funcs["linear"])

        try:
            # 如果需要淡出当前音频
            if fade_audio and source_name:
                source_start_volume = self.get_input_volume(source_name)["volume_db"]
                for i in range(steps):
                    progress = ease((steps - i - 1) / steps)
                    new_volume = source_start_volume + (source_volume_db - source_start_volume) * progress
                    self.set_input_volume(source_name, volume_db=new_volume)
                    time.sleep(step_duration)

            # 执行场景切换
            self.set_current_scene(target_scene)
            logger.info(f"场景切换动画完成 -> {target_scene}")

            # 如果需要淡入新音频
            if fade_audio and source_name:
                for i in range(steps):
                    progress = ease(i / steps)
                    new_volume = source_volume_db + (target_volume_db - source_volume_db) * progress
                    self.set_input_volume(source_name, volume_db=new_volume)
                    time.sleep(step_duration)

            return True
        except Exception as e:
            logger.error(f"场景切换动画失败: {e}")
            raise

    def fade_volume(
        self,
        input_name: str,
        from_volume_db: Optional[float] = None,
        to_volume_db: float = -60.0,
        duration: float = 1.0,
        easing: str = "ease_in_out"
    ) -> bool:
        """
        音量淡入淡出动画

        Args:
            input_name: 输入源名称
            from_volume_db: 起始音量（dB），None=当前音量
            to_volume_db: 目标音量（dB）
            duration: 动画时长（秒）
            easing: 缓动函数

        Returns:
            bool: 是否成功
        """
        steps = 50
        step_duration = duration / steps

        easing_funcs = {
            "linear": lambda t: t,
            "ease_in": lambda t: t * t,
            "ease_out": lambda t: t * (2 - t),
            "ease_in_out": lambda t: t * t * (3 - 2 * t) if t < 0.5 else (4 - t) * (t - 1)
        }
        ease = easing_funcs.get(easing, easing_funcs["linear"])

        try:
            if from_volume_db is None:
                from_volume_db = self.get_input_volume(input_name)["volume_db"]

            for i in range(steps):
                progress = ease(i / steps)
                new_volume = from_volume_db + (to_volume_db - from_volume_db) * progress
                self.set_input_volume(input_name, volume_db=new_volume)
                time.sleep(step_duration)

            logger.info(f"音量淡出完成 [{input_name}]: {from_volume_db}dB -> {to_volume_db}dB")
            return True
        except Exception as e:
            logger.error(f"音量淡出失败: {e}")
            raise

    # ==================== 更多事件监听 ====================

    def on_input_created(self, func: Callable) -> None:
        """注册输入源创建事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_input_removed(self, func: Callable) -> None:
        """注册输入源删除事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_input_volume_changed(self, func: Callable) -> None:
        """注册输入音量变更事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_transition_started(self, func: Callable) -> None:
        """注册转场开始事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_transition_ended(self, func: Callable) -> None:
        """注册转场结束事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_media_ended(self, func: Callable) -> None:
        """注册媒体播放结束事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    def on_media_started(self, func: Callable) -> None:
        """注册媒体播放开始事件回调"""
        self.setup_event_client()
        self.event_client.callback.register(func)

    # 截图与画面捕获方法见上方 get_source_screenshot / save_source_screenshot 等


# ==================== 使用示例 ====================

if __name__ == "__main__":
    obs_ctrl = OBSController(
        host="localhost",
        port=4455,
        password=""
    )

    # 基本状态
    ver = obs_ctrl.get_version()
    print(f"OBS 版本: {ver['obs_version']}")

    # 场景管理
    scenes = obs_ctrl.get_scene_names()
    print(f"场景列表: {scenes}")
    cur = obs_ctrl.get_current_scene()
    print(f"当前场景: {cur}")

    # 截图
    b64 = obs_ctrl.get_source_screenshot(cur, "jpg", 320, 180, 50)
    print(f"截图 Base64 长度: {len(b64)}")

    # 状态摘要
    summary = obs_ctrl.get_summary()
    print(f"状态摘要: {summary}")
