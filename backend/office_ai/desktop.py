"""Development desktop launcher for pywebview + a local FastAPI server."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn

from office_ai.api.app import create_app
from office_ai.application.backups import BackupService
from office_ai.infrastructure.storage_paths import get_user_data_directory

if getattr(sys, "frozen", False):
    # PyInstaller stores bundled resources below _MEIPASS in onedir builds.
    ROOT_DIR = Path(getattr(sys, "_MEIPASS"))
else:
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
    data_directory: Path | None = None,
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
        data_directory=data_directory,
    )
    # Uvicorn's default dictConfig resolves formatters dynamically, which PyInstaller
    # can omit from frozen builds. The application does not rely on Uvicorn logs.
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=DEV_HOST,
            port=port,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
    )
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


def _open_window(url: str, bridge: DesktopBridge, *, debug: bool, smoke_test: bool = False) -> None:
    if not _webview2_runtime_found():
        raise RuntimeError(
            "Не найден Microsoft Edge WebView2 Runtime. Установите Evergreen Runtime "
            "с https://developer.microsoft.com/microsoft-edge/webview2/ и перезапустите Office AI."
        )
    try:
        import webview
    except ImportError as error:
        raise RuntimeError(
            "pywebview не установлен. Установите backend\\requirements.txt "
            "в окружение разработчика и повторите запуск."
        ) from error

    window = webview.create_window(
        "Office AI",
        url=url,
        js_api=bridge,
        width=1180,
        height=780,
        min_size=(920, 640),
    )
    page_loaded = threading.Event()
    page_ready = threading.Event()
    if smoke_test:
        def wait_for_react_and_backend() -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if window.evaluate_js(
                        "document.querySelector('.app-shell[data-backend-ready=true]') !== null"
                    ):
                        page_ready.set()
                        break
                except Exception:
                    # The page may not have finished creating its WebView2 document yet.
                    pass
                time.sleep(0.2)
            window.destroy()

        def on_page_loaded() -> None:
            page_loaded.set()
            threading.Thread(target=wait_for_react_and_backend, daemon=True).start()

        window.events.loaded += on_page_loaded
    webview.start(debug=debug)
    if smoke_test and not page_loaded.is_set():
        raise RuntimeError("Окно WebView2 закрылось до загрузки интерфейса.")
    if smoke_test and not page_ready.is_set():
        raise RuntimeError("React-интерфейс не подтвердил подключение к локальному backend.")


def _webview2_runtime_found() -> bool:
    """Check common Evergreen WebView2 runtime locations without network access."""
    if sys.platform != "win32":
        return True
    roots = {
        Path(value)
        for key, value in os.environ.items()
        if key.casefold() in {"programfiles", "programfiles(x86)", "localappdata"} and value
    }
    for root in roots:
        application_root = root / "Microsoft" / "EdgeWebView" / "Application"
        try:
            for version_directory in application_root.iterdir():
                if version_directory.is_dir() and (version_directory / "msedgewebview2.exe").is_file():
                    return True
        except OSError:
            continue
    return False


def run_self_test() -> None:
    """Check the packaged static frontend and local API without opening a window."""
    if not (FRONTEND_DIST / "index.html").is_file():
        raise RuntimeError("В комплекте приложения отсутствует файл интерфейса index.html.")
    if not _webview2_runtime_found():
        raise RuntimeError("Не найден Microsoft Edge WebView2 Runtime.")

    import secrets

    token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="officeai-startup-check-") as temporary:
        server: uvicorn.Server | None = None
        thread: threading.Thread | None = None
        listener: socket.socket | None = None
        try:
            server, thread, listener, port, origin, _ = _start_backend(
                token,
                None,
                data_directory=Path(temporary),
            )
            base_url = f"http://{DEV_HOST}:{port}"
            with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
                if response.status != 200 or b"<html" not in response.read(256).lower():
                    raise RuntimeError("Локальный сервер не отдал собранный интерфейс.")
            request = urllib.request.Request(
                f"{base_url}/api/v1/health",
                headers={"Origin": origin, "X-OfficeAI-Token": token},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            if health.get("status") != "ok":
                raise RuntimeError("Локальный API не прошёл проверку готовности.")
        finally:
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=5)
            if listener is not None:
                listener.close()


def _log_startup_error(error: BaseException) -> None:
    """Write a minimal diagnostic locally; never log request or document data."""
    try:
        log_directory = get_user_data_directory() / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        error_text = "".join(traceback.format_exception_only(type(error), error)).strip()
        with (log_directory / "startup.log").open("a", encoding="utf-8") as log:
            log.write(f"{timestamp} {error_text[:1000]}\n")
            # Keep the call path for packaged startup failures; this log stays local.
            stack = "".join(traceback.format_tb(error.__traceback__))
            log.write(f"{stack[-6000:]}\n")
    except Exception:
        pass


def _show_startup_error(error: BaseException) -> None:
    _log_startup_error(error)
    message = f"Office AI не удалось запустить.\n\n{error}"
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "Office AI", 0x10)
    else:
        print(message, file=sys.stderr)


def run(*, dev: bool, gui_smoke_test: bool = False) -> None:
    import secrets

    vite: subprocess.Popen[bytes] | None = None
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    listener: socket.socket | None = None
    backup_service: BackupService | None = None
    smoke_data: tempfile.TemporaryDirectory[str] | None = None

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
        if gui_smoke_test:
            smoke_data = tempfile.TemporaryDirectory(prefix="officeai-gui-smoke-")
        server, thread, listener, port, frontend_origin, backup_service = _start_backend(
            token,
            frontend_origin if dev else None,
            data_directory=Path(smoke_data.name) if smoke_data is not None else None,
        )
        bridge_token = token

        assert backup_service is not None
        bridge = DesktopBridge(
            RuntimeConfig(api_base_url=f"http://{DEV_HOST}:{port}/api/v1", session_token=bridge_token),
            backup_service,
        )
        ui_url = frontend_origin if dev else f"http://{DEV_HOST}:{port}/"
        _open_window(ui_url, bridge, debug=dev, smoke_test=gui_smoke_test)
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
        if smoke_data is not None:
            smoke_data.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Office AI desktop development launcher")
    parser.add_argument("--dev", action="store_true", help="Run Vite and enable pywebview developer tools")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.self_test:
        try:
            run_self_test()
        except Exception as error:
            _log_startup_error(error)
            raise SystemExit(1) from error
        return
    if arguments.gui_smoke_test:
        try:
            run(dev=False, gui_smoke_test=True)
        except Exception as error:
            _log_startup_error(error)
            raise SystemExit(1) from error
        return
    try:
        run(dev=arguments.dev)
    except Exception as error:  # A concise startup error is more useful than a traceback here.
        _show_startup_error(error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
