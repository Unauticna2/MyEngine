"""Restore Windows text services and focus when leaving the native viewport.

The viewport is a child window owned by another process. Tk's remembered
focus can outlive the actual Win32 focus; repair it only on an explicit click
or focus event in an editor text control, never from a frame timer.
"""
import ctypes as C
from pathlib import Path
import subprocess
import sys

_text_services_attempted = False
TEXT_CLASSES = {'Entry', 'TEntry', 'Text', 'Spinbox', 'TSpinbox', 'TCombobox'}


def start_text_services(log=lambda message: None):
    global _text_services_attempted
    if sys.platform != 'win32' or _text_services_attempted:
        return
    _text_services_attempted = True
    try:
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.GetSystemDirectoryW.argtypes = [C.c_wchar_p, C.c_uint]
        kernel.GetSystemDirectoryW.restype = C.c_uint
        buffer = C.create_unicode_buffer(32768)
        length = kernel.GetSystemDirectoryW(buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise OSError('Windows system directory is unavailable')
        executable = Path(buffer.value) / 'ctfmon.exe'
        if not executable.is_file():
            raise OSError('Windows Text Services executable is missing')
        # System component, one launch per editor process; Windows handles an
        # already-running instance. No scheduled tasks or registry changes.
        subprocess.Popen([str(executable)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as error:
        log('TEXT INPUT: ' + str(error))


class EditorTextFocus:
    def __init__(self, window, log=lambda message: None, *, user=None):
        self.window = window
        self.user = user
        self.bindings = []
        if sys.platform != 'win32' and user is None:
            return
        start_text_services(log)
        if self.user is None:
            self.user = C.WinDLL('user32', use_last_error=True)
        for name, arguments, result in (
                ('SetFocus', [C.c_void_p], C.c_void_p),
                ('GetFocus', [], C.c_void_p),
                ('GetForegroundWindow', [], C.c_void_p),
                ('GetAncestor', [C.c_void_p, C.c_uint], C.c_void_p)):
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        # bind_all is appended after Tk's normal widget/class bindings and also
        # covers text controls created later in Inspector and configuration dialogs.
        for event in ('<ButtonPress-1>', '<FocusIn>'):
            self.bindings.append(window.bind_all(event, self.restore, add='+'))

    def restore(self, event):
        widget = event.widget
        try:
            if widget.winfo_class() not in TEXT_CLASSES or not widget.winfo_exists():
                return
            hwnd = widget.winfo_id()
            foreground = self.user.GetForegroundWindow()
            if not foreground or foreground != self.user.GetAncestor(hwnd, 2):
                return  # Do not activate a background editor or another dialog.
            if self.user.GetFocus() != hwnd:
                self.user.SetFocus(hwnd)
            if widget.focus_get() != widget:
                widget.focus_set()
        except Exception:
            # Destruction/recreation during a selection change can invalidate a
            # pending focus event. Never disable the editor because of that race.
            return
