from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import csv
import ipaddress
import logging
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

APP_NAME = "HD2 Stratagem LAN"
APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
CATALOG_PATH = APP_DIR / "stratagems.tsv"
ICON_MAP_PATH = APP_DIR / "icon_map.json"
EXPECTED_CATALOG_SIZE = 111
VERSION = "0.21.0"
SUPPORTED_DIRECTION_KEYS = {"UP", "DOWN", "LEFT", "RIGHT", "W", "A", "S", "D"}
LEGACY_WASD = {"U": "W", "D": "S", "L": "A", "R": "D"}
ARROW_KEYS = {"U": "UP", "D": "DOWN", "L": "LEFT", "R": "RIGHT"}
DIRECTION_GLYPHS = {"U": "↑", "D": "↓", "L": "←", "R": "→"}
DIRECTION_NAMES = {"U": "Вверх", "D": "Вниз", "L": "Влево", "R": "Вправо"}
ICON_REPOSITORY = "https://github.com/nvigneux/Helldivers-2-Stratagems-icons-svg"
ICON_RAW_BASE = "https://raw.githubusercontent.com/nvigneux/Helldivers-2-Stratagems-icons-svg/master/"
LOCAL_HOST_NAMES = {"localhost", "localhost.localdomain", socket.gethostname().lower()}

# Ten main digit keys (0–9) plus five operator keys. Numpad Enter is
# intentionally not intercepted or used as a macro binding.
BINDING_KEYS: list[dict] = []
for digit in range(10):
    BINDING_KEYS.append({
        "id": f"numpad_{digit}", "label": str(digit), "display": str(digit),
        "title": f"Numpad {digit}", "group": "main", "vk": 0x60 + digit,
    })
for key_id, label, display, vk in [
    ("numpad_decimal", ".", ".", 0x6E),
    ("numpad_subtract", "-", "-", 0x6D),
    ("numpad_add", "+", "+", 0x6B),
    ("numpad_multiply", "*", "×", 0x6A),
    ("numpad_divide", "/", "÷", 0x6F),
]:
    BINDING_KEYS.append({"id": key_id, "label": label, "display": display, "title": f"Numpad {label}", "group": "extra", "vk": vk})
BINDING_BY_ID = {item["id"]: item for item in BINDING_KEYS}
BINDING_IDS = set(BINDING_BY_ID)


def user_data_dir() -> Path:
    root = Path(os.getenv("APPDATA", str(Path.home())))
    folder = root / "HD2StratagemLAN"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


CONFIG_PATH = user_data_dir() / "config.json"
CONFIG_LOCK = threading.RLock()
CONFIG_REVISION = 1
ICON_CACHE_DIR = user_data_dir() / "icons"
ICON_LOCKS_GUARD = threading.Lock()
ICON_LOCKS: dict[int, threading.Lock] = {}
LOGGER = logging.getLogger("hd2_stratagem_lan")


def direction_arrows(code: str) -> str:
    return " ".join(DIRECTION_GLYPHS[item] for item in code)


def load_icon_map() -> dict[str, str]:
    try:
        data = json.loads(ICON_MAP_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            safe: dict[str, str] = {}
            for name, raw_path in data.items():
                if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path or ":" in raw_path:
                    continue
                relative = PurePosixPath(raw_path)
                if relative.is_absolute() or any(part in {"..", "."} for part in relative.parts):
                    continue
                safe[str(name)] = relative.as_posix()
            return safe
    except (OSError, json.JSONDecodeError):
        pass
    return {}


ICON_MAP = load_icon_map()


def load_catalog(path: Path = CATALOG_PATH) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.reader(stream, delimiter="\t"), start=1):
            if not row or all(not item.strip() for item in row):
                continue
            if len(row) < 3:
                raise ValueError(f"В каталоге строка {line}: ожидались категория, название и код.")
            category, name, code = (part.strip().lstrip("\ufeff") for part in row[:3])
            code = code.upper().replace(" ", "")
            if not category or not name or not code or set(code) - set("UDLR"):
                raise ValueError(f"В каталоге строка {line}: некорректная запись.")
            records.append({
                "id": str(len(records)),
                "category": category,
                "name": name,
                "code": code,
                "arrows": direction_arrows(code),
                "directions": [DIRECTION_NAMES[item] for item in code],
                "icon_url": f"/api/icons/{len(records)}?v={VERSION}",
                "has_icon": name in ICON_MAP,
            })
    if len(records) != EXPECTED_CATALOG_SIZE:
        raise ValueError(f"Ожидалось {EXPECTED_CATALOG_SIZE} записей, найдено {len(records)}.")
    if len({item["name"] for item in records}) != len(records):
        raise ValueError("В каталоге есть повторяющиеся названия.")
    unmapped = [item["name"] for item in records if item["name"] not in ICON_MAP]
    if unmapped:
        raise ValueError("Для стратагем отсутствуют игровые иконки: " + ", ".join(unmapped))
    return records


def empty_bindings() -> dict[str, str | None]:
    return {key_id: None for key_id in BINDING_BY_ID}


DEFAULT_CONFIG = {
    "bindings": empty_bindings(),
    "open_key": "CTRL",
    "direction_keys": dict(ARROW_KEYS),
    "press_ms": 65,
    "gap_ms": 65,
    "open_hold_ms": 100,
}


def write_config(config: dict) -> None:
    """Durably write config to a sibling file, then atomically replace the old one."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    payload = dict(config)
    payload["_revision"] = CONFIG_REVISION
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    # Flush the file before replace so a power loss is less likely to leave an
    # empty/truncated config. CONFIG_LOCK serializes writers in this process.
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, CONFIG_PATH)


def _backup_corrupt_config() -> Path:
    """Move malformed user config aside instead of silently destroying it."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.corrupt-{stamp}")
    suffix = 1
    while backup.exists():
        backup = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.corrupt-{stamp}-{suffix}")
        suffix += 1
    os.replace(CONFIG_PATH, backup)
    return backup


def read_config() -> dict:
    global CONFIG_REVISION
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    saved: dict = {}
    if CONFIG_PATH.exists():
        try:
            candidate = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                saved = candidate
            else:
                raise json.JSONDecodeError("Корень config.json должен быть объектом", "", 0)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Keep a recoverable copy. A malformed file should never disappear
            # just because the application started with fallback defaults.
            backup = _backup_corrupt_config()
            LOGGER.warning("Повреждённый config.json сохранён как %s: %s", backup, exc)
        except OSError:
            # Permission/I/O errors are not corruption. Fail startup rather than
            # writing defaults over a file that could not be read.
            raise
    try:
        CONFIG_REVISION = max(1, int(saved.get("_revision", 1)))
    except (TypeError, ValueError):
        CONFIG_REVISION = 1
    # Preserve the input settings and migrate the old four-slot layout to Numpad 1–4.
    for key in ("open_key", "direction_keys", "press_ms", "gap_ms", "open_hold_ms"):
        if key in saved:
            config[key] = saved[key]
    raw_bindings = saved.get("bindings")
    if isinstance(raw_bindings, dict):
        for key_id, name in raw_bindings.items():
            if key_id in BINDING_IDS and (name is None or isinstance(name, str)):
                config["bindings"][key_id] = name
    else:
        legacy_slots = saved.get("slots")
        if isinstance(legacy_slots, list):
            for legacy_index, name in enumerate(legacy_slots[:4], start=1):
                config["bindings"][f"numpad_{legacy_index}"] = name if isinstance(name, str) else None
    for key_id, name in list(config["bindings"].items()):
        if name not in CATALOG_BY_NAME:
            config["bindings"][key_id] = None
    if not isinstance(config.get("direction_keys"), dict):
        config["direction_keys"] = dict(ARROW_KEYS)
    saved_direction_keys = {str(k): str(v).upper() for k, v in config["direction_keys"].items()}
    if saved_direction_keys == LEGACY_WASD:
        config["direction_keys"] = dict(ARROW_KEYS)
    else:
        config["direction_keys"] = saved_direction_keys
    for direction, key in ARROW_KEYS.items():
        if config["direction_keys"].get(direction) not in SUPPORTED_DIRECTION_KEYS:
            config["direction_keys"][direction] = key
    if config.get("open_key") not in {"CTRL", "ALT", "SHIFT"}:
        config["open_key"] = "CTRL"
    for key, low, high, fallback in [
        ("press_ms", 25, 250, 65), ("gap_ms", 20, 300, 65), ("open_hold_ms", 50, 500, 100)
    ]:
        try:
            config[key] = max(low, min(high, int(config.get(key, fallback))))
        except (ValueError, TypeError):
            config[key] = fallback
    write_config(config)
    return config


CATALOG = load_catalog()
CATALOG_BY_NAME = {item["name"]: item for item in CATALOG}
CONFIG = read_config()


class ConfigPayload(BaseModel):
    bindings: dict[str, str | None]
    open_key: Literal["CTRL", "ALT", "SHIFT"] = "CTRL"
    direction_keys: dict[Literal["U", "D", "L", "R"], str]
    press_ms: int = Field(default=65, ge=25, le=250)
    gap_ms: int = Field(default=65, ge=20, le=300)
    open_hold_ms: int = Field(default=100, ge=50, le=500)

    revision: int = Field(..., ge=1)

    @model_validator(mode="after")
    def validate_config(self):
        if set(self.bindings) != BINDING_IDS:
            raise ValueError("В конфигурации должны присутствовать все 15 назначаемых клавиш Numpad.")
        for key_id, name in self.bindings.items():
            if name is not None and name not in CATALOG_BY_NAME:
                raise ValueError(f"Неизвестная стратагема для {BINDING_BY_ID[key_id]['title']}: {name}")
        if set(self.direction_keys) != {"U", "D", "L", "R"}:
            raise ValueError("Нужны назначения для всех четырёх направлений.")
        keys = [str(value).upper() for value in self.direction_keys.values()]
        if any(key not in SUPPORTED_DIRECTION_KEYS for key in keys) or len(set(keys)) != 4:
            raise ValueError("Для направлений выбери четыре разные стрелки или клавиши WASD.")
        self.direction_keys = {direction: str(value).upper() for direction, value in self.direction_keys.items()}
        return self


class MacroPayload(BaseModel):
    wait_for_game: bool = True
    wait_timeout_seconds: int = Field(default=12, ge=3, le=30)



def get_local_ipv4() -> list[str]:
    found: set[str] = set()
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            try:
                ip = ipaddress.ip_address(address)
                if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    found.add(address)
            except ValueError:
                pass
    except OSError:
        pass
    for remote in [("192.0.2.1", 80), ("8.8.8.8", 80)]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(remote)
            address = sock.getsockname()[0]
            ip = ipaddress.ip_address(address)
            if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
                found.add(address)
        except OSError:
            pass
        finally:
            sock.close()
    return sorted(found)


VK = {
    "CTRL": 0x11, "ALT": 0x12, "SHIFT": 0x10,
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
}


@lru_cache(maxsize=1)
def _window_api():
    """Load and type Win32 process/window APIs once instead of on every key event."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.WCHAR), ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return user32, kernel32


@lru_cache(maxsize=1)
def _sendinput_api():
    """Cache SendInput bindings and ctypes structures for low-jitter macro playback."""
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    return user32, INPUT, INPUT_UNION, KEYBDINPUT


def windows_is_game_foreground() -> tuple[bool, str | None]:
    if os.name != "nt":
        return False, None
    try:
        user32, kernel32 = _window_api()
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False, None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False, None
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return False, None
            name = Path(buffer.value).name.lower()
            return name == "helldivers2.exe", name
        finally:
            kernel32.CloseHandle(process)
    except Exception:
        return False, None


def send_vk(vk: int, key_up: bool = False) -> None:
    if os.name != "nt":
        raise RuntimeError("Отправка клавиш доступна только на Windows.")
    user32, INPUT, INPUT_UNION, KEYBDINPUT = _sendinput_api()
    flags = 0x0002 if key_up else 0
    payload = INPUT(type=1, union=INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0)))
    sent = user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(INPUT))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


class MacroEngine:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.waiting_for_game = False
        self.active_binding: str | None = None
        self.last_result = "Ожидание команды"
        self.hotkeys_registered = False
        self.hotkey_error: str | None = None
        self.cancel_event = threading.Event()
        self.shutting_down = False
        self.worker: threading.Thread | None = None

    def start(self) -> bool:
        with self.lock:
            if self.worker and self.worker.is_alive():
                LOGGER.error("Нельзя перезапустить MacroEngine: предыдущий worker ещё работает.")
                return False
            self.shutting_down = False
            self.cancel_event.clear()
            return True

    def shutdown(self, timeout: float = 3.0) -> None:
        with self.lock:
            self.shutting_down = True
            self.cancel_event.set()
            worker = self.worker
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=timeout)
            if worker.is_alive():
                LOGGER.error("Поток макроса не завершился за %.1f сек. после отмены.", timeout)

    def _wait_or_cancel(self, seconds: float) -> None:
        if self.cancel_event.wait(max(0.0, seconds)):
            raise RuntimeError("Сервер останавливается; макрос отменён.")

    def snapshot(self) -> dict:
        focused, process = windows_is_game_foreground()
        with CONFIG_LOCK:
            assigned_count = sum(1 for name in CONFIG["bindings"].values() if name)
        with self.lock:
            return {
                "running": self.running,
                "waiting_for_game": self.waiting_for_game,
                "active_binding": self.active_binding,
                "active_binding_label": BINDING_BY_ID[self.active_binding]["title"] if self.active_binding else None,
                "last_result": self.last_result,
                "hotkeys_registered": self.hotkeys_registered,
                "hotkey_error": self.hotkey_error,
                "game_focused": focused,
                "foreground_process": process,
                "windows_only": os.name == "nt",
                "assigned_count": assigned_count,
                "binding_count": len(BINDING_KEYS),
            }

    def _set_result(self, result: str) -> None:
        with self.lock:
            self.last_result = result

    def trigger(self, binding_id: str, require_game_focus: bool = True, wait_for_game: bool = False,
                wait_timeout_seconds: int = 12, focus_already_confirmed: bool = False) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Макросы доступны только на Windows."
        if binding_id not in BINDING_BY_ID:
            return False, "Неизвестная клавиша Numpad."
        with self.lock:
            if self.shutting_down:
                return False, "Сервер завершает работу; новая команда не принята."
        if focus_already_confirmed:
            focused, process = True, "Helldivers2.exe"
        else:
            focused, process = windows_is_game_foreground()
        if require_game_focus and not focused and not wait_for_game:
            return False, f"Фокус не у игры (активно: {process or 'неизвестное окно'}). Макрос не отправлен."
        label = BINDING_BY_ID[binding_id]["title"]
        with CONFIG_LOCK:
            selected = CONFIG["bindings"].get(binding_id)
            macro_config = {
                "open_key": CONFIG["open_key"],
                "direction_keys": dict(CONFIG["direction_keys"]),
                "press_ms": CONFIG["press_ms"],
                "gap_ms": CONFIG["gap_ms"],
                "open_hold_ms": CONFIG["open_hold_ms"],
            }
        if not selected:
            return False, f"Для {label} стратагема не назначена."
        stratagem = CATALOG_BY_NAME.get(selected)
        if not stratagem:
            return False, "Выбранная стратагема отсутствует в каталоге."
        with self.lock:
            if self.shutting_down:
                return False, "Сервер завершает работу; новая команда не принята."
            if self.running:
                return False, "Предыдущая комбинация ещё выполняется."
            self.cancel_event.clear()
            self.running = True
            self.waiting_for_game = bool(wait_for_game and not focused)
            self.active_binding = binding_id
            self.last_result = f"Ожидаю игру: {selected}" if self.waiting_for_game else f"Выполняется: {selected}"
            worker = threading.Thread(
                target=self._execute,
                args=(binding_id, stratagem, wait_timeout_seconds if wait_for_game else 0, macro_config),
                daemon=True,
                name="HD2-Stratagem-Macro",
            )
            self.worker = worker
            try:
                worker.start()
            except RuntimeError as exc:
                self.worker = None
                self.running = False
                self.waiting_for_game = False
                self.active_binding = None
                self.last_result = f"Не удалось запустить макрос: {exc}"
                return False, f"Не удалось запустить макрос: {exc}"
        if wait_for_game and not focused:
            return True, f"Команда подготовлена. Верни фокус Helldivers 2 в течение {wait_timeout_seconds} сек."
        return True, f"Отправлена команда для {selected}."

    def _execute(self, binding_id: str, stratagem: dict, wait_timeout_seconds: int = 0,
                 macro_config: dict | None = None) -> None:
        try:
            # Snapshot settings once: edits in another browser must not change a
            # combination halfway through its execution.
            if macro_config is None:
                with CONFIG_LOCK:
                    macro_config = {
                        "open_key": CONFIG["open_key"],
                        "direction_keys": dict(CONFIG["direction_keys"]),
                        "press_ms": CONFIG["press_ms"],
                        "gap_ms": CONFIG["gap_ms"],
                        "open_hold_ms": CONFIG["open_hold_ms"],
                    }
            if self.cancel_event.is_set():
                raise RuntimeError("Сервер останавливается; макрос отменён.")
            deadline = time.monotonic() + wait_timeout_seconds
            focused, process = windows_is_game_foreground()
            while not focused and time.monotonic() < deadline:
                self._wait_or_cancel(0.12)
                focused, process = windows_is_game_foreground()
            with self.lock:
                self.waiting_for_game = False
            if not focused:
                raise RuntimeError(f"Helldivers 2 не получило фокус за {wait_timeout_seconds} сек. Ввод отменён.")
            open_vk = VK[macro_config["open_key"]]
            direction_keys = macro_config["direction_keys"]
            send_vk(open_vk, False)
            open_key_down = True
            self._wait_or_cancel(macro_config["open_hold_ms"] / 1000)
            active_direction_vk = None
            for direction in stratagem["code"]:
                if self.cancel_event.is_set():
                    raise RuntimeError("Сервер останавливается; макрос отменён.")
                still_focused, current_process = windows_is_game_foreground()
                if not still_focused:
                    raise RuntimeError(f"Фокус ушёл от игры (активно: {current_process or 'неизвестное окно'}); ввод отменён.")
                active_direction_vk = VK[direction_keys[direction].upper()]
                send_vk(active_direction_vk, False)
                self._wait_or_cancel(macro_config["press_ms"] / 1000)
                send_vk(active_direction_vk, True)
                active_direction_vk = None
                self._wait_or_cancel(macro_config["gap_ms"] / 1000)
            send_vk(open_vk, True)
            open_key_down = False
            self._set_result(f"Готово: {stratagem['name']} ({BINDING_BY_ID[binding_id]['title']})")
        except Exception as exc:
            try:
                if "active_direction_vk" in locals() and active_direction_vk is not None:
                    send_vk(active_direction_vk, True)
            except Exception:
                pass
            try:
                if "open_key_down" in locals() and open_key_down:
                    send_vk(VK[macro_config["open_key"]], True)
            except Exception:
                pass
            self._set_result(f"Ошибка макроса: {exc}")
        finally:
            with self.lock:
                self.running = False
                self.waiting_for_game = False
                self.active_binding = None
                if self.worker is threading.current_thread():
                    self.worker = None


MACROS = MacroEngine()


# The low-level hook runs on a dedicated Windows thread. WebSocket events are
# marshalled onto the FastAPI event loop so the browser can animate the physical key.
WS_LOOP: asyncio.AbstractEventLoop | None = None
WS_BROADCAST_LOCK: asyncio.Lock | None = None
WS_CLIENTS: set[WebSocket] = set()


async def _send_ws_event(client: WebSocket, event: dict) -> bool:
    try:
        await asyncio.wait_for(client.send_json(event), timeout=2.0)
        return True
    except Exception:
        return False


async def _broadcast_unlocked(event: dict) -> None:
    """Fan out one packet concurrently; evict dead/slow sockets to protect peers."""
    clients = tuple(WS_CLIENTS)
    if not clients:
        return
    results = await asyncio.gather(
        *(_send_ws_event(client, event) for client in clients),
        return_exceptions=True,
    )
    for client, result in zip(clients, results):
        if result is not True:
            WS_CLIENTS.discard(client)
            try:
                await client.close(code=1011)
            except Exception:
                pass


async def _broadcast_event(event: dict) -> None:
    lock = WS_BROADCAST_LOCK
    if lock is None:
        return
    async with lock:
        await _broadcast_unlocked(event)


async def _broadcast_events(events: list[dict]) -> None:
    # Keep related config/settings packets in-order and prevent concurrent
    # send_json calls on the same WebSocket connection.
    lock = WS_BROADCAST_LOCK
    if lock is None:
        return
    async with lock:
        for event in events:
            await _broadcast_unlocked(event)


def _observe_broadcast_future(future) -> None:
    try:
        future.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        LOGGER.exception("Ошибка рассылки события WebSocket.")


def publish_server_event(event: dict) -> None:
    loop = WS_LOOP
    if loop is None or not loop.is_running():
        return
    try:
        future = asyncio.run_coroutine_threadsafe(_broadcast_event(event), loop)
        future.add_done_callback(_observe_broadcast_future)
    except RuntimeError:
        LOGGER.debug("WebSocket loop уже остановлен; событие пропущено.")


def publish_server_events(events: list[dict]) -> None:
    loop = WS_LOOP
    if loop is None or not loop.is_running() or not events:
        return
    try:
        future = asyncio.run_coroutine_threadsafe(_broadcast_events(events), loop)
        future.add_done_callback(_observe_broadcast_future)
    except RuntimeError:
        LOGGER.debug("WebSocket loop уже остановлен; пакет событий пропущен.")


def publish_key_event(event_type: str, binding_id: str) -> None:
    publish_server_event({"type": event_type, "binding_id": binding_id, "at": time.monotonic()})


class GlobalNumpadHook:
    """Low-level keyboard hook: consumes assigned Numpad keys only in the game."""
    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012
    LLKHF_UP = 0x80
    LLKHF_INJECTED = 0x10
    LLKHF_LOWER_IL_INJECTED = 0x02
    PM_NOREMOVE = 0x0000

    def __init__(self, engine: MacroEngine):
        self.engine = engine
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.callback = None
        self.hook = None
        self.pressed: set[str] = set()
        self.pressed_last_seen: dict[str, float] = {}
        self.pressed_last_broadcast: dict[str, float] = {}
        self.stop_event = threading.Event()
        self.lifecycle_lock = threading.Lock()

    def start(self):
        if os.name != "nt":
            return
        with self.lifecycle_lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, daemon=True, name="HD2-Numpad-LowLevel-Hook")
            self.thread.start()

    def stop(self, timeout: float = 3.0):
        if os.name != "nt":
            return
        with self.lifecycle_lock:
            thread = self.thread
            thread_id = self.thread_id
            if not thread or not thread.is_alive():
                self.thread = None
                self.thread_id = None
                return
            self.stop_event.set()
        if thread_id:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.PostThreadMessageW.restype = wintypes.BOOL
                user32.PostThreadMessageW(thread_id, self.WM_QUIT, 0, 0)
            except Exception:
                LOGGER.exception("Не удалось отправить WM_QUIT клавиатурному hook.")
        thread.join(timeout=timeout)
        if thread.is_alive():
            LOGGER.error("Поток клавиатурного hook не завершился за %.1f сек.", timeout)
        else:
            with self.lifecycle_lock:
                self.thread = None
                self.thread_id = None

    def _binding_from_event(self, info) -> str | None:
        vk = int(info.vkCode)
        for digit in range(10):
            if vk == 0x60 + digit:
                return f"numpad_{digit}"
        special = {0x6E: "numpad_decimal", 0x6D: "numpad_subtract", 0x6B: "numpad_add",
                   0x6A: "numpad_multiply", 0x6F: "numpad_divide"}
        return special.get(vk)

    def handle_binding_event(self, binding_id: str, key_down: bool, key_up: bool) -> bool:
        """Handle a mapped transition; return True when the key must be swallowed."""
        if self.stop_event.is_set():
            return False
        now = time.monotonic()
        if key_up and binding_id in self.pressed:
            self.pressed.discard(binding_id)
            self.pressed_last_seen.pop(binding_id, None)
            self.pressed_last_broadcast.pop(binding_id, None)
            publish_key_event("key_up", binding_id)
            return True
        if not key_down:
            return False

        # Auto-repeat keydowns are swallowed while held. If the OS missed key_up,
        # a fresh press after a quiet interval repairs the stale pressed state.
        if binding_id in self.pressed:
            last_seen = self.pressed_last_seen.get(binding_id, now)
            if now - last_seen <= 2.0:
                self.pressed_last_seen[binding_id] = now
                # Send a throttled pressed-state heartbeat. The browser has a
                # fail-safe timer for suspended tabs; this keeps long physical
                # holds visibly pressed without flooding the WebSocket.
                last_broadcast = self.pressed_last_broadcast.get(binding_id, now)
                if now - last_broadcast >= 0.7:
                    self.pressed_last_broadcast[binding_id] = now
                    publish_key_event("key_down", binding_id)
                return True
            self.pressed.discard(binding_id)
            self.pressed_last_seen.pop(binding_id, None)
            self.pressed_last_broadcast.pop(binding_id, None)
            publish_key_event("key_up", binding_id)

        with CONFIG_LOCK:
            assigned = bool(CONFIG["bindings"].get(binding_id))
        if not assigned or not windows_is_game_foreground()[0]:
            return False
        self.pressed.add(binding_id)
        self.pressed_last_seen[binding_id] = now
        self.pressed_last_broadcast[binding_id] = now
        publish_key_event("key_down", binding_id)
        # Focus was checked once in the hook callback. The macro worker checks
        # again immediately before sending synthetic input.
        self.engine.trigger(binding_id, require_game_focus=True, focus_already_confirmed=True)
        return True

    def _run(self):
        if os.name != "nt":
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ULONG_PTR = ctypes.c_size_t

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        # Create the message queue before publishing the thread ID so stop() can
        # safely post WM_QUIT even during startup.
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self.PM_NOREMOVE)
        self.thread_id = int(kernel32.GetCurrentThreadId())

        def on_key(n_code, w_param, l_param):
            if n_code == self.HC_ACTION:
                try:
                    info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    # Ignore SendInput / accessibility-injected events. Our macro
                    # emits arrows and Ctrl; this also avoids accidental recursion.
                    if info.flags & (self.LLKHF_INJECTED | self.LLKHF_LOWER_IL_INJECTED):
                        return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)
                    binding_id = self._binding_from_event(info)
                    if binding_id:
                        key_up = w_param in (self.WM_KEYUP, self.WM_SYSKEYUP) or bool(info.flags & self.LLKHF_UP)
                        key_down = w_param in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN) and not key_up
                        if self.handle_binding_event(binding_id, key_down, key_up):
                            return 1
                except Exception:
                    LOGGER.exception("Ошибка в callback клавиатурного hook.")
            return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)

        self.callback = HOOKPROC(on_key)
        module = kernel32.GetModuleHandleW(None)
        self.hook = user32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self.callback, module, 0)
        if not self.hook:
            error = f"Не удалось установить клавиатурный hook: {ctypes.WinError(ctypes.get_last_error())}"
            with self.engine.lock:
                self.engine.hotkeys_registered = False
                self.engine.hotkey_error = error
            self.thread_id = None
            return
        with self.engine.lock:
            self.engine.hotkeys_registered = True
            self.engine.hotkey_error = None
            self.engine.last_result = "Глобальный Numpad hook активен (15 клавиш)"
        try:
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
        finally:
            if self.hook:
                user32.UnhookWindowsHookEx(self.hook)
                self.hook = None
            for binding_id in tuple(self.pressed):
                publish_key_event("key_up", binding_id)
            self.pressed.clear()
            self.pressed_last_seen.clear()
            self.pressed_last_broadcast.clear()
            self.callback = None
            self.thread_id = None
            with self.engine.lock:
                self.engine.hotkeys_registered = False


HOTKEYS = GlobalNumpadHook(MACROS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global WS_LOOP, WS_BROADCAST_LOCK
    WS_LOOP = asyncio.get_running_loop()
    WS_BROADCAST_LOCK = asyncio.Lock()
    try:
        if not MACROS.start():
            raise RuntimeError("Предыдущий поток макроса ещё выполняется; сервер не может безопасно перезапуститься.")
        HOTKEYS.start()
        yield
    finally:
        MACROS.shutdown()
        HOTKEYS.stop()
        WS_LOOP = None
        WS_BROADCAST_LOCK = None
        WS_CLIENTS.clear()


app = FastAPI(title=APP_NAME, version=VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


def _hostname_from_header(host_header: str) -> str | None:
    try:
        return urllib.parse.urlsplit("//" + (host_header or "")).hostname
    except ValueError:
        return None


def _is_trusted_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    if address.is_loopback or address.is_link_local:
        return True
    if isinstance(address, ipaddress.IPv4Address):
        private_networks = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
        return any(address in network for network in private_networks)
    return address in ipaddress.ip_network("fc00::/7")


def is_local_peer(peer_host: str | None) -> bool:
    """Only serve connections originating from loopback/private/link-local IPs."""
    if peer_host == "testclient":
        return True  # Starlette TestClient only.
    if not peer_host:
        return False
    try:
        address = ipaddress.ip_address(peer_host)
    except ValueError:
        return False
    return _is_trusted_ip(address)


def is_local_host(host_header: str, peer_host: str | None = None) -> bool:
    """Allow loopback/private LAN hosts, local machine names and mDNS .local.

    This blocks external Host headers/DNS-rebinding attempts and public peers
    while preserving localhost/IP/PC-name access on a trusted home LAN.
    """
    hostname = _hostname_from_header(host_header)
    if not hostname:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "testserver" and peer_host == "testclient":
        return True  # Starlette TestClient only; not a production network alias.
    host_is_local = normalized in LOCAL_HOST_NAMES or normalized.endswith(".local")
    if not host_is_local:
        try:
            address = ipaddress.ip_address(normalized)
            host_is_local = _is_trusted_ip(address)
        except ValueError:
            host_is_local = False
    return host_is_local and is_local_peer(peer_host)


def _same_origin(origin: str, host_header: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and parsed.netloc.lower() == host_header.lower()


@app.middleware("http")
async def local_network_guard(request: Request, call_next):
    host_header = request.headers.get("host", "")
    peer_host = request.client.host if request.client else None
    if not is_local_host(host_header, peer_host):
        return JSONResponse({"detail": "Доступ разрешён только по локальному адресу этого ПК из локальной сети."}, status_code=400)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and not _same_origin(origin, host_header):
            return JSONResponse({"detail": "Отклонён межсайтовый запрос."}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get("/", include_in_schema=False)
def homepage():
    # The HTML entry point should always be revalidated after the server updates.
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/status")
def get_status():
    return {
        "ok": True,
        "name": APP_NAME,
        "version": VERSION,
        "catalog_count": len(CATALOG),
        "binding_keys": BINDING_KEYS,
        "macro": MACROS.snapshot(),
        "lan_addresses": get_local_ipv4(),
    }


@app.websocket("/ws/keys")
async def key_feedback_socket(websocket: WebSocket):
    # Reject DNS-rebinding / cross-site WebSocket connections.
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host", "")
    peer_host = websocket.client.host if websocket.client else None
    if not is_local_host(host, peer_host) or (origin and not _same_origin(origin, host)):
        await websocket.close(code=1008)
        return

    # PIN-free WebSocket for trusted home-LAN use. Keep this service off public networks.
    await websocket.accept()
    lock = WS_BROADCAST_LOCK
    if lock is None:
        await websocket.close(code=1011)
        return
    try:
        # Register and send the initial snapshot under the broadcast lock. This
        # guarantees the client receives `ready` before any subsequent update.
        async with lock:
            await websocket.send_json({
                "type": "ready",
                "config": public_config(),
                "status": MACROS.snapshot(),
            })
            WS_CLIENTS.add(websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        WS_CLIENTS.discard(websocket)


@app.get("/api/stratagems")
def get_stratagems():
    return {"items": CATALOG, "categories": list(dict.fromkeys(item["category"] for item in CATALOG))}


def _icon_lock(icon_id: int) -> threading.Lock:
    # Two browser tabs often request the same newly seen icons at once.
    # Serialize cache misses per icon rather than locking every image request.
    with ICON_LOCKS_GUARD:
        lock = ICON_LOCKS.get(icon_id)
        if lock is None:
            lock = threading.Lock()
            ICON_LOCKS[icon_id] = lock
        return lock


def _is_valid_svg(data: bytes) -> bool:
    prefix = data[:4096].lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    return len(data) <= 600_000 and b"<svg" in prefix


def _ensure_icon_cached(icon_id: int, relative_path: str) -> Path:
    cache_path = ICON_CACHE_DIR / f"{icon_id}.svg"
    with _icon_lock(icon_id):
        if cache_path.is_file():
            try:
                cached = cache_path.read_bytes()
                if _is_valid_svg(cached):
                    return cache_path
                cache_path.unlink(missing_ok=True)
            except OSError:
                # Continue to a clean download attempt; failures will become a 502.
                pass

        remote_url = ICON_RAW_BASE + urllib.parse.quote(relative_path, safe="/")
        request = urllib.request.Request(
            remote_url,
            headers={"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "image/svg+xml"},
        )
        with urllib.request.urlopen(request, timeout=6) as remote:
            data = remote.read(600_001)
        if not _is_valid_svg(data):
            raise ValueError("Получен некорректный или слишком большой SVG-файл.")

        ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # A per-process unique temporary filename and os.replace prevent another
        # tab/request from observing a partially written SVG cache entry.
        tmp_path = cache_path.with_name(f"{cache_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with tmp_path.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, cache_path)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return cache_path


@app.get("/api/icons/{icon_id}")
def get_icon(icon_id: int):
    if icon_id < 0 or icon_id >= len(CATALOG):
        raise HTTPException(status_code=404, detail="Иконка не найдена.")
    item = CATALOG[icon_id]
    relative_path = ICON_MAP.get(item["name"])
    if not relative_path:
        raise HTTPException(status_code=404, detail="Для стратагемы нет игровой иконки.")
    try:
        cache_path = _ensure_icon_cached(icon_id, relative_path)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        LOGGER.warning("Не удалось получить SVG для %s: %s", item["name"], exc)
        raise HTTPException(status_code=502, detail=f"Не удалось загрузить игровую иконку: {exc}") from exc
    return FileResponse(
        cache_path, media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=604800, immutable", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/config")
def get_configuration():
    return public_config()


def public_config() -> dict:
    with CONFIG_LOCK:
        result = {key: CONFIG[key] for key in ("bindings", "open_key", "direction_keys", "press_ms", "gap_ms", "open_hold_ms")}
        result["revision"] = CONFIG_REVISION
        return result


@app.put("/api/config")
def update_configuration(payload: ConfigPayload):
    global CONFIG_REVISION
    with CONFIG_LOCK:
        current = public_config()
        if payload.revision != CONFIG_REVISION:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Конфигурация уже обновлена в другой вкладке.",
                    "config": current,
                },
            )
        previous = json.loads(json.dumps(CONFIG))
        previous_revision = CONFIG_REVISION
        CONFIG.update(payload.model_dump(exclude={"revision"}))
        CONFIG_REVISION += 1
        try:
            write_config(CONFIG)
        except OSError as exc:
            CONFIG.clear()
            CONFIG.update(previous)
            CONFIG_REVISION = previous_revision
            raise HTTPException(status_code=500, detail=f"Не удалось сохранить конфигурацию: {exc}") from exc
        updated = public_config()
        current_settings = {key: CONFIG.get(key) for key in ("open_key", "direction_keys", "press_ms", "gap_ms", "open_hold_ms")}

    changed_settings = [
        key for key in ("open_key", "direction_keys", "press_ms", "gap_ms", "open_hold_ms")
        if previous.get(key) != current_settings.get(key)
    ]
    events = [{
        "type": "config_updated",
        "config": updated,
        "revision": updated["revision"],
        "at": time.time(),
    }]
    if changed_settings:
        events.append({
            "type": "settings_updated",
            "settings": {key: updated[key] for key in ("open_key", "direction_keys", "press_ms", "gap_ms", "open_hold_ms")},
            "revision": updated["revision"],
            "at": time.time(),
        })
    publish_server_events(events)
    return {"ok": True, "config": updated}


@app.post("/api/macro/{binding_id}")
def run_macro(binding_id: str, payload: MacroPayload = MacroPayload()):
    if binding_id not in BINDING_BY_ID:
        raise HTTPException(status_code=404, detail="Неизвестная клавиша Numpad.")
    ok, message = MACROS.trigger(binding_id, require_game_focus=True, wait_for_game=payload.wait_for_game,
                                 wait_timeout_seconds=payload.wait_timeout_seconds)
    if not ok:
        status_code = 409 if "фокус" in message.lower() or "выполняется" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)
    return {"ok": True, "message": message}


@app.get("/api/macro/status")
def macro_status():
    return MACROS.snapshot()


def print_startup_info(host: str, port: int):
    print("\n" + "=" * 64)
    print("  HELLDIVERS 2 — STRATAGEM LAN SERVER")
    print("=" * 64)
    print(f"  Каталог: {len(CATALOG)} стратагем")
    print(f"  Назначаемых клавиш: {len(BINDING_KEYS)}")
    print(f"  Игровые SVG-иконки: {len(ICON_MAP)} (загружаются по мере просмотра и кешируются локально)")
    print("  Авторизация отключена: доступ открыт участникам локальной сети.")
    print("  Не настраивай проброс порта 8765 из интернета.")
    print("\n  Адреса для подключения:")
    print(f"  На этом ПК: http://127.0.0.1:{port}")
    addresses = get_local_ipv4()
    for address in addresses:
        print(f"  Локальная сеть: http://{address}:{port}")
    if not addresses:
        print(f"  Локальная сеть: http://IP-АДРЕС-ПК:{port}")
    print("\n  Глобальный hook перехватывает только назначенные клавиши Numpad 0–9 и . − + * /,")
    print("  и только когда Helldivers 2 находится в фокусе.")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print_startup_info(args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
