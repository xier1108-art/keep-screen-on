# -*- coding: utf-8 -*-
"""
화면안꺼지게 — Windows 화면 절전 방지 트레이 앱
단축키: Ctrl+Shift+K (토글)
"""
import ctypes
import ctypes.wintypes
import json
import os
import sys
import threading
import time

import pystray
from PIL import Image, ImageDraw

# ──────────────────────────────────────────
# 상수
# ──────────────────────────────────────────
APP_NAME = "화면안꺼지게"
MUTEX_NAME = "Global\\KeepAwakeMutex"
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", "."), "keepawake")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

# SetThreadExecutionState 플래그
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# 핫키 (Ctrl+Shift+K)
HOTKEY_ID = 1
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312
VK_K = ord("K")

# 배터리 상태
AC_LINE_STATUS_OFFLINE = 0  # 배터리 사용 중

DEFAULT_SETTINGS = {
    "timer_minutes": 0,
    "battery_aware": False,
}


# ──────────────────────────────────────────
# 설정 I/O
# ──────────────────────────────────────────
def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {**DEFAULT_SETTINGS, **data}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(s: dict) -> None:
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ──────────────────────────────────────────
# Windows API
# ──────────────────────────────────────────
def set_keep_alive(active: bool) -> None:
    """화면 절전 방지 활성화/비활성화"""
    if active:
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
    else:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def is_on_battery() -> bool:
    """현재 배터리 사용 중인지 확인"""
    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_byte),
            ("BatteryFlag", ctypes.c_byte),
            ("BatteryLifePercent", ctypes.c_byte),
            ("SystemStatusFlag", ctypes.c_byte),
            ("BatteryLifeTime", ctypes.wintypes.DWORD),
            ("BatteryFullLifeTime", ctypes.wintypes.DWORD),
        ]

    status = SYSTEM_POWER_STATUS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
    return status.ACLineStatus == AC_LINE_STATUS_OFFLINE


# ──────────────────────────────────────────
# 아이콘 생성 (Pillow, 외부 파일 불필요)
# ──────────────────────────────────────────
def _fixed_make_icon_active() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 46], radius=4, fill="#2E7D32")
    d.rectangle([10, 10, 54, 42], fill="#A5D6A7")
    d.rectangle([29, 46, 35, 54], fill="#2E7D32")
    d.rectangle([20, 54, 44, 58], fill="#2E7D32")
    cx, cy = 32, 26
    d.arc([cx - 9, cy - 9, cx + 9, cy + 9], start=40, end=320, fill="white", width=3)
    d.line([cx, cy - 9, cx, cy - 2], fill="white", width=3)
    return img


def _fixed_make_icon_paused() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 46], radius=4, fill="#616161")
    d.rectangle([10, 10, 54, 42], fill="#E0E0E0")
    d.rectangle([29, 46, 35, 54], fill="#616161")
    d.rectangle([20, 54, 44, 58], fill="#616161")
    cx, cy = 32, 26
    d.rectangle([cx - 7, cy - 8, cx - 3, cy + 8], fill="#616161")
    d.rectangle([cx + 3, cy - 8, cx + 7, cy + 8], fill="#616161")
    return img


# ──────────────────────────────────────────
# 메인 앱
# ──────────────────────────────────────────
class KeepAwakeApp:
    def __init__(self):
        self.settings = load_settings()
        self.active = True
        self.timer_minutes: int = self.settings.get("timer_minutes", 0)
        self.timer_end: float | None = (
            time.time() + self.timer_minutes * 60 if self.timer_minutes > 0 else None
        )
        self.battery_aware: bool = self.settings.get("battery_aware", False)

        self._stop_event = threading.Event()
        self._hotkey_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self.icon_active = _fixed_make_icon_active()
        self.icon_paused = _fixed_make_icon_paused()

        self.tray = pystray.Icon(
            APP_NAME,
            icon=self.icon_active,
            title=self._make_tooltip(),
            menu=self._build_menu(),
        )

    # ── 상태 관리 ──────────────────────────
    def toggle(self, icon=None, item=None):
        with self._lock:
            self.active = not self.active
            set_keep_alive(self.active)
        self._refresh()

    def set_timer(self, minutes: int):
        with self._lock:
            self.timer_minutes = minutes
            self.timer_end = time.time() + minutes * 60 if minutes > 0 else None
            self.settings["timer_minutes"] = minutes
        save_settings(self.settings)
        self._refresh()

    def toggle_battery_aware(self, icon=None, item=None):
        with self._lock:
            self.battery_aware = not self.battery_aware
            self.settings["battery_aware"] = self.battery_aware
        save_settings(self.settings)
        self._refresh()

    def quit_app(self, icon=None, item=None):
        self._stop_event.set()
        set_keep_alive(False)
        save_settings(self.settings)
        self.tray.stop()

    # ── 툴팁 ───────────────────────────────
    def _make_tooltip(self) -> str:
        with self._lock:
            active = self.active
            end = self.timer_end
        if not active:
            return f"{APP_NAME} — 일시 중지됨"
        if end is not None:
            remaining = max(0, int((end - time.time()) / 60))
            return f"{APP_NAME} — 유지 중 ({remaining}분 남음)"
        return f"{APP_NAME} — 유지 중"

    def _make_status_text(self, item=None) -> str:
        with self._lock:
            active = self.active
            end = self.timer_end
        if not active:
            return "○ 일시 중지됨"
        if end is not None:
            remaining = max(0, int((end - time.time()) / 60))
            return f"● 유지 중 ({remaining}분 남음)"
        return "● 유지 중"

    # ── 트레이 메뉴 ────────────────────────
    def _build_menu(self) -> pystray.Menu:
        timer_items = [
            pystray.MenuItem(
                label,
                action,
                checked=lambda item, m=mins: self.timer_minutes == m,
                radio=True,
            )
            for label, mins, action in [
                ("없음 (무제한)", 0, lambda icon, item: self.set_timer(0)),
                ("30분", 30, lambda icon, item: self.set_timer(30)),
                ("1시간", 60, lambda icon, item: self.set_timer(60)),
                ("2시간", 120, lambda icon, item: self.set_timer(120)),
                ("4시간", 240, lambda icon, item: self.set_timer(240)),
            ]
        ]

        return pystray.Menu(
            pystray.MenuItem(
                self._make_status_text,
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "▶  활성화" if not self.active else "⏸  일시 중지",
                self.toggle,
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "⏱  자동 종료 타이머",
                pystray.Menu(*timer_items),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "🔋  배터리 절약 모드",
                self.toggle_battery_aware,
                checked=lambda item: self.battery_aware,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("✖  완전 종료", self.quit_app),
        )

    def _refresh(self):
        """아이콘 이미지 + 툴팁 + 메뉴 갱신"""
        with self._lock:
            active = self.active
        self.tray.icon = self.icon_active if active else self.icon_paused
        self.tray.title = self._make_tooltip()
        self.tray.menu = self._build_menu()

    # ── 백그라운드 워커 ────────────────────
    def _worker_loop(self):
        while not self._stop_event.is_set():
            with self._lock:
                active = self.active
                end = self.timer_end
                battery_aware = self.battery_aware

            # SetThreadExecutionState 재호출 (일부 앱이 초기화할 수 있으므로)
            if active:
                set_keep_alive(True)

            # 타이머 만료 확인
            if active and end is not None and time.time() >= end:
                with self._lock:
                    self.active = False
                    self.timer_end = None
                    self.timer_minutes = 0
                    self.settings["timer_minutes"] = 0
                set_keep_alive(False)
                save_settings(self.settings)
                self._refresh()

            # 배터리 절약 모드
            elif active and battery_aware and is_on_battery():
                with self._lock:
                    self.active = False
                set_keep_alive(False)
                self._refresh()

            # 툴팁 갱신 (남은 시간 표시)
            self.tray.title = self._make_tooltip()

            self._stop_event.wait(30)

    # ── 핫키 (Ctrl+Shift+K) ───────────────
    def _hotkey_listener_loop(self):
        registered = ctypes.windll.user32.RegisterHotKey(
            None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_K
        )
        if not registered:
            return  # 핫키 충돌 시 조용히 무시

        msg = ctypes.wintypes.MSG()
        while not self._stop_event.is_set():
            # PeekMessage — 비블로킹
            result = ctypes.windll.user32.PeekMessageW(
                ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1  # PM_REMOVE
            )
            if result:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.toggle()
            time.sleep(0.1)

        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)

    # ── 실행 ──────────────────────────────
    def run(self):
        set_keep_alive(True)

        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="worker"
        )
        self._worker_thread.start()

        self._hotkey_thread = threading.Thread(
            target=self._hotkey_listener_loop, daemon=True, name="hotkey"
        )
        self._hotkey_thread.start()

        self.tray.run()


# ──────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────
if __name__ == "__main__":
    # 단일 인스턴스 가드
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)

    app = KeepAwakeApp()
    app.run()
