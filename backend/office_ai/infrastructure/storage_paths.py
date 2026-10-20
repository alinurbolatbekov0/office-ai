"""Resolve the per-user data directory outside the application install tree."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRECTORY_NAME = "OfficeAI"


def get_user_data_directory() -> Path:
    """Return the local application data directory for the current user.

    Windows uses %LOCALAPPDATA%. The XDG fallback supports developer testing on
    Linux/macOS; it is not used for the Windows release path.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("Переменная LOCALAPPDATA не задана для текущего пользователя Windows.")
        return Path(local_app_data) / APP_DIRECTORY_NAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / APP_DIRECTORY_NAME
