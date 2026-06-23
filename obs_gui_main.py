"""
obs_gui_main.py  ——  OBS 全功能控制台 GUI 入口（PyQt5 版）
用法：
    python obs_gui_main.py

依赖：
    pip install PyQt5 pillow obsws-python
"""
import sys
import os

# 确保工作目录在 sys.path，便于导入 obs_controller
sys.path.insert(0, os.path.dirname(__file__))

from PyQt5.QtWidgets import QApplication
from gui.app import OBSGui


def main():
    app = QApplication(sys.argv)
    window = OBSGui()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()