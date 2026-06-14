import ctypes
import os
import shutil
from ctypes import wintypes
import cv2
import numpy as np
import config

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi
shcore = ctypes.windll.shcore

try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()

DWMWA_EXTENDED_FRAME_BOUNDS = 9
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
    @property
    def width(self): return self.right - self.left
    @property
    def height(self): return self.bottom - self.top
    @property
    def area(self): return self.width * self.height
    def __repr__(self): return f"{self.left},{self.top},{self.right},{self.bottom} ({self.width}x{self.height})"

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

def boot_clean_directory():
    if os.path.exists(config.DEBUG_DIR):
        shutil.rmtree(config.DEBUG_DIR)
    os.makedirs(config.DEBUG_DIR, exist_ok=True)

def get_window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value

def get_true_dwm_rect(hwnd):
    rect = RECT()
    hr = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS), ctypes.byref(rect), ctypes.sizeof(rect))
    if hr != 0 or rect.width <= 0 or rect.height <= 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect

def find_tracker_hwnds():
    hwnds = []
    def callback(hwnd, lparam):
        title = get_window_text(hwnd).strip().lower()
        if title not in ["valorant tracker", "valorant tracker: duels"]:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        rect = get_true_dwm_rect(hwnd)
        if rect.width > 100 and rect.height > 100:
            hwnds.append(hwnd)
            print(f"[FOUND] hwnd={hwnd} title={title!r} rect={rect}")
        return True
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(enum_proc(callback), 0)
    return hwnds

def capture_rect_to_opencv(rect):
    w, h = rect.width, rect.height
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old_obj = gdi32.SelectObject(mem_dc, bitmap)
    try:
        ok = gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, rect.left, rect.top, SRCCOPY | CAPTUREBLT)
        if not ok:
            raise RuntimeError("BitBlt failed")
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bmi.bmiHeader.biSizeImage = w * h * 4
        buffer = ctypes.create_string_buffer(w * h * 4)
        lines = gdi32.GetDIBits(mem_dc, bitmap, 0, h, buffer, ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines != h:
            raise RuntimeError(f"GetDIBits failed: {lines}/{h}")
        img = np.frombuffer(buffer.raw, dtype=np.uint8).reshape((h, w, 4))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    finally:
        gdi32.SelectObject(mem_dc, old_obj)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)

def capture_all_tracker_windows(hwnds):
    outputs = {}
    for hwnd in hwnds:
        title = get_window_text(hwnd).strip().lower()
        rect = get_true_dwm_rect(hwnd)
        label = "live_duels" if title == "valorant tracker: duels" else "scoreboard"
        img = capture_rect_to_opencv(rect)
        path = os.path.join(config.DEBUG_DIR, f"{label}.png")
        cv2.imwrite(path, img)
        outputs[label] = path
    return outputs