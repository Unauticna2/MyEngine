"""Windows certificate picker, on a daemon UI thread; no Tk in exported games."""
import ctypes as C
import sys
import threading

from engine_certificates import read_certificate


class OpenFilenameW(C.Structure):
    # Windows OPENFILENAMEW ABI, including Explorer extension fields.
    _fields_ = [('lStructSize', C.c_uint32), ('hwndOwner', C.c_void_p),
                ('hInstance', C.c_void_p), ('lpstrFilter', C.c_wchar_p),
                ('lpstrCustomFilter', C.c_wchar_p), ('nMaxCustFilter', C.c_uint32),
                ('nFilterIndex', C.c_uint32), ('lpstrFile', C.POINTER(C.c_wchar)),
                ('nMaxFile', C.c_uint32), ('lpstrFileTitle', C.c_wchar_p),
                ('nMaxFileTitle', C.c_uint32), ('lpstrInitialDir', C.c_wchar_p),
                ('lpstrTitle', C.c_wchar_p), ('Flags', C.c_uint32),
                ('nFileOffset', C.c_uint16), ('nFileExtension', C.c_uint16),
                ('lpstrDefExt', C.c_wchar_p), ('lCustData', C.c_ssize_t),
                ('lpfnHook', C.c_void_p), ('lpTemplateName', C.c_wchar_p),
                ('pvReserved', C.c_void_p), ('dwReserved', C.c_uint32), ('FlagsEx', C.c_uint32)]


class WindowsDialogs:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('Окно импорта сертификата доступно в Windows-версии игры')
        self.user = C.WinDLL('user32', use_last_error=True)
        self.common = C.WinDLL('comdlg32', use_last_error=True)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentThreadId.argtypes = []; kernel.GetCurrentThreadId.restype = C.c_uint32
        self.thread_id = kernel.GetCurrentThreadId()
        self.common.GetOpenFileNameW.argtypes = [C.POINTER(OpenFilenameW)]
        self.common.GetOpenFileNameW.restype = C.c_int
        self.common.CommDlgExtendedError.argtypes = []; self.common.CommDlgExtendedError.restype = C.c_uint32
        self.user.MessageBoxW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_wchar_p, C.c_uint32]
        self.user.MessageBoxW.restype = C.c_int
        self.cancelled = threading.Event()

    def pick(self, product):
        if self.cancelled.is_set():
            return None
        filename = C.create_unicode_buffer(32768)
        dialog = OpenFilenameW()
        dialog.lStructSize = C.sizeof(dialog)
        dialog.lpstrFilter = 'Сертификат MyEngine (*.json)\0*.json\0\0'
        dialog.nFilterIndex = 1; dialog.lpstrFile = filename; dialog.nMaxFile = len(filename)
        dialog.lpstrTitle = 'Загрузить сертификат — '+product
        dialog.lpstrDefExt = 'json'
        # Explorer, file/path must exist, preserve CWD, no recent-file shortcut.
        dialog.Flags = 0x00080000 | 0x00001000 | 0x00000800 | 0x00000008 | 0x02000000
        if not self.common.GetOpenFileNameW(C.byref(dialog)):
            error = self.common.CommDlgExtendedError()
            if error and not self.cancelled.is_set():
                raise OSError('Не удалось открыть выбор файла: '+hex(error))
            return None
        return None if self.cancelled.is_set() else filename.value

    def confirm(self, certificate, key):
        if self.cancelled.is_set():
            return False
        kind = 'разработчика (без оплаты)' if certificate['grantType'] == 'developer' else 'локальной активации'
        identity=getattr(self,'identity_required',False)
        text = ('Сертификат '+kind+'\n\nТовар: '+certificate['edition']+
                '\nID товара: '+certificate['productId']+'\nИгрок: '+certificate['playerId']+
                '\nКлюч Blueprint: '+key+ ('\n\nПродолжить проверку игрока в браузере (SMS / пароль владельца)?' if identity else '\n\nАктивировать доступ на этом компьютере?')+
                ('\n\nДо подтверждения сервером доступ останется закрыт.' if identity else '\n\nПодпись и банковская оплата этим файлом не подтверждаются.'))
        return self.user.MessageBoxW(None, text, 'Сертификат MyEngine', 0x4 | 0x20 | 0x100 | 0x10000) == 6

    def message(self, text, error=False):
        if not self.cancelled.is_set():
            self.user.MessageBoxW(None, text, 'Сертификат MyEngine', (0x10 if error else 0x40) | 0x10000)

    def close(self):
        self.cancelled.set()
        callback_type = C.WINFUNCTYPE(C.c_int, C.c_void_p, C.c_ssize_t)
        self.user.PostMessageW.argtypes = [C.c_void_p, C.c_uint32, C.c_size_t, C.c_ssize_t]
        self.user.PostMessageW.restype = C.c_int
        self.user.EnumThreadWindows.argtypes = [C.c_uint32, callback_type, C.c_ssize_t]
        self.user.EnumThreadWindows.restype = C.c_int
        @callback_type
        def close_window(hwnd, parameter):
            self.user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return 1
        self.user.EnumThreadWindows(self.thread_id, close_window, 0)


class CertificateDialog:
    def __init__(self, product, key, player_id='', *, backend_factory=None, message=None, error=False,identity_required=False):
        self.done = threading.Event(); self.cancelled = threading.Event()
        self.result = None; self.error = ''; self.backend = None
        def work():
            try:
                self.backend = (backend_factory or WindowsDialogs)()
                self.backend.identity_required=identity_required
                if self.cancelled.is_set():
                    self.backend.close(); return
                if message is not None:
                    self.backend.message(message, error); return
                path = self.backend.pick(product)
                if not path or self.cancelled.is_set():
                    return
                certificate = read_certificate(path, product, player_id)
                if self.backend.confirm(certificate, key) and not self.cancelled.is_set():
                    self.result = certificate
            except Exception as exception:
                self.error = str(exception)
                if self.backend is not None and not self.cancelled.is_set():
                    try: self.backend.message(self.error, True)
                    except Exception: pass
            finally:
                self.done.set()
        self.thread = threading.Thread(target=work, name='certificate-dialog', daemon=True)
        self.thread.start()

    def close(self):
        self.cancelled.set()
        if self.backend is not None:
            try: self.backend.close()
            except Exception: pass

