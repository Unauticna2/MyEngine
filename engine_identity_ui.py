"""Editor configuration and export for the optional registered-player server."""
from pathlib import Path
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from engine_scene import atomic_json
from engine_transactions import load_settings,settings

TEMPLATE=Path(__file__).resolve().parent/'templates'/'player-identity'
ANDROID=TEMPLATE.parent/'android-sms-gateway'

def export_server(destination):
    if not (TEMPLATE/'identity_server.py').is_file():raise ValueError('Шаблон сервера не установлен. Распакуй обновление полностью.')
    allowed={'app.py','identity_server.py','manage.py','requirements.txt','render.yaml','setup_secrets.py','setup_owner.cmd','README_RU.txt','README_TWILIO_R20.txt','.gitignore','static/index.html','static/verify.js','static/verify.css','registration.py','static/register.html','static/register.js','static/moderation.html','static/moderation.js','README_REGISTRATION_R23.txt','security_audit.py','static/device.js','README_SECURITY_R24.txt'}
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(allowed):
            path=TEMPLATE/name
            if path.is_file() and not path.is_symlink():archive.write(path,name)

def identity_dialog(editor):
    if not editor.can_edit():return
    root=Path(editor.path_root).resolve()
    try:current=load_settings(root)
    except Exception as error:editor.error(error);return
    window=tk.Toplevel(editor.window);window.title('MyEngine R24.1 — игроки и регистрация')
    window.geometry('650x650');window.transient(editor.window)
    frame=ttk.Frame(window,padding=18);frame.pack(fill='both',expand=True)
    required=tk.BooleanVar(value=current['identityRequired']);api=tk.StringVar(value=current['identityApi'])
    ttk.Label(frame,text='Игрок: SMS с твоего Android. Владелец: свой номер и пароль без SMS.',wraplength=600).pack(anchor='w',pady=8)
    ttk.Label(frame,text='Сервер для Render: HTTPS-адрес без пути').pack(anchor='w',pady=(12,3))
    ttk.Entry(frame,textvariable=api).pack(fill='x')
    ttk.Checkbutton(frame,text='Требовать проверку игрока: SMS / пароль владельца',variable=required).pack(anchor='w',pady=12)
    ttk.Label(frame,text='Регистрацию игроков включай в разделе «Управление регистрацией» на сайте: свободный доступ или заявки с одобрением. Вход владельца — с прежним номером и паролем.',wraplength=600).pack(anchor='w',pady=8)
    ttk.Label(frame,text='В Blueprint: UI Click → Branch (Player verified) → True: Load scene; False: Import certificate. После SMS нажми кнопку входа ещё раз.',wraplength=600).pack(anchor='w',pady=8)
    status=tk.StringVar();ttk.Label(frame,textvariable=status,wraplength=600).pack(anchor='w',pady=6)
    def save():
        try:
            if not editor.can_edit() or Path(editor.path_root).resolve()!=root:raise ValueError('Останови Play и открой это окно заново.')
            data=settings({**load_settings(root),'identityApi':api.get(),'identityRequired':required.get()})
            if required.get() and not data['identityApi']:raise ValueError('Сначала укажи HTTPS-адрес работающего сервера.')
            atomic_json(root/'payments.json',data);editor.refresh_project();status.set('Сохранено. Перезапусти Play.')
        except Exception as error:editor.error(error)
    def export():
        try:
            path=filedialog.asksaveasfilename(parent=window,title='Сервер проверки игроков',defaultextension='.zip',initialfile='MyEngine_PlayerIdentity_Server_R24.zip',filetypes=[('ZIP','*.zip')])
            if not path:return
            export_server(path)
            messagebox.showinfo('Сервер экспортирован','Порядок публикации и регистрации игроков — в README_RU.txt внутри ZIP. Экспорт не включает SMS и не публикует сервер.',parent=window)
        except Exception as error:editor.error(error)
    ttk.Button(frame,text='Сохранить проверку игрока',command=save).pack(fill='x',pady=5)
    ttk.Button(frame,text='Экспортировать сервер для Render…',command=export).pack(fill='x',pady=5)
    def open_registration(path):
        try:
            from engine_ui_media import open_url,https_url
            address=https_url(api.get().strip().rstrip('/'))
            from urllib.parse import urlsplit
            if urlsplit(address).path not in ('','/'):raise ValueError('Нужен адрес сервера без пути')
            open_url(address.rstrip('/')+path)
        except Exception as error:editor.error(error)
    ttk.Button(frame,text='Управление регистрацией — вход владельца',command=lambda:open_registration('/moderation')).pack(fill='x',pady=5)
    ttk.Button(frame,text='Открыть регистрацию игрока',command=lambda:open_registration('/register')).pack(fill='x',pady=5)
    def export_apk():
        try:
            source=ANDROID/'MyEngine_SMS_Gateway_R21.apk'
            if not source.exists():raise ValueError('APK не найден. Распакуй полный архив обновления R21.')
            target=filedialog.asksaveasfilename(parent=window,title='APK для твоего Android',initialfile=source.name,defaultextension='.apk',filetypes=[('Android APK','*.apk')])
            if target:shutil.copy2(source,target);status.set('APK сохранён. Установи на свой Android и настрой по инструкции сервера R21.')
        except Exception as error:editor.error(error)
    ttk.Button(frame,text='Сохранить Android-приложение (APK)…',command=export_apk).pack(fill='x',pady=5)
    return window
