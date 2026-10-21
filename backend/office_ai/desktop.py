"""Development desktop launcher for pywebview + a local FastAPI server."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import uvicorn

from office_ai.api.app import create_app
from office_ai.application.backups import BackupService

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
DEV_HOST = "127.0.0.1"
DEV_PORT = 5173


@dataclass(frozen=True)
class RuntimeConfig:
    api_base_url: str
    session_token: str


class DesktopBridge:
    """Narrow pywebview bridge: only the active app window gets the token."""

    def __init__(self, config: RuntimeConfig, backup_service: BackupService) -> None:
        self._config = config
        self._backup_service = backup_service

    def get_runtime_config(self) -> dict[str, str]:
        return {
            "apiBaseUrl": self._config.api_base_url,
            "sessionToken": self._config.session_token,
        }

    def save_backup(self, backup_id: str) -> bool:
        """Show a native Save dialog and stream one generated local archive to it."""
        backup = self._backup_service.get_backup_download(backup_id)
        if backup is None:
            raise ValueError("Резервная копия не найдена.")
        source, filename = backup
        try:
            import webview
        except ImportError as error:
            raise RuntimeError("Нативный диалог доступен только в desktop-оболочке.") from error
        selected = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=filename,
            file_types=("ZIP архив (*.zip)",),
        )
        if not selected:
            return False
        destination = Path(selected[0] if isinstance(selected, (tuple, list)) else selected)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return True


def _wait_for_vite(process: subprocess.Popen[bytes], timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://{DEV_HOST}:{DEV_PORT}/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Vite завершился до запуска окна приложения.")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise TimeoutError("Не удалось дождаться Vite на 127.0.0.1:5173.")


def _start_backend(
    session_token: str,
    frontend_origin: str | None,
) -> tuple[uvicorn.Server, threading.Thread, socket.socket, int, str, BackupService]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((DEV_HOST, 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    if frontend_origin is None:
        frontend_origin = f"http://{DEV_HOST}:{port}"
    app = create_app(
        expected_host=f"{DEV_HOST}:{port}",
        expected_origin=frontend_origin,
        session_token=session_token,
        frontend_dist=FRONTEND_DIST,
    )
    server = uvicorn.Server(uvicorn.Config(app, host=DEV_HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not server.started:
        if not thread.is_alive():
            listener.close()
            raise RuntimeError("Локальный API не запустился.")
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        listener.close()
        raise TimeoutError("Локальный API не подтвердил запуск.")
    return server, thread, listener, port, frontend_origin, app.state.backup_service


def _open_window(url: str, bridge: DesktopBridge, *, debug: bool) -> None:
    try:
        import webview
    except ImportError as error:
        raise RuntimeError(
            "pywebview не установлен. Установите backend\\requirements.txt "
            "в окружение разработчика и повторите запуск."
        ) from error

    webview.create_window(
        "Office AI",
        url=url,
        js_api=bridge,
        width=1180,
        height=780,
        min_size=(920, 640),
    )
    webview.start(debug=debug)


def run(*, dev: bool) -> None:
    import secrets

    vite: subprocess.Popen[bytes] | None = None
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    listener: socket.socket | None = None
    backup_service: BackupService | None = None

    try:
        if dev:
            command = ["npm.cmd" if os.name == "nt" else "npm", "run", "dev", "--", "--host", DEV_HOST, "--port", str(DEV_PORT), "--strictPort"]
            vite = subprocess.Popen(command, cwd=FRONTEND_DIR)
            _wait_for_vite(vite)
            frontend_origin = f"http://{DEV_HOST}:{DEV_PORT}"
        else:
            if not (FRONTEND_DIST / "index.html").is_file():
                raise RuntimeError("Собранный интерфейс не найден. Выполните npm run build в frontend.")
            frontend_origin = ""  # Filled after choosing the backend port below.

        # Production serves the SPA and API from one origin; development uses Vite.
        token = secrets.token_urlsafe(32)
        server, thread, listener, port, frontend_origin, backup_service = _start_backend(
            token,
            frontend_origin if dev else None,
        )
        bridge_token = token

        assert backup_service is not None
        bridge = DesktopBridge(
            RuntimeConfig(api_base_url=f"http://{DEV_HOST}:{port}/api/v1", session_token=bridge_token),
            backup_service,
        )
        ui_url = frontend_origin if dev else f"http://{DEV_HOST}:{port}/"
        _open_window(ui_url, bridge, debug=dev)
    finally:
        if server is not None:
            server.should_exit = True
        if vite is not None and vite.poll() is None:
            vite.terminate()
            try:
                vite.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite.kill()
        if thread is not None:
            thread.join(timeout=5)
        if listener is not None:
            listener.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Office AI desktop development launcher")
    parser.add_argument("--dev", action="store_true", help="Run Vite and enable pywebview developer tools")
    arguments = parser.parse_args()
    try:
        run(dev=arguments.dev)
    except Exception as error:  # A concise startup error is more useful than a traceback here.
        print(f"Office AI не запущен: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
