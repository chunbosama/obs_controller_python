"""
gui/tab_scene.py  ——  场景管理标签页（PyQt5 版）
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QTableWidget, QTableWidgetItem,
    QSplitter, QListWidgetItem, QMenu, QInputDialog, QMessageBox,
    QAbstractItemView, QLabel, QHeaderView,
)
from PyQt5.QtCore import Qt, QPoint

from .utils import run_in_thread, FONT_BOLD

if TYPE_CHECKING:
    from .app import OBSGui


class SceneTab(QWidget):
    """场景管理：左侧场景列表，右侧场景项表格。"""

    def __init__(self, parent, app: "OBSGui"):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # ── 左列：场景列表 ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        left_layout.addWidget(QLabel("场景列表"))

        self.scene_list = QListWidget()
        self.scene_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scene_list.itemClicked.connect(self._on_scene_select)
        self.scene_list.itemDoubleClicked.connect(self._on_scene_dbl)
        self.scene_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scene_list.customContextMenuRequested.connect(self._show_context_menu)
        left_layout.addWidget(self.scene_list)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_switch = QPushButton("切换")
        btn_switch.clicked.connect(self._switch_scene)
        btn_row.addWidget(btn_switch)

        btn_create = QPushButton("新建")
        btn_create.setProperty("success", True)
        btn_create.clicked.connect(self._create_scene)
        btn_row.addWidget(btn_create)

        btn_delete = QPushButton("删除")
        btn_delete.setProperty("danger", True)
        btn_delete.clicked.connect(self._delete_scene)
        btn_row.addWidget(btn_delete)

        btn_rename = QPushButton("重命名")
        btn_rename.setProperty("warning", True)
        btn_rename.clicked.connect(self._rename_scene)
        btn_row.addWidget(btn_rename)

        btn_refresh = QPushButton("🔄")
        btn_refresh.setProperty("outline", True)
        btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(btn_refresh)

        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        # ── 右列：场景项表格 ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        right_layout.addWidget(QLabel("场景项（单击场景查看）"))

        self.item_table = QTableWidget(0, 3)
        self.item_table.setHorizontalHeaderLabels(["名称", "类型", "启用"])
        self.item_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.item_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.item_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.item_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right_layout.addWidget(self.item_table)

        # 场景项操作
        item_btn_row = QHBoxLayout()
        btn_toggle = QPushButton("启用/禁用")
        btn_toggle.setProperty("warning", True)
        btn_toggle.clicked.connect(self._toggle_item)
        item_btn_row.addWidget(btn_toggle)

        btn_del_item = QPushButton("删除项")
        btn_del_item.setProperty("danger", True)
        btn_del_item.clicked.connect(self._delete_item)
        item_btn_row.addWidget(btn_del_item)

        right_layout.addLayout(item_btn_row)
        splitter.addWidget(right)

        # 使用比例而不是固定值
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # 右键菜单
        self._ctx_menu = QMenu(self)
        self._ctx_menu.addAction("切换到此场景", self._switch_scene)
        self._ctx_menu.addAction("重命名", self._rename_scene)
        self._ctx_menu.addSeparator()
        self._ctx_menu.addAction("删除", self._delete_scene)

    # ── 刷新 ─────────────────────────────────────────────────

    def refresh(self) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        run_in_thread(ctrl.get_scene_names, self._on_scenes_loaded)

    def _on_scenes_loaded(self, scenes: list) -> None:
        self.scene_list.clear()
        for s in scenes:
            name = s if isinstance(s, str) else s.get("sceneName", "")
            self.scene_list.addItem(name)
        ctrl = self.app.ctrl
        if ctrl:
            run_in_thread(ctrl.get_current_scene, self._select_scene)

    def _select_scene(self, current: str) -> None:
        items = self.scene_list.findItems(current, Qt.MatchExactly)
        if items:
            self.scene_list.setCurrentItem(items[0])
            self.scene_list.scrollToItem(items[0])

    def load_items(self, scene_name: str) -> None:
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        run_in_thread(
            lambda: ctrl.get_scene_items(scene_name),
            self._on_items_loaded,
        )

    def _on_items_loaded(self, items: list) -> None:
        self.item_table.setRowCount(0)
        for item in items:
            name    = item.get("source_name", "")
            kind    = item.get("source_type", "")
            enabled = "✓" if item.get("enabled", True) else "✗"
            row = self.item_table.rowCount()
            self.item_table.insertRow(row)
            self.item_table.setItem(row, 0, QTableWidgetItem(name))
            self.item_table.setItem(row, 1, QTableWidgetItem(kind))
            self.item_table.setItem(row, 2, QTableWidgetItem(enabled))
            # 存储 scene_item_id
            self.item_table.item(row, 0).setData(Qt.UserRole, item.get("scene_item_id", ""))

    # ── 事件回调 ──────────────────────────────────────────────

    def _on_scene_dbl(self, _item) -> None:
        self._switch_scene()

    def _on_scene_select(self, item) -> None:
        scene = item.text()
        if not scene or not self.app.ctrl:
            return
        self.app.preview_scene(scene)
        self.load_items(scene)

    def _selected_scene(self) -> str | None:
        item = self.scene_list.currentItem()
        return item.text() if item else None

    def _switch_scene(self) -> None:
        scene = self._selected_scene()
        if not scene:
            return
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        self.app.log(f"切换场景 → {scene}", "INFO")
        run_in_thread(
            lambda: ctrl.set_current_scene(scene),
            lambda _: self.app.set_scene(scene),
        )

    def _create_scene(self) -> None:
        name, ok = QInputDialog.getText(self, "新建场景", "请输入场景名称：")
        if not ok or not name:
            return
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        self.app.log(f"创建场景: {name}", "SUCCESS")
        run_in_thread(lambda: ctrl.create_scene(name), lambda _: self.refresh())

    def _delete_scene(self) -> None:
        scene = self._selected_scene()
        if not scene:
            return
        reply = QMessageBox.question(
            self, "删除场景", f"确认删除场景「{scene}」？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        self.app.log(f"删除场景: {scene}", "WARNING")
        run_in_thread(lambda: ctrl.remove_scene(scene), lambda _: self.refresh())

    def _rename_scene(self) -> None:
        scene = self._selected_scene()
        if not scene:
            return
        new_name, ok = QInputDialog.getText(
            self, "重命名场景", f"请输入「{scene}」的新名称：", text=scene,
        )
        if not ok or not new_name or new_name == scene:
            return
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        self.app.log(f"重命名场景: {scene} → {new_name}", "INFO")
        run_in_thread(
            lambda: ctrl.req.set_scene_name(scene_name=scene, new_scene_name=new_name),
            lambda _: self.refresh(),
        )

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.scene_list.itemAt(pos)
        if item:
            self.scene_list.setCurrentItem(item)
            self._ctx_menu.exec_(self.scene_list.mapToGlobal(pos))

    def _toggle_item(self) -> None:
        row = self.item_table.currentRow()
        if row < 0:
            return
        item_id_item = self.item_table.item(row, 0)
        item_id = int(item_id_item.data(Qt.UserRole))
        scene = self._selected_scene() or ""
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        enabled_item = self.item_table.item(row, 2)
        new_enabled = (enabled_item.text() != "✓")
        run_in_thread(
            lambda: ctrl.set_scene_item_enabled(scene, item_id, new_enabled),
            lambda _: self.load_items(scene),
        )

    def _delete_item(self) -> None:
        row = self.item_table.currentRow()
        if row < 0:
            return
        item_id_item = self.item_table.item(row, 0)
        item_id = int(item_id_item.data(Qt.UserRole))
        scene = self._selected_scene() or ""
        ctrl = self.app.ctrl
        if ctrl is None:
            return
        run_in_thread(
            lambda: ctrl.remove_scene_item(scene, item_id),
            lambda _: self.load_items(scene),
        )
