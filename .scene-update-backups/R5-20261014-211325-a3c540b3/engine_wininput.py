"""Shared Win32 mouse ABI for slide UI and editor transform handles.

All consumers of a user32 instance must use the same ctypes structure types.
Windows LONG is 32 bits, including on Windows x64.
"""
import ctypes as C


class Point(C.Structure):
    _fields_ = [('x', C.c_int32), ('y', C.c_int32)]


class Rect(C.Structure):
    _fields_ = [('left', C.c_int32), ('top', C.c_int32),
               ('right', C.c_int32), ('bottom', C.c_int32)]


def configure_mouse(user):
    """Bind once during consumer initialization, never during frame polling."""
    signatures = {
        'GetCursorPos': ([C.POINTER(Point)], C.c_int32),
        'ScreenToClient': ([C.c_void_p, C.POINTER(Point)], C.c_int32),
        'GetClientRect': ([C.c_void_p, C.POINTER(Rect)], C.c_int32),
        'GetAsyncKeyState': ([C.c_int], C.c_short),
        'WindowFromPoint': ([Point], C.c_void_p),
        'GetForegroundWindow': ([], C.c_void_p),
    }
    for name, (args, result) in signatures.items():
        function = getattr(user, name)
        function.argtypes = args
        function.restype = result
