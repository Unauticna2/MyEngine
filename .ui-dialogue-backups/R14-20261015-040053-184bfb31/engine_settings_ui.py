"""Editor dialogs for developer-owned controls and slide UI imports."""
from pathlib import Path
import queue,threading
import tkinter as tk
from tkinter import ttk,filedialog,simpledialog,messagebox
from engine_editor_tools import _commit

UI_PATCH_VERSION = 'UI TOOLS R13'

def runtime_dialog(editor):
    if not editor.can_edit():return
    from engine_runtime_options import normalized
    w=tk.Toplevel(editor.window);w.title('Game controls / diagnostics');p=ttk.Frame(w,padding=16);p.pack(fill='both',expand=True)
    labels={'diagnosticTitle':'Show diagnostic window title','cameraReset':'R: reset camera','scriptReload':'F5: reload Python scripts','wKeys':'Q / E: change W layer','lightKeys':'F1–F7: built-in light controls','escapeQuits':'Escape: quit game','freeFly':'Built-in WASD / Space / Ctrl free flight','mouseLook':'Right mouse: built-in camera look'}
    values={}
    for key,value in normalized(editor.document.data.get('runtime')).items():
        values[key]=tk.BooleanVar(value=value);ttk.Checkbutton(p,text=labels[key],variable=values[key]).pack(anchor='w',pady=4)
    ttk.Label(p,text='These settings apply to Play and exported games.\nScripts can still read all keys. Editor navigation stays available.').pack(pady=10)
    def save():
        if editor.can_edit():_commit(editor,'runtime',{k:v.get() for k,v in values.items()});w.destroy()
    ttk.Button(p,text='Apply',command=save).pack(fill='x')

def ui_dialog(editor):
    if not editor.can_edit():return
    w=tk.Toplevel(editor.window);w.title(UI_PATCH_VERSION+' — PowerPoint / 2D interface');w.geometry('780x730');w.minsize(660,600);w.transient(editor.window)
    canvas=tk.Canvas(w,highlightthickness=0);scroll=ttk.Scrollbar(w,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
    p=ttk.Frame(canvas,padding=16);panel_id=canvas.create_window((0,0),window=p,anchor='nw')
    p.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda event:canvas.itemconfigure(panel_id,width=event.width))
    messages=queue.Queue();busy=False;controls=[];import_document=None;import_ui=None;import_root=None;pending_background=None
    ttk.Label(p,text=UI_PATCH_VERSION+' · Фон слайда выключен по умолчанию').pack(anchor='w',pady=(0,8))
    background=tk.BooleanVar(value=bool(editor.document.data.get('uiBackground',False)))
    def set_background():
        if busy or not editor.can_edit():
            background.set(bool(editor.document.data.get('uiBackground',False)));return
        try:
            ui=editor.document.data.get('ui')
            if background.get() and ui:
                from engine_pptx_import import has_backgrounds
                if not has_backgrounds(editor.path_root/ui):
                    refresh_deck(enable_background=True);return
            _commit(editor,'uiBackground',background.get())
            status.set('Фон включён.' if background.get() else 'Фон выключен.')
        except Exception as ex:
            background.set(bool(editor.document.data.get('uiBackground',False)));editor.error(ex)
    control=ttk.Checkbutton(p,text='Показывать фон слайда / Show slide background',variable=background,command=set_background)
    control.pack(anchor='w',pady=5);controls.append(control)
    from engine_ui_blueprint_ui import ui_blueprints_dialog
    ttk.Button(p,text='UI Blueprints — настроить нажатия кнопок',command=lambda:ui_blueprints_dialog(editor)).pack(fill='x',pady=4)
    from engine_ui_settings import ui_effects_dialog
    ttk.Button(p,text='Переходы и запуск анимаций…',command=lambda:ui_effects_dialog(editor)).pack(fill='x',pady=4)
    from engine_ui_content_editor import content_dialog,payments_dialog
    ttk.Button(p,text='Привязки элементов / новелла / видео…',command=lambda:content_dialog(editor)).pack(fill='x',pady=4)
    ttk.Button(p,text='Донаты / транзакции…',command=lambda:payments_dialog(editor)).pack(fill='x',pady=4)
    from engine_ui_scaling import ui_scale_dialog
    ttk.Button(p,text='Масштаб UI — ширина / высота / без полос…',command=lambda:ui_scale_dialog(editor)).pack(fill='x',pady=4)
    ttk.Label(p,text='Если фон ещё не импортирован, включение галочки загрузит его из открытого PowerPoint.\nПовторное переключение использует сохранённый фон. «Обновить» загружает изменения.',wraplength=620).pack(anchor='w',pady=(0,6))
    status=tk.StringVar(value=editor.document.data.get('ui') or 'No UI attached');ttk.Label(p,textvariable=status,wraplength=590).pack(fill='x',pady=8)
    ttk.Label(p,text='Открой .pptx в PowerPoint и вернись в редактор.\n«Импорт» создаёт UI, «Обновить» меняет уже подключённый.\nНесохранённые правки презентации тоже учитываются.\nJSON: Alt Text или {"myengine":{...}} в тексте фигуры; кавычки “ ” поддерживаются.',wraplength=620).pack(anchor='w',pady=8)
    def attach(path,show_background=None):
        if not editor.can_edit():return
        relative=Path(path).resolve().relative_to(editor.path_root).as_posix()
        if show_background is None:_commit(editor,'ui',relative)
        else:
            editor.document.checkpoint();editor.document.data.update(ui=relative,uiBackground=show_background)
            editor.changed();editor.reload()
        editor.refresh_project();status.set(str(path))
    def select():
        path=filedialog.askopenfilename(parent=w,initialdir=editor.path_root,filetypes=[('UI document','*.ui.json')])
        if path:
            try:
                from engine_ui import load_document
                load_document(path);attach(path)
            except Exception as ex:editor.error(ex)
    def import_deck():
        nonlocal busy,import_document,import_ui,import_root,pending_background
        if busy or not editor.can_edit():return
        name=simpledialog.askstring('UI asset name','New asset folder name (active PowerPoint presentation):',initialvalue='PowerPointUI',parent=w)
        if not name:return
        busy=True;import_document=editor.document;import_ui=import_document.data.get('ui');import_root=editor.path_root;pending_background=None
        include_background=background.get();status.set('Importing from open PowerPoint…')
        for control in controls:control.configure(state='disabled')
        def work():
            try:
                from engine_pptx_import import import_powerpoint
                result=import_powerpoint(None,import_root,name,include_background=include_background);messages.put(('done',result))
            except Exception as ex:messages.put(('error',str(ex)))
        threading.Thread(target=work,name='pptx-import',daemon=False).start()
    def refresh_deck(choose=False,*,enable_background=False):
        nonlocal busy,import_document,import_ui,import_root,pending_background
        if busy or not editor.can_edit():return
        ui=editor.document.data.get('ui')
        if not ui:editor.error('Сначала подключи импортированный интерфейс.');return
        source=None
        if choose:
            source=filedialog.askopenfilename(parent=w,title='Выбери .pptx, открытый в PowerPoint',filetypes=[('PowerPoint','*.pptx')])
            if not source:return
        import_document=editor.document;import_ui=ui;import_root=editor.path_root
        pending_background=True if enable_background else None
        include_background=bool(enable_background or background.get())
        required=[(r['slide'],r['element']) for r in import_document.data.get('uiBlueprints',{}).values() if r.get('ui')==ui]
        busy=True;status.set('Загружаю недостающий фон из PowerPoint…' if enable_background else 'Обновляю текущий UI из PowerPoint…')
        for control in controls:control.configure(state='disabled')
        def work():
            try:
                from engine_pptx_import import update_powerpoint
                result=update_powerpoint(ui,import_root,source,required=required,include_background=include_background);messages.put(('done',result))
            except Exception as ex:messages.put(('error',str(ex)))
        threading.Thread(target=work,name='pptx-import',daemon=False).start()
    def poll():
        nonlocal busy,pending_background
        if not w.winfo_exists():return
        while not messages.empty():
            kind,value=messages.get();busy=False
            for control in controls:control.configure(state='normal')
            if kind=='error':status.set(value);messagebox.showerror('Import failed',value,parent=w)
            else:
                path,warnings=value
                try:
                    if editor.document is import_document and editor.path_root==import_root and editor.document.data.get('ui')==import_ui and editor.can_edit():
                        attach(path,pending_background)
                        if pending_background:status.set('Фон загружен и включён.')
                    else:status.set('Импорт готов: '+str(path))
                except Exception as ex:editor.error(ex)
                for warning in warnings:editor.log(warning)
                if warnings:messagebox.showinfo('Imported with limitations','\n'.join(warnings[:20]),parent=w)
            pending_background=None;background.set(bool(editor.document.data.get('uiBackground',False)))
        w.after(100,poll)
    button=ttk.Button(p,text='Import from open PowerPoint…',command=import_deck);button.pack(fill='x',pady=3)
    controls.append(button)
    for title,command in [('Обновить текущий UI из PowerPoint',refresh_deck),('Обновить из другого открытого .pptx…',lambda:refresh_deck(True))]:
        control=ttk.Button(p,text=title,command=command);control.pack(fill='x',pady=3);controls.append(control)
    for title,command in [('Attach existing .ui.json…',select),('Remove interface',lambda:_commit(editor,'ui',None) if editor.can_edit() else None)]:
        control=ttk.Button(p,text=title,command=command);control.pack(fill='x',pady=3);controls.append(control)
    w.protocol('WM_DELETE_WINDOW',lambda:status.set('Wait for the import to finish.') if busy else w.destroy());w.after(100,poll)
