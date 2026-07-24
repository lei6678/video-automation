"""
资源路径解析 — 开发模式与 PyInstaller 打包模式兼容。

开发模式: __file__ 相对路径正常工作。
打包模式: sys._MEIPASS 存放只读资源(fonts/prompts/frontend)，
          可写数据(DB/tasks/bgm)放在 exe 同级目录方便同事换歌。
"""
import os
import sys

_FROZEN = getattr(sys, 'frozen', False)
_EXE_DIR = os.path.dirname(sys.executable) if _FROZEN else None


def get_project_root() -> str:
    """只读资源根目录（fonts/  prompts/  frontend/dist/）。打包后指向 MEIPASS。"""
    if _FROZEN:
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_data_dir() -> str:
    """可写数据根目录（app.db  tasks/）。打包后在 exe 旁边，解压即用。"""
    if _FROZEN:
        d = os.path.join(_EXE_DIR, "data")  # type: ignore[arg-type]
    else:
        d = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(d, exist_ok=True)
    return d


def get_bgm_dir() -> str:
    """
    BGM 目录 — 打包后放在 exe 旁边的 bgm/，方便同事自己换歌。
    开发模式仍用项目根目录 bgm/。
    """
    if _FROZEN:
        d = os.path.join(_EXE_DIR, "bgm")  # type: ignore[arg-type]
    else:
        d = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bgm"))
    os.makedirs(d, exist_ok=True)
    return d
