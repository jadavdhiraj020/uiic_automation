"""
utils.py — Shared utilities for frozen (PyInstaller) and normal execution.

When the app is bundled into an exe, file paths resolve differently.
This module provides a single helper that works in both modes.
"""

import os
import sys


def get_base_dir() -> str:
    """
    Return the project root directory.

    - Normal run:  the directory containing main.py
    - Frozen exe:  sys._MEIPASS (PyInstaller temp extraction folder)
    """
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return sys._MEIPASS
    else:
        # Running from source — go up from app/ to project root
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts) -> str:
    """
    Build an absolute path to a bundled resource.

    Usage:
        resource_path("app", "config", "settings.json")
        resource_path("app", "ui", "styles.qss")
        resource_path("assets", "icon.ico")
    """
    return os.path.join(get_base_dir(), *parts)
