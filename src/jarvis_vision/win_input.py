"""Native Windows DPI-aware mouse input via user32.SendInput."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

# DPI awareness constants
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

# System metrics
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# SendInput mouse flags
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

WHEEL_DELTA = 120

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)


def enable_dpi_awareness() -> None:
    """Make current process Per-Monitor V2 DPI aware so coordinates match physical pixels."""
    try:
        _user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass


def get_primary_screen_size() -> tuple[int, int]:
    """Return primary display width and height in pixels."""
    return int(_user32.GetSystemMetrics(SM_CXSCREEN)), int(_user32.GetSystemMetrics(SM_CYSCREEN))


def get_virtual_screen_rect() -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of the Windows virtual desktop."""
    return (
        int(_user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(_user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def get_cursor_pos() -> tuple[int, int]:
    """Return current OS cursor (x, y)."""
    pt = POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


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
        """Move cursor to absolute primary-monitor coordinates (x, y)."""
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
        """Scroll vertically; positive scrolls up, negative scrolls down."""
        ticks = int(round(delta_units * WHEEL_DELTA))
        if ticks != 0:
            _send_mouse(mouse_data=ticks, flags=MOUSEEVENTF_WHEEL)

    def release_all(self) -> None:
        """Ensure no mouse button remains stuck when pausing or exiting."""
        self.left_up()
