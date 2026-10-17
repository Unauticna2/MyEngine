"""Tk editor for the built-in payment website generator."""
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from engine_scene import atomic_json
import engine_commerce as commerce
from engine_transactions import load_settings, settings


def commerce_dialog(editor):
    if not editor.can_edit(): return
    root = Path(editor.path_root).resolve()
    try: current = commerce.load(root); payment = load_settings(root)
    except Exception as ex: editor.error(ex); return
    window = tk.Toplevel(editor.window); window.title('MyEngine R17 — коммерция / генератор сайта')
    window.geometry('800x740'); window.minsize(660,560); window.transient(editor.window)
    outer = ttk.Frame(window, padding=12); outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='Добавь товары → экспортируй ZIP → опубликуй на Render → подключи адрес.', wraplength=740).pack(anchor='w', pady=(0,10))
    book = ttk.Notebook(outer); book.pack(fill='both', expand=True)
    tabs = []
    for title in ('Товары', 'Контакты', 'Сайт и кнопки', 'Разработчик'):
        tab = ttk.Frame(book); book.add(tab,text=title)
        canvas = tk.Canvas(tab, highlightthickness=0); scrollbar = ttk.Scrollbar(tab,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set); scrollbar.pack(side='right',fill='y'); canvas.pack(side='left',fill='both',expand=True)
        panel = ttk.Frame(canvas,padding=14); item = canvas.create_window((0,0),window=panel,anchor='nw')
        panel.bind('<Configure>',lambda e,c=canvas:c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',lambda e,c=canvas,i=item:c.itemconfigure(i,width=e.width))
        tabs.append(panel)
    product, contacts, host, developer = tabs
    values = {}
    def entry(parent,key,label,width=None):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(5,0))
        var = tk.StringVar(value=current.get(key,'')); values[key] = var
        box = ttk.Entry(parent,textvariable=var); box.pack(fill='x',pady=(2,4)); return box
    draft = commerce.CatalogDraft(current['products'])
    active_index = 0
    catalog_box = ttk.Frame(product); catalog_box.pack(fill='x')
    tree = ttk.Treeview(catalog_box,columns=('id','title','price'),show='headings',height=5,selectmode='browse')
    for key,label,width in [('id','ID товара',150),('title','Название',330),('price','Цена, ₽',100)]:
        tree.heading(key,text=label); tree.column(key,width=width,minwidth=70)
    scroll=ttk.Scrollbar(catalog_box,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');tree.pack(side='left',fill='x',expand=True)
    catalog_buttons=ttk.Frame(product);catalog_buttons.pack(fill='x',pady=6)
    for key,label in [('productTitle','Название товара / дополнения'),('productId','ID для Blueprint (у каждого товара свой)'),
                      ('description','Описание товара'),('amount','Цена, ₽')]: entry(product,key,label)
    ttk.Label(product,text='Порядок активации этого товара').pack(anchor='w',pady=(5,2))
    activation = tk.Text(product,height=3,wrap='word',undo=True); activation.pack(fill='x')
    ttk.Label(product,text='Изменения товара сохраняются при выборе другого товара и при экспорте. На сайте первый товар выбран по умолчанию; каждая игровая кнопка может открыть свой ID.',wraplength=670).pack(anchor='w',pady=8)
    def refresh_catalog():
        tree.delete(*tree.get_children())
        for i,item in enumerate(draft.products):tree.insert('','end',iid=str(i),values=(item['productId'],item['productTitle'],item['amount']))
        tree.selection_set(str(active_index));tree.see(str(active_index))
    def show_product(index):
        nonlocal active_index
        active_index=index;item=draft.products[index]
        for key in ('productTitle','productId','description','amount'):values[key].set(item[key])
        activation.delete('1.0','end');activation.insert('1.0',item['activationText'])
    def commit_product():
        item={key:values[key].get() for key in ('productTitle','productId','description','amount')}
        item['activationText']=activation.get('1.0','end-1c')
        draft.update(active_index,item)
        item=draft.products[active_index]
        tree.item(str(active_index),values=(item['productId'],item['productTitle'],item['amount']))
    def select_product(event=None):
        selected=tree.selection()
        if not selected or int(selected[0])==active_index:return
        try:commit_product();show_product(int(selected[0]))
        except Exception as ex:tree.selection_set(str(active_index));editor.error(ex)
    def add_product(copy=False):
        try:
            commit_product();index=draft.add(active_index if copy else None);show_product(index);refresh_catalog()
        except Exception as ex:editor.error(ex)
    def remove_product():
        try:
            index=draft.remove(active_index);show_product(index);refresh_catalog()
        except Exception as ex:editor.error(ex)
    ttk.Button(catalog_buttons,text='+ Добавить товар',command=add_product).pack(side='left',padx=3)
    ttk.Button(catalog_buttons,text='Дублировать',command=lambda:add_product(True)).pack(side='left',padx=3)
    ttk.Button(catalog_buttons,text='Удалить товар',command=remove_product).pack(side='left',padx=3)
    show_product(0);refresh_catalog();tree.bind('<<TreeviewSelect>>',select_product)
    for key,label in [('gameName','Название игры / проекта'),('receiver','Общий кошелёк ЮMoney'),
                      ('sellerName','Имя / название разработчика'),('supportUrl','Общая поддержка: mailto:email или https://ссылка')]:entry(contacts,key,label)
    enabled = tk.BooleanVar(value=current['paymentsEnabled'])
    ttk.Checkbutton(contacts,text='Приём платежей включён для каталога',variable=enabled).pack(anchor='w',pady=8)
    ttk.Label(contacts,text='Один сайт, один кошелёк и один контакт поддержки для всех товаров. У каждого товара свои цена, описание и порядок активации.',wraplength=670).pack(anchor='w',pady=8)

    entry(host,'siteUrl','Опубликованный адрес сайта (https://…onrender.com)')
    ttk.Label(host,text='Архив содержит сайт, сборку и render.yaml. Один сайт — весь каталог. На Render выбери Static Site; Build Command: node scripts/build-static.mjs; Publish Directory: dist.',wraplength=670).pack(anchor='w',pady=10)
    ttk.Label(host,text='Кнопка «Создать транзакцию» / Transaction start открывает сайт с ID товара и меткой запроса. Без сервера статус manual: оплата проверяется вручную. Transaction paid once сработает только в серверном режиме после подтверждения.',wraplength=670).pack(anchor='w',pady=8)
    donate = tk.BooleanVar(value=True)
    ttk.Checkbutton(host,text='Также использовать сайт для «Открыть донат»',variable=donate).pack(anchor='w',pady=5)
    ttk.Separator(host).pack(fill='x',pady=12)
    ttk.Label(host,text='Существующие подключения проекта').pack(anchor='w')
    api = tk.StringVar(value=payment['checkoutApi']); donation = tk.StringVar(value=payment['donationUrl'])
    for label,var in [('Отдельная ссылка «Открыть донат»',donation),('Checkout API — сервер автоматической проверки (не адрес сайта)',api)]:
        ttk.Label(host,text=label).pack(anchor='w',pady=(8,2)); ttk.Entry(host,textvariable=var).pack(fill='x')
    mode_labels = {'Сайт — ручная проверка':'site','Сервер — автоматическая проверка':'api'}
    mode = tk.StringVar(value=next(k for k,v in mode_labels.items() if v==payment['checkoutMode']))
    ttk.Label(host,text='Режим Transaction start').pack(anchor='w',pady=(8,2))
    ttk.Combobox(host,textvariable=mode,values=list(mode_labels),state='readonly').pack(fill='x')
    def identity_settings():
        from engine_identity_ui import identity_dialog
        identity_dialog(editor)
    ttk.Button(host,text='Проверка игрока / SMS…',command=identity_settings).pack(fill='x',pady=12)

    dev_settings = dict(current['developerAccess'])
    dev_enabled = tk.BooleanVar(value=dev_settings.get('enabled',False))
    dev_status = tk.StringVar()
    ttk.Checkbutton(developer,text='Включить бесплатный сертификат разработчика',variable=dev_enabled).pack(anchor='w',pady=8)
    ttk.Label(developer,text='Сертификат JSON помечается «оплата не требуется». Проверка локальная, без банка и SMS; файл не является подтверждением перевода. В игру он автоматически не импортируется.',wraplength=670).pack(anchor='w',pady=8)
    ttk.Label(developer,textvariable=dev_status,wraplength=670).pack(anchor='w',pady=8)
    credentials = {}
    for key,label,masked in [('id','ID разработчика',False),('last4','Последние 4 цифры карты',True),('phone','Телефон с кодом страны',True)]:
        ttk.Label(developer,text=label).pack(anchor='w',pady=(8,2)); var=tk.StringVar(); credentials[key]=var
        ttk.Entry(developer,textvariable=var,show='•' if masked else '').pack(fill='x')
    def developer_summary():
        dev_status.set('Сохранён ID: '+dev_settings['playerId'] if dev_settings.get('enabled') else 'Локальная проверка ещё не настроена.')
    def clear_credentials():
        for var in credentials.values(): var.set('')
    def apply_developer():
        try:
            updated = commerce.create_developer(credentials['id'].get(),credentials['last4'].get(),credentials['phone'].get())
            dev_settings.clear(); dev_settings.update(updated); dev_enabled.set(True); clear_credentials(); developer_summary()
            status.set('Проверка подготовлена. Сохрани настройки или экспортируй сайт.')
        except Exception as ex: editor.error(ex)
    ttk.Button(developer,text='Настроить проверку по введённым данным',command=apply_developer).pack(fill='x',pady=12)
    ttk.Label(developer,text='Телефон и цифры карты не записываются в настройки — сохраняется только отпечаток. Чтобы сохранить прежнюю проверку из архива, импортируй его через кнопку внизу.',wraplength=670).pack(anchor='w',pady=6)
    developer_summary()

    status = tk.StringVar()
    ttk.Label(outer,textvariable=status,wraplength=740).pack(anchor='w',pady=8)
    def connection_status():
        active=load_settings(root)
        if active['checkoutMode']=='site' and active['checkoutSite']:
            return 'Подключён сайт: '+active['checkoutSite']+' · товаров: '+str(len(active['siteProducts']))
        if active['checkoutMode']=='api' and active['checkoutApi']:
            return 'Подключён сервер: '+active['checkoutApi']
        return 'Покупка ещё не подключена. Экспортируй и опубликуй сайт, затем вставь его адрес на вкладке «Сайт и кнопки».'
    status.set(connection_status())
    def check_project():
        if not editor.can_edit() or Path(editor.path_root).resolve()!=root: raise ValueError('Проект изменился или запущен Play. Открой окно заново.')
    def collect():
        check_project()
        if any(v.get() for v in credentials.values()): raise ValueError('Нажми «Настроить проверку» или очисти поля разработчика перед сохранением.')
        if dev_enabled.get() and not dev_settings.get('enabled'): raise ValueError('Сначала настрой проверку разработчика')
        commit_product()
        return commerce.normalize({**{k:v.get() for k,v in values.items()},'products':draft.products,
            'paymentsEnabled':enabled.get(),'developerAccess':dev_settings if dev_enabled.get() else {'enabled':False}})
    def fill(data):
        for key,var in values.items(): var.set(data[key])
        draft.products=commerce.CatalogDraft(data['products']).products;show_product(0);refresh_catalog();enabled.set(data['paymentsEnabled'])
        dev_settings.clear(); dev_settings.update(data['developerAccess']); dev_enabled.set(dev_settings.get('enabled',False)); clear_credentials(); developer_summary()
    def save_settings():
        try:
            data=collect()
            # Saving a site address also connects it, unless the author chose a configured API.
            if data['siteUrl'] and (mode_labels[mode.get()]=='site' or not api.get().strip()):
                connect();return
            commerce.save(root,data); editor.refresh_project(); status.set('Настройки сохранены. '+connection_status())
        except Exception as ex: editor.error(ex)
    def import_file(preset=False):
        try:
            check_project()
            path = commerce.TEMPLATE/'myengine-preset.json' if preset else filedialog.askopenfilename(parent=window,title='Импорт настроек сайта',filetypes=[('Сайт / настройки','*.zip *.js *.json')])
            if not path:return
            fill(commerce.import_settings(path)); status.set('Настройки загружены в форму. Сохрани их или экспортируй сайт.')
        except Exception as ex: editor.error(ex)
    def export():
        try:
            data=collect(); commerce.normalize(data,publish=True)
            target=filedialog.asksaveasfilename(parent=window,title='Экспорт платёжного сайта',defaultextension='.zip',initialfile='payment-catalog.zip',filetypes=[('ZIP','*.zip')])
            if not target:return
            check_project(); commerce.export_zip(data,target); commerce.save(root,data)
            status.set('ZIP готов: '+str(target)+'. Теперь опубликуй его на Render и подключи адрес во вкладке «Сайт и кнопки».'); editor.log('Payment website exported: '+str(target))
        except Exception as ex: editor.error(ex)
    def connect():
        try:
            data=collect(); updated=commerce.connect(root,data,connect_donation=donate.get()); commerce.save(root,data)
            payment.clear(); payment.update(updated); api.set(payment['checkoutApi']); donation.set(payment['donationUrl']); mode.set('Сайт — ручная проверка')
            editor.refresh_project(); status.set('Каталог подключён: '+str(len(data['products']))+' товаров. В каждом Transaction start укажи нужный product и отдельный key. Перезапусти Play.')
        except Exception as ex: editor.error(ex)
    def save_connections():
        try:
            check_project(); old=load_settings(root)
            updated=settings({**old,'donationUrl':donation.get(),'checkoutApi':api.get(),'checkoutMode':mode_labels[mode.get()]})
            if updated['checkoutMode']=='site' and not updated['checkoutSite']: raise ValueError('Сначала подключи опубликованный сайт кнопкой ниже')
            atomic_json(root/'payments.json',updated); payment.clear();payment.update(updated); editor.refresh_project(); status.set('Подключения сохранены. Перезапусти Play.')
        except Exception as ex: editor.error(ex)
    ttk.Button(host,text='Сохранить подключения / выбранный режим',command=save_connections).pack(fill='x',pady=12)
    ttk.Button(host,text='Сохранить и подключить сайт к кнопкам',command=connect).pack(fill='x',pady=6)
    row=ttk.Frame(outer); row.pack(fill='x')
    ttk.Button(row,text='Импорт ZIP / config.js…',command=import_file).pack(side='left',padx=3)
    ttk.Button(row,text='Мой MyEngine Deluxe · 10 ₽',command=lambda:import_file(True)).pack(side='left',padx=3)
    row=ttk.Frame(outer); row.pack(fill='x',pady=(8,0))
    ttk.Button(row,text='Сохранить настройки',command=save_settings).pack(side='left',fill='x',expand=True,padx=3)
    ttk.Button(row,text='Экспорт сайта для Render…',command=export).pack(side='left',fill='x',expand=True,padx=3)
    def close(): clear_credentials(); window.destroy()
    window.protocol('WM_DELETE_WINDOW',close)
    return window
