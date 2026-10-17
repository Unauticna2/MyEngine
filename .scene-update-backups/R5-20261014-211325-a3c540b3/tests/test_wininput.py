"""Regression: slide UI polling must not invalidate the gizmo's ctypes ABI.

Callbacks are real ctypes function pointers, so argument conversion is checked
even on a test host without user32. This is not a Windows GUI integration test.
"""
import ctypes as C
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from engine_gizmo import WinMouse
from engine_runtime import NativeCore
from engine_ui import SlideUI
from engine_wininput import Point, Rect, configure_mouse


class User32Fixture:
    def __init__(self):
        self.hwnd = 0x123456789 if C.sizeof(C.c_void_p) == 8 else 123
        self.foreground = self.hwnd
        self.down = True
        self.snap = True
        self.failed = None
        self.handles = []
        make = getattr(C, 'WINFUNCTYPE', C.CFUNCTYPE)
        self.GetCursorPos = make(C.c_int32, C.c_void_p)(self.cursor)
        self.ScreenToClient = make(C.c_int32, C.c_void_p, C.c_void_p)(self.client)
        self.GetClientRect = make(C.c_int32, C.c_void_p, C.c_void_p)(self.bounds)
        self.GetAsyncKeyState = make(C.c_short, C.c_int)(self.key)
        self.WindowFromPoint = make(C.c_void_p, Point)(lambda p: self.hwnd)
        self.GetForegroundWindow = make(C.c_void_p)(lambda: self.foreground)

    def cursor(self, address):
        if self.failed == 'cursor': return 0
        point = C.cast(address, C.POINTER(Point)).contents
        point.x, point.y = 320, 240
        return 1

    def client(self, hwnd, address):
        self.handles.append(hwnd)
        if self.failed == 'client': return 0
        point = C.cast(address, C.POINTER(Point)).contents
        point.x -= 20
        point.y -= 40
        return 1

    def bounds(self, hwnd, address):
        self.handles.append(hwnd)
        if self.failed == 'bounds': return 0
        rect = C.cast(address, C.POINTER(Rect)).contents
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1280, 720
        return 1

    def key(self, code):
        return -32768 if {1: self.down, 17: self.snap}.get(code, False) else 0


class MouseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.user = User32Fixture()
        self.core = NativeCore.__new__(NativeCore)
        self.core.user, self.core.hwnd = self.user, self.user.hwnd
        configure_mouse(self.user)
        self.mouse = WinMouse(self.core)

    def test_slide_ui_and_gizmo_poll_repeatedly_in_both_orders(self):
        for frame in range(100):
            # Reinitializing a viewport consumer must also keep both compatible.
            if frame == 50: self.mouse = WinMouse(self.core)
            if frame % 2: self.mouse.poll()
            self.assertEqual(self.core.pointer(), (300, 200, True, 1280, 720))
            self.assertEqual(self.mouse.poll(), ((300, 200), True, True, True))
        self.assertTrue(all(hwnd == self.user.hwnd for hwnd in self.user.handles))

    def test_ui_button_works_while_gizmo_is_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = {'format': 1, 'kind': 'MyEngine.UI', 'width': 1280, 'height': 720,
                        'startSlide': '1', 'slides': [{'id': '1', 'elements': [
                            {'id': 'close', 'rect': [250, 150, 100, 100],
                             'onClick': [{'action': 'ui', 'enabled': False}]}]}]}
            (root/'interface.ui.json').write_text(json.dumps(document), encoding='utf-8')
            ui = SlideUI(SimpleNamespace(root=root), 'interface.ui.json')
            ui.update(.016, self.core.pointer())
            self.assertTrue(self.mouse.poll()[1])
            self.user.down = False
            ui.update(.016, self.core.pointer())
            self.assertFalse(self.mouse.poll()[1])
            self.assertFalse(ui.enabled)

    def test_focus_and_failed_native_queries_do_not_report_false_clicks(self):
        self.user.foreground = None
        self.assertEqual(self.core.pointer(), (-1, -1, False, 1280, 720))
        self.user.foreground = self.user.hwnd
        for failure in ('cursor', 'client'):
            with self.subTest(failure=failure):
                self.user.failed = failure
                self.assertEqual(self.core.pointer(), (-1, -1, False, 1280, 720))
                self.assertEqual(self.mouse.poll(), ((0, 0), False, False, False))
        self.user.failed = 'bounds'
        self.assertEqual(self.core.pointer(), (-1, -1, False, 0, 0))

    def test_fixed_windows_structure_layout(self):
        self.assertEqual(C.sizeof(Point), 8)
        self.assertEqual(Point.y.offset, 4)
        self.assertEqual(C.sizeof(Rect), 16)
        self.assertEqual(Rect.bottom.offset, 12)


if __name__ == '__main__': unittest.main()
