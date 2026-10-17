"""Right-click title-bar menu on our own Win32 window. Native game commands use an ASM mailbox; Tk windows use their UI thread."""
from pathlib import Path
import ctypes as C
import os
import queue
import sys
import threading
import time

RESTORE, FULLSCREEN, ABOUT, UNLOCK = 0x1E10, 0x1E20, 0x1E30, 0x1E40
_kept_callbacks = []  # Keep callback memory alive until the interpreter exits.

class Rect(C.Structure):
    _fields_=[('left',C.c_int32),('top',C.c_int32),('right',C.c_int32),('bottom',C.c_int32)]
class Point(C.Structure):
    _fields_=[('x',C.c_int32),('y',C.c_int32)]
class Placement(C.Structure):
    _fields_=[('length',C.c_uint32),('flags',C.c_uint32),('showCmd',C.c_uint32),
              ('ptMinPosition',Point),('ptMaxPosition',Point),('rcNormalPosition',Rect)]
class MonitorInfo(C.Structure):
    _fields_=[('cbSize',C.c_uint32),('rcMonitor',Rect),('rcWork',Rect),('dwFlags',C.c_uint32)]

def message(text, error=False):
    if sys.platform!='win32':print(text);return
    user=C.WinDLL('user32',use_last_error=True)
    user.MessageBoxW.argtypes=[C.c_void_p,C.c_wchar_p,C.c_wchar_p,C.c_uint32]
    user.MessageBoxW.restype=C.c_int
    user.MessageBoxW(None,str(text),'MyEngine 2',0x10000 | (0x10 if error else 0x40))

class TitleMenu:
    def __init__(self, hwnd, root, access_root=None, native_poll=None):
        if sys.platform!='win32':raise RuntimeError('Windows title menu is unavailable on this platform')
        self.hwnd=int(hwnd);self.root=Path(root).resolve();self.access_root=Path(access_root or root).resolve()
        self.native_poll=native_poll
        self.commands=queue.SimpleQueue();self.closed=False;self.fullscreen=False;self.recovery=None;self.last_check=0
        self.user=C.WinDLL('user32',use_last_error=True)
        P=C.c_void_p;U=C.c_uint32;S=C.c_ssize_t;Z=C.c_size_t;I=C.c_int
        signatures={
            'GetWindowThreadProcessId':(U,[P,C.POINTER(U)]), 'GetWindowLongPtrW':(S,[P,I]),
            'SetWindowLongPtrW':(S,[P,I,S]), 'GetSystemMenu':(P,[P,I]),
            'AppendMenuW':(I,[P,U,Z,C.c_wchar_p]), 'DeleteMenu':(I,[P,U,U]),
            'CheckMenuItem':(U,[P,U,U]), 'DrawMenuBar':(I,[P]),
            'CallWindowProcW':(S,[P,P,U,Z,S]), 'IsWindow':(I,[P]),
            'GetWindowPlacement':(I,[P,C.POINTER(Placement)]),
            'SetWindowPlacement':(I,[P,C.POINTER(Placement)]),
            'MonitorFromWindow':(P,[P,U]), 'GetMonitorInfoW':(I,[P,C.POINTER(MonitorInfo)]),
            'SetWindowPos':(I,[P,P,I,I,I,I,U]), 'ShowWindow':(I,[P,I])}
        for name,(ret,args) in signatures.items():
            f=getattr(self.user,name);f.restype=ret;f.argtypes=args
        pid=U();self.user.GetWindowThreadProcessId(self.hwnd,C.byref(pid))
        if pid.value!=os.getpid():raise ValueError('Title menu can only attach to this process')
        if self.user.GetWindowLongPtrW(self.hwnd,-16)&0x40000000:raise ValueError('Use the editor title bar, not its child viewport')
        self.menu=self.user.GetSystemMenu(self.hwnd,False)
        if not self.menu:raise C.WinError(C.get_last_error())
        self.user.AppendMenuW(self.menu,0x800,0,None)
        for command,label in ((RESTORE,'Восстановить с GitHub…'),(FULLSCREEN,'Полный экран\tF11'),
                              (ABOUT,'О программе / номер сборки…'),(UNLOCK,'Разблокировать всё (донат добровольный)')):
            if not self.user.AppendMenuW(self.menu,0,command,label):raise C.WinError(C.get_last_error())
        if self.native_poll is not None:
            self.refresh_checkmarks();self.user.DrawMenuBar(self.hwnd)
            return
        callback_type=C.WINFUNCTYPE(S,P,U,Z,S)
        self.old_proc=self.user.GetWindowLongPtrW(self.hwnd,-4)
        @callback_type
        def callback(hwnd,msg,wparam,lparam):
            try:
                if not self.closed:
                    if msg==0x112 and (wparam&0xFFF0) in (RESTORE,FULLSCREEN,ABOUT,UNLOCK):
                        self.commands.put(wparam&0xFFF0);return 0
                    if msg==0x100 and wparam==0x7A:  # F11, once per key press.
                        if not (lparam&(1<<30)):self.commands.put(FULLSCREEN)
                        return 0
                    if msg==0x101 and wparam==0x7A:return 0
                    if msg==0x82:self.closed=True  # WM_NCDESTROY
            except Exception as ex:print('WINDOW MENU:',ex)
            return self.user.CallWindowProcW(self.old_proc,hwnd,msg,wparam,lparam)
        self.callback=callback;_kept_callbacks.append(callback)
        C.set_last_error(0)
        previous=self.user.SetWindowLongPtrW(self.hwnd,-4,C.cast(callback,P).value)
        if not previous and C.get_last_error():raise C.WinError(C.get_last_error())
        self.old_proc=previous or self.old_proc
        self.refresh_checkmarks();self.user.DrawMenuBar(self.hwnd)

    def refresh_checkmarks(self):
        from engine_access import unlock_all
        self.user.CheckMenuItem(self.menu,UNLOCK,8 if unlock_all(self.access_root) else 0)
        self.user.CheckMenuItem(self.menu,FULLSCREEN,8 if self.fullscreen else 0)

    def toggle_fullscreen(self):
        u=self.user
        if not self.fullscreen:
            placement=Placement();placement.length=C.sizeof(Placement)
            monitor=MonitorInfo();monitor.cbSize=C.sizeof(MonitorInfo)
            if not u.GetWindowPlacement(self.hwnd,C.byref(placement)):raise C.WinError()
            if not u.GetMonitorInfoW(u.MonitorFromWindow(self.hwnd,2),C.byref(monitor)):raise C.WinError()
            self.placement=placement;self.style=u.GetWindowLongPtrW(self.hwnd,-16)
            u.ShowWindow(self.hwnd,9) # Restore before removing the frame.
            u.SetWindowLongPtrW(self.hwnd,-16,self.style&~(0x00C00000|0x00040000))
            r=monitor.rcMonitor
            u.SetWindowPos(self.hwnd,None,r.left,r.top,r.right-r.left,r.bottom-r.top,0x24)
            self.fullscreen=True
        else:
            u.SetWindowLongPtrW(self.hwnd,-16,self.style)
            u.SetWindowPlacement(self.hwnd,C.byref(self.placement))
            u.SetWindowPos(self.hwnd,None,0,0,0,0,0x37)
            self.fullscreen=False
        self.refresh_checkmarks()

    def poll(self):
        if self.closed:return
        if self.native_poll is not None:
            command=self.native_poll()
            if command:self.commands.put(command)
        if time.monotonic()-self.last_check>=1:
            self.last_check=time.monotonic();self.refresh_checkmarks()
        while not self.commands.empty():
            command=self.commands.get()
            try:
                if command==FULLSCREEN:self.toggle_fullscreen()
                elif command==ABOUT:
                    from engine_version import description
                    text=description(self.root)
                    threading.Thread(target=message,args=(text,),daemon=True,name='build-info').start()
                elif command==UNLOCK:
                    from engine_access import unlock_all,set_unlock_all
                    set_unlock_all(self.access_root,not unlock_all(self.access_root));self.refresh_checkmarks()
                elif command==RESTORE:
                    from engine_recovery_ui import RecoveryTask
                    if self.recovery is None or self.recovery.done.is_set():self.recovery=RecoveryTask(self.root)
            except Exception as ex:
                threading.Thread(target=message,args=(str(ex),True),daemon=True).start()

    def close(self):
        if self.recovery:self.recovery.close()
        if self.closed:return
        self.closed=True
        if self.user.IsWindow(self.hwnd):
            # Do not overwrite another library's subsequently installed subclass.
            if self.native_poll is None and self.user.GetWindowLongPtrW(self.hwnd,-4)==C.cast(self.callback,C.c_void_p).value:
                self.user.SetWindowLongPtrW(self.hwnd,-4,self.old_proc)
            for command in (RESTORE,FULLSCREEN,ABOUT,UNLOCK):self.user.DeleteMenu(self.menu,command,0)
            self.user.DrawMenuBar(self.hwnd)
        if self.recovery:self.recovery.close()


def attach_tk(window, root, access_root=None):
    if sys.platform!='win32':return None
    try:
        window.update_idletasks()
        user=C.WinDLL('user32',use_last_error=True)
        user.GetAncestor.argtypes=[C.c_void_p,C.c_uint32];user.GetAncestor.restype=C.c_void_p
        menu=TitleMenu(user.GetAncestor(window.winfo_id(),2),root,access_root)
        def poll():
            if not menu.closed and window.winfo_exists():menu.poll();window.after(100,poll)
        window.after(100,poll)
        held=[False]
        def key_down(event):
            if not held[0]:menu.commands.put(FULLSCREEN)
            held[0]=True
            return 'break'
        def key_up(event):held[0]=False
        window.bind('<KeyPress-F11>',key_down,add='+')
        window.bind('<KeyRelease-F11>',key_up,add='+')
        window.bind('<FocusOut>',key_up,add='+')
        window.bind('<Destroy>',lambda event:menu.close() if event.widget is window else None,add='+')
        return menu
    except Exception as ex:
        print('WINDOW MENU:',ex);return None
