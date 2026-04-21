"""
PyInstaller runtime hook for PaddlePaddle and related native libraries.
"""

import os
import sys


def _register_dll_dir(path: str) -> None:
    if not os.path.isdir(path):
        return

    os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(path)
    except (OSError, AttributeError):
        pass


if getattr(sys, "frozen", False):
    base_dir = sys._MEIPASS

    for relative_path in (
        "",
        os.path.join("paddle", "libs"),
        "numpy.libs",
        "scipy.libs",
        "Shapely.libs",
        "cv2",
    ):
        _register_dll_dir(os.path.join(base_dir, relative_path))

    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("FLAGS_eager_delete_tensor_gb", "0.0")
    os.environ.setdefault("FLAGS_fast_eager_deletion_mode", "1")
    os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")
    os.environ.setdefault("PADDLE_NO_UPDATE", "1")
