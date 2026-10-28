"""测试都离线跑：不连网、不碰麦克风，读写的文件全部换到临时目录"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
