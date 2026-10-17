"""Editor dialogs for developer-owned controls and slide UI imports."""
from pathlib import Path
import queue,threading
import tkinter as tk
from tkinter import ttk,filedialog,simpledialog,messagebox
from engine_editor_tools import _commit

UI_PATCH_VERSION = 'UI TOOLS R6'

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
    w=tk.Toplevel(editor.window);w.title(UI_PATCH_VERSION+' — PowerPoint / 2D interface');w.geometry('680x570');w.minsize(620,550);w.transient(editor.window)
    p=ttk.Frame(w,padding=16);p.pack(fill='both',expand=True)
    ttk.Label(p,text=UI_PATCH_VERSION+' · Фон слайда выключен по умолчанию').pack(anchor='w',pady=(0,8))
    background=tk.BooleanVar(value=bool(editor.document.data.get('uiBackground',False)))
    def set_background():
        if editor.can_edit():_commit(editor,'uiBackground',background.get())
    ttk.Checkbutton(p,text='Показывать фон слайда / Show slide background',variable=background,command=set_background).pack(anchor='w',pady=5)
    from engine_ui_blueprint_ui import ui_blueprints_dialog
    ttk.Button(p,text='UI Blueprints — настроить нажатия кнопок',command=lambda:ui_blueprints_dialog(editor)).pack(fill='x',pady=4)
    ttk.Label(p,text='Off by default, including previously imported interfaces. No JSON edits needed.',wraplength=590).pack(anchor='w',pady=(0,6))
    status=tk.StringVar(value=editor.document.data.get('ui') or 'No UI attached');ttk.Label(p,textvariable=status,wraplength=590).pack(fill='x',pady=8)
    ttk.Label(p,text='Open your .pptx in desktop PowerPoint, then switch to this editor.\nThe currently active presentation is imported using a temporary copy.\nYour presentation stays open; unsaved edits are included.\nOnly individual elements are imported; the slide background is omitted.\nJSON: Alternative Text, or {"myengine":{...}} as the whole shape text.\nNo LibreOffice or additional Python packages are required.',wraplength=590).pack(anchor='w',pady=8)
    ttk.Label(p,text='Loaded from: '+str(Path(__file__).resolve()),wraplength=590).pack(side='bottom',anchor='w',pady=(8,0))
    messages=queue.Queue();busy=False
    def attach(path):
        if editor.can_edit():_commit(editor,'ui',Path(path).resolve().relative_to(editor.path_root).as_posix());editor.refresh_project();status.set(str(path))
    def select():
        path=filedialog.askopenfilename(parent=w,initialdir=editor.path_root,filetypes=[('UI document','*.ui.json')])
        if path:
            try:
                from engine_ui import load_document
                load_document(path);attach(path)
            except Exception as ex:editor.error(ex)
    def import_deck():
        nonlocal busy
        if busy:return
        name=simpledialog.askstring('UI asset name','New asset folder name (active PowerPoint presentation):',initialvalue='PowerPointUI',parent=w)
        if not name:return
        busy=True;status.set('Importing from open PowerPoint…');button.configure(state='disabled')
        def work():
            try:
                from engine_pptx_import import import_powerpoint
                result=import_powerpoint(None,editor.path_root,name);messages.put(('done',result))
            except Exception as ex:messages.put(('error',str(ex)))
        threading.Thread(target=work,name='pptx-import',daemon=False).start()
    def poll():
        nonlocal busy
        if not w.winfo_exists():return
        while not messages.empty():
            kind,value=messages.get();busy=False;button.configure(state='normal')
            if kind=='error':status.set(value);messagebox.showerror('Import failed',value,parent=w)
            else:
                path,warnings=value
                try:attach(path)
                except Exception as ex:editor.error(ex)
                for warning in warnings:editor.log(warning)
                if warnings:messagebox.showinfo('Imported with limitations','\n'.join(warnings[:20]),parent=w)
        w.after(100,poll)
    button=ttk.Button(p,text='Import from open PowerPoint…',command=import_deck);button.pack(fill='x',pady=3)
    ttk.Button(p,text='Attach existing .ui.json…',command=select).pack(fill='x',pady=3)
    ttk.Button(p,text='Remove interface',command=lambda:_commit(editor,'ui',None) if editor.can_edit() else None).pack(fill='x',pady=3)
    w.protocol('WM_DELETE_WINDOW',lambda:status.set('Wait for the import to finish.') if busy else w.destroy());w.after(100,poll)
