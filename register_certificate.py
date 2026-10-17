"""Private desktop registration for the existing MyEngine R20/R21 registry."""
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from urllib.parse import parse_qsl, urlsplit

BASE = Path(__file__).resolve().parent
DEPENDENCY = 'psycopg[binary]>=3.2,<4'


def identifier(value, label, limit):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,' + str(limit) + '}', value):
        raise ValueError('Некорректное поле сертификата: ' + label)
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('В JSON повторяется поле: ' + key)
        result[key] = value
    return result


def read_certificate(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Сертификат слишком большой: максимум 64 КБ.')
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Некорректное число JSON')))
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Нужен JSON-сертификат в кодировке UTF-8.') from error
    if not isinstance(value, dict) or value.get('schema') != 'myengine-license/v1':
        raise ValueError('Выбран не сертификат MyEngine. Выбери файл deluxe-…json из игры.')
    if value.get('licenseStatus') != 'issued':
        raise ValueError('Этот сертификат не выдан или отозван.')
    if value.get('grantType') not in ('developer', 'purchase', 'manual'):
        raise ValueError('Неизвестный тип сертификата.')
    if value.get('signature') is not None:
        raise ValueError('Для подписанного сертификата нужен соответствующий проверяющий модуль.')
    payment = value.get('payment')
    if not isinstance(payment, dict) or not isinstance(payment.get('status'), str):
        raise ValueError('В сертификате отсутствует описание payment.')
    if value['grantType'] == 'developer' and payment['status'] != 'not_required':
        raise ValueError('У сертификата разработчика payment.status должен быть not_required.')
    def date(text):
        if not isinstance(text, str) or len(text) > 64:
            raise ValueError('Некорректная дата сертификата.')
        result = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('В дате сертификата отсутствует часовой пояс.')
        return result
    issued = date(value.get('issuedAt'))
    if value.get('expiresAt') is not None:
        expiry = date(value['expiresAt'])
        if expiry <= issued or expiry <= datetime.now(timezone.utc):
            raise ValueError('Срок действия сертификата истёк.')
    return {name: identifier(value.get(name), name, limit) for name, limit in
            [('playerId', 32), ('productId', 100), ('certificateId', 128)]}


def phone_number(value):
    value = value.strip()
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
        raise ValueError('Телефон: +кодстраныномер, без пробелов и скобок.')
    return value


def database_url(value):
    value = value.strip()
    try:
        parsed = urlsplit(value)
        parsed.port  # Validate the port without exposing the URL in errors.
    except ValueError as error:
        raise ValueError('Некорректный External Database URL.') from error
    if (len(value) > 4096 or any(c.isspace() for c in value) or
            parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname or
            not parsed.username or not parsed.password or parsed.path in ('', '/') or parsed.fragment):
        raise ValueError('Нужен External Database URL базы PostgreSQL из Render, начинающийся с postgres:// или postgresql://. HTTPS-адрес сайта не подходит.')
    # Keep connection options predictable; do not accept URL overrides of host,
    # password files, local services, or SSL settings. TLS is enforced by connect.
    if any(key != 'sslmode' or val not in ('require', 'verify-ca', 'verify-full')
           for key, val in parse_qsl(parsed.query, keep_blank_values=True)):
        raise ValueError('Скопируй обычный External Database URL из Render без дополнительных параметров.')
    return value


def register(connect, url, certificate, number):
    """One transaction, no schema creation, payment changes, or SMS sends."""
    url = database_url(url)
    number = phone_number(number)
    player = identifier(certificate.get('playerId'), 'playerId', 32)
    product = identifier(certificate.get('productId'), 'productId', 100)
    cert_id = identifier(certificate.get('certificateId'), 'certificateId', 128)
    ssl_mode = dict(parse_qsl(urlsplit(url).query)).get('sslmode', 'require')
    with connect(url, sslmode=ssl_mode, connect_timeout=10,
                 application_name='MyEngine private registration',
                 options='-c statement_timeout=15000 -c lock_timeout=5000') as connection:
        # Guard inside each UPSERT, including concurrent registrations. A
        # conflicting certificate rolls back the player write as well.
        row = connection.execute(
            'INSERT INTO players(id,phone,active) VALUES(%s,%s,1) '
            'ON CONFLICT(id) DO UPDATE SET active=1 WHERE players.phone=EXCLUDED.phone RETURNING id',
            (player, number)).fetchone()
        if row is None:
            raise ValueError('Этот playerId уже зарегистрирован с другим телефоном. Номер не изменён. Укажи прежний номер или используй отдельное восстановление аккаунта.')
        row = connection.execute(
            'INSERT INTO certificates(id,player,product,active) VALUES(%s,%s,%s,1) '
            'ON CONFLICT(id) DO UPDATE SET active=1 '
            'WHERE certificates.player=EXCLUDED.player AND certificates.product=EXCLUDED.product RETURNING id',
            (cert_id, player, product)).fetchone()
        if row is None:
            raise ValueError('Этот certificateId уже принадлежит другому игроку или товару. Регистрация отменена без изменений.')
    return {'playerId': player, 'productId': product, 'certificateId': cert_id}


def load_driver(progress):
    local = BASE / '.registration-deps'
    if local.is_dir():
        sys.path.insert(0, str(local))
    try:
        return importlib.import_module('psycopg')
    except ImportError:
        progress('Первый запуск: устанавливаем модуль подключения к базе. Нужен интернет…')
        local.mkdir(exist_ok=True)
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
             '--only-binary=:all:', '--upgrade', '--target', str(local), DEPENDENCY],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if str(local) not in sys.path:
            sys.path.insert(0, str(local))
        importlib.invalidate_caches()
        return importlib.import_module('psycopg')


def friendly_error(error):
    if isinstance(error, ValueError):
        return str(error)
    if isinstance(error, (subprocess.CalledProcessError, subprocess.TimeoutExpired, ImportError)):
        return 'Не удалось установить модуль подключения. Проверь интернет и наличие Python 3.11–3.14 с pip, затем повтори запуск.'
    state = getattr(error, 'sqlstate', None)
    if state == '42P01':
        return 'В этой базе нет таблиц MyEngine. Выбери базу, подключённую к твоему серверу проверки игроков.'
    if state in ('28P01', '28000', '3D000'):
        return 'База отклонила подключение. Заново скопируй External Database URL из базы Render, связанной с сервером игроков.'
    if state in ('57014', '55P03'):
        return 'База не успела завершить операцию. Подожди немного и повтори регистрацию с тем же сертификатом.'
    # Database exceptions may contain a connection string: never display them.
    return 'Регистрация не подтверждена. Проверь External Database URL, доступность базы Render и разрешение внешнего подключения с твоего IP. Повторная регистрация того же файла с тем же номером допустима.'


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    if sys.version_info < (3, 11):
        raise RuntimeError('Нужен Python 3.11 или новее.')
    root = tk.Tk()
    root.title('MyEngine — зарегистрировать сертификат')
    root.geometry('760x' + str(min(720, max(500, root.winfo_screenheight() - 120))))
    root.minsize(640, 480)
    container = ttk.Frame(root)
    container.pack(fill='both', expand=True)
    canvas = tk.Canvas(container, highlightthickness=0)
    scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    frame = ttk.Frame(canvas, padding=22)
    body = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    def resize(event):
        canvas.itemconfigure(body, width=event.width)
        for child in frame.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(wraplength=max(280, event.width - 44))
    canvas.bind('<Configure>', resize)
    def wheel(event):
        if frame.winfo_reqheight() > canvas.winfo_height():
            canvas.yview_scroll(-int(event.delta / 120), 'units')
    root.bind('<MouseWheel>', wheel)
    ttk.Label(frame, text='Добавить сертификат в базу игроков', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Для автора игры. После регистрации сервер сможет начать проверку телефона или пароля.',
              wraplength=700).pack(anchor='w', pady=(8, 18))
    selected = {'certificate': None}
    filename = tk.StringVar(value='Файл ещё не выбран')
    details = tk.StringVar(value='Выбери тот же JSON, который загружаешь через кнопку в игре.')
    status = tk.StringVar(value='Заполни три поля и нажми «Зарегистрировать».')
    url = tk.StringVar()
    number = tk.StringVar()
    controls = []
    events = queue.Queue()
    busy = [False]

    def choose():
        path = filedialog.askopenfilename(parent=root, title='Сертификат, который выбираешь в игре',
                                          filetypes=[('Сертификат MyEngine', '*.json')])
        if not path:
            return
        try:
            certificate = read_certificate(path)
        except (OSError, ValueError) as error:
            selected['certificate'] = None
            filename.set('Файл не принят')
            details.set('Выбери действительный JSON-сертификат.')
            messagebox.showerror('Сертификат', str(error), parent=root)
            return
        selected['certificate'] = certificate
        filename.set(Path(path).name)
        details.set('Игрок: ' + certificate['playerId'] + '    Товар: ' + certificate['productId'] +
                    '\nСертификат: ' + certificate['certificateId'])

    ttk.Label(frame, text='1. Сертификат из игры', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
    choose_button = ttk.Button(frame, text='Выбрать JSON…', command=choose)
    choose_button.pack(anchor='w', pady=5)
    controls.append(choose_button)
    ttk.Label(frame, textvariable=filename, wraplength=700).pack(anchor='w')
    ttk.Label(frame, textvariable=details, wraplength=700).pack(anchor='w', pady=(4, 14))
    ttk.Label(frame, text='2. External Database URL из Render', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
    database_entry = ttk.Entry(frame, textvariable=url, show='*')
    database_entry.pack(fill='x', pady=5)
    controls.append(database_entry)
    ttk.Label(frame, text='Render → база PostgreSQL твоего сервера → Connect → External Database URL.\n'
              'Вставь сюда целиком. Адрес хранится только в памяти до закрытия окна.', wraplength=700).pack(anchor='w', pady=(0, 14))
    ttk.Label(frame, text='3. Телефон игрока', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
    phone_entry = ttk.Entry(frame, textvariable=number)
    phone_entry.pack(fill='x', pady=5)
    controls.append(phone_entry)
    ttk.Label(frame, text='Формат: +кодстраныномер. Для своего входа укажи номер из OWNER_PHONE.\n'
              'ID игрока выше должен совпадать с OWNER_PLAYER_ID в Render.', wraplength=700).pack(anchor='w', pady=(0, 16))

    def start():
        try:
            if not selected['certificate']:
                raise ValueError('Сначала выбери JSON-сертификат.')
            target = database_url(url.get())
            phone = phone_number(number.get())
            cert = dict(selected['certificate'])
        except ValueError as error:
            messagebox.showerror('Проверь поля', str(error), parent=root)
            return
        busy[0] = True
        for control in controls:
            control.configure(state='disabled')
        status.set('Подключаемся к базе и регистрируем сертификат…')

        def worker():
            try:
                driver = load_driver(lambda message: events.put(('status', message)))
                events.put(('status', 'Регистрируем сертификат в базе Render…'))
                result = register(driver.connect, target, cert, phone)
                events.put(('ok', result))
            except Exception as error:
                events.put(('error', friendly_error(error)))
        threading.Thread(target=worker, name='register-certificate', daemon=True).start()

    button = ttk.Button(frame, text='Зарегистрировать', command=start)
    button.pack(fill='x', pady=5)
    controls.append(button)
    ttk.Label(frame, textvariable=status, wraplength=700, font=('Segoe UI', 10)).pack(anchor='w', pady=10)
    ttk.Label(frame, text='Регистрация выдаёт доступ к проверке входа. SMS не отправляется, оплата не подтверждается.',
              wraplength=700).pack(anchor='w')

    def poll():
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == 'status':
                    status.set(payload)
                    continue
                busy[0] = False
                for control in controls:
                    control.configure(state='normal')
                if kind == 'ok':
                    status.set('Зарегистрировано: ' + payload['playerId'] + ' / ' + payload['productId'] +
                               '. Вернись в игру и снова выбери этот же сертификат.')
                    messagebox.showinfo('Готово', 'Игрок и сертификат зарегистрированы.\n\n'
                                        'В игре снова нажми «Играть», выбери этот же JSON и подтверди вход.\n'
                                        'Для владельца сайт запросит свой номер и пароль.', parent=root)
                else:
                    status.set(payload)
                    messagebox.showerror('Регистрация не подтверждена', payload, parent=root)
        except queue.Empty:
            pass
        root.after(100, poll)

    def close():
        if busy[0]:
            messagebox.showinfo('Дождись результата', 'Операция ещё выполняется. Дождись сообщения о результате перед закрытием.', parent=root)
            return
        url.set('')
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, poll)
    root.mainloop()


if __name__ == '__main__':
    main()
