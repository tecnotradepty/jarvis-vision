"""Native Windows DPI-aware mouse, keyboard, media & system input helpers."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CXSCREEN = 0
SM_CYSCREEN = 1

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

# Windows Virtual-Key codes for media & system shortcuts
VK_TAB = 0x09
VK_MENU = 0x12      # Alt
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_D = 0x44
VK_S = 0x53
VK_F4 = 0x73
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_mutex_handle = None


def acquire_single_instance(mutex_name: str = "Local\\GeminiDesktopAppMutex") -> bool:
    """Return True if this is the sole running instance; False if already running."""
    global _mutex_handle
    handle = _kernel32.CreateMutexW(None, True, mutex_name)
    if not handle:
        return True
    if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def focus_existing_window(title: str = "Gemini // Asistente") -> bool:
    """Bring an existing Gemini Desktop window to front if visible or minimized."""
    hwnd = _user32.FindWindowW(None, title)
    if hwnd:
        _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.SetForegroundWindow(hwnd)
        return True
    return False


def enable_dpi_awareness() -> None:
    try:
        _user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass


def get_primary_screen_size() -> tuple[int, int]:
    return int(_user32.GetSystemMetrics(SM_CXSCREEN)), int(_user32.GetSystemMetrics(SM_CYSCREEN))


def get_virtual_screen_rect() -> tuple[int, int, int, int]:
    return (
        int(_user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def _send_mouse(dx: int = 0, dy: int = 0, mouse_data: int = 0, flags: int = 0) -> None:
    inp = INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(
            dx=dx,
            dy=dy,
            mouseData=mouse_data & 0xFFFFFFFF,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        ),
    )
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_key(vk: int, repeat: int = 1) -> None:
    """Tap a single Windows Virtual-Key code one or more times."""
    ext_keys = {VK_LEFT, VK_RIGHT, VK_LWIN, VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP,
                VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK, VK_MEDIA_STOP, VK_MEDIA_PLAY_PAUSE}
    ext_flag = KEYEVENTF_EXTENDEDKEY if vk in ext_keys else 0
    for _ in range(max(1, repeat)):
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=ext_flag, time=0, dwExtraInfo=0))
        up = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=ext_flag | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0),
        )
        arr = (INPUT * 2)(down, up)
        _user32.SendInput(2, arr, ctypes.sizeof(INPUT))


def send_hotkey(*vks: int) -> None:
    """Press a key chord simultaneously (e.g. VK_LWIN, VK_D) then release in reverse."""
    inputs: list[INPUT] = []
    for vk in vks:
        inputs.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)))
    for vk in reversed(vks):
        inputs.append(
            INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))
        )
    arr = (INPUT * len(inputs))(*inputs)
    _user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def lock_workstation() -> None:
    """Lock the Windows session."""
    _user32.LockWorkStation()


class WindowsMouseController:
    """High-frequency, zero-delay Windows mouse controller."""

    def __init__(self) -> None:
        enable_dpi_awareness()
        self.screen_w, self.screen_h = get_primary_screen_size()
        self._left_down = False

    def refresh_screen_size(self) -> tuple[int, int]:
        self.screen_w, self.screen_h = get_primary_screen_size()
        return self.screen_w, self.screen_h

    def move_to(self, x: int, y: int) -> None:
        vx, vy, vw, vh = get_virtual_screen_rect()
        vw = max(vw, 1)
        vh = max(vh, 1)
        abs_x = int((x - vx) * 65535 / max(vw - 1, 1))
        abs_y = int((y - vy) * 65535 / max(vh - 1, 1))
        abs_x = min(max(abs_x, 0), 65535)
        abs_y = min(max(abs_y, 0), 65535)
        _send_mouse(
            dx=abs_x,
            dy=abs_y,
            flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        )

    def left_down(self) -> None:
        if not self._left_down:
            _send_mouse(flags=MOUSEEVENTF_LEFTDOWN)
            self._left_down = True

    def left_up(self) -> None:
        if self._left_down:
            _send_mouse(flags=MOUSEEVENTF_LEFTUP)
            self._left_down = False

    def left_click(self) -> None:
        _send_mouse(flags=MOUSEEVENTF_LEFTDOWN)
        _send_mouse(flags=MOUSEEVENTF_LEFTUP)
        self._left_down = False

    def right_click(self) -> None:
        _send_mouse(flags=MOUSEEVENTF_RIGHTDOWN)
        _send_mouse(flags=MOUSEEVENTF_RIGHTUP)

    def scroll(self, delta_units: float) -> None:
        ticks = int(round(delta_units * WHEEL_DELTA))
        if ticks != 0:
            _send_mouse(mouse_data=ticks, flags=MOUSEEVENTF_WHEEL)

    def release_all(self) -> None:
        self.left_up()
