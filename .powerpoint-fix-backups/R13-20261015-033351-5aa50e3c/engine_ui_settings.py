"""UI animation/transition settings, kept across PowerPoint reimports."""
import tkinter as tk
from tkinter import ttk
from engine_ui import load_document,validate
from engine_scene import atomic_json
from engine_projects import inside
from engine_ui_effects import transition_settings


def ui_effects_dialog(editor):
    if not editor.can_edit():return
    try:
        name=editor.document.data.get('ui')
        if not name:raise ValueError('Сначала подключи UI из PowerPoint.')
        path=inside(editor.path_root,name);data=load_document(path)
    except Exception as ex:editor.error(ex);return
    document=editor.document
    w=tk.Toplevel(editor.window);w.title('UI — переходы и анимации');w.geometry('650x680')
    p=ttk.Frame(w,padding=16);p.pack(fill='both',expand=True)
    ttk.Label(p,text='Изменения сохраняются в UI и переживают обновление из PowerPoint.',wraplength=600).pack(anchor='w',pady=5)
    slides={str(s['id']):s for s in data['slides']}
    slide=tk.StringVar(value=next(iter(slides),''));element=tk.StringVar()
    ttk.Label(p,text='Слайд').pack(anchor='w')
    sb=ttk.Combobox(p,textvariable=slide,values=list(slides),state='readonly');sb.pack(fill='x')
    kinds={'Без перехода':'none','Плавное появление':'fade','Сдвиг':'push'}
    kind=tk.StringVar();duration=tk.StringVar();direction=tk.StringVar();after=tk.StringVar();automatic=tk.BooleanVar();pageclick=tk.BooleanVar()
    ttk.Label(p,text='Переход при входе на этот слайд').pack(anchor='w',pady=(10,0))
    ttk.Combobox(p,textvariable=kind,values=list(kinds),state='readonly').pack(fill='x')
    row=ttk.Frame(p);row.pack(fill='x',pady=5)
    ttk.Label(row,text='Длительность, секунд:').pack(side='left');ttk.Entry(row,textvariable=duration,width=8).pack(side='left',padx=6)
    ttk.Combobox(row,textvariable=direction,values=['left','right','up','down'],state='readonly',width=10).pack(side='left')
    row=ttk.Frame(p);row.pack(fill='x')
    ttk.Checkbutton(row,text='Следующий слайд через, секунд:',variable=automatic).pack(side='left');ttk.Entry(row,textvariable=after,width=8).pack(side='left')
    ttk.Checkbutton(p,text='Щелчок по пустому месту: следующая анимация / слайд',variable=pageclick).pack(anchor='w',pady=5)
    ttk.Separator(p).pack(fill='x',pady=12)
    ttk.Label(p,text='Элемент / кнопка').pack(anchor='w')
    eb=ttk.Combobox(p,textvariable=element,state='readonly');eb.pack(fill='x')
    modes={'Как в PowerPoint':'imported','Автоматически один раз':'auto','По нажатию на эту кнопку':'click','Автоматически по кругу':'loop','Только узлом UI play animation':'manual'}
    mode=tk.StringVar();ttk.Combobox(p,textvariable=mode,values=list(modes),state='readonly').pack(fill='x',pady=8)
    wait=tk.BooleanVar()
    ttk.Checkbutton(p,text='Выполнить действие кнопки после анимации',variable=wait).pack(anchor='w',pady=4)
    details=tk.StringVar();ttk.Label(p,textvariable=details,wraplength=600).pack(fill='x')
    ttk.Label(p,text='Анимация задаётся в PowerPoint. Здесь выбирается её запуск.\nРежим «По нажатию» перезапускает эффект при каждом щелчке.\nДля выхода: UI Click → Quit game. В редакторе это Stop Play.',wraplength=600).pack(anchor='w',pady=10)
    def load_element(event=None):
        s=slides.get(slide.get());e=next((e for e in s['elements'] if str(e['id'])==element.get()),None) if s else None
        if not e:mode.set(next(iter(modes)));details.set('Нет элементов.');return
        mode.set(next(k for k,v in modes.items() if v==e.get('animationMode','imported')));wait.set(e.get('waitForAnimation',False))
        count=len(e.get('animations',[]))+sum(str(a['element'])==str(e['id']) for a in s.get('animations',[]))
        details.set(f"{e.get('name',e['id'])} · эффектов: {count} · кадров: {len(e.get('frames',[]))}")
    def load_slide(event=None):
        s=slides.get(slide.get())
        if not s:return
        t=transition_settings(s.get('transition'));kind.set(next(k for k,v in kinds.items() if v==t['kind']));duration.set(str(t['duration']));direction.set(t['direction'])
        automatic.set('advanceAfter' in s);after.set(str(s.get('advanceAfter',3)));pageclick.set(s.get('advanceOnClick',False))
        ids=[str(e['id']) for e in s['elements']];eb.configure(values=ids);element.set(ids[0] if ids else '');load_element()
    def save():
        try:
            if not editor.can_edit() or editor.document is not document:raise ValueError('Открой настройки заново для текущей сцены.')
            # Merge only the fields on screen into the latest asset; do not erase a reimport.
            latest=load_document(path);s=next(s for s in latest['slides'] if str(s['id'])==slide.get())
            t=transition_settings({'kind':kinds[kind.get()],'duration':float(duration.get()),'direction':direction.get()})
            original=slides[slide.get()];overrides=s.setdefault('_editor',{})
            if t!=transition_settings(original.get('transition')):overrides['transition']=t
            if pageclick.get()!=original.get('advanceOnClick',False):overrides['advanceOnClick']=pageclick.get()
            new_after=float(after.get()) if automatic.get() else None
            if new_after!=original.get('advanceAfter'):overrides['advanceAfter']=new_after
            s.update(overrides)
            if s.get('advanceAfter') is None:s.pop('advanceAfter',None)
            if element.get():
                e=next(e for e in s['elements'] if str(e['id'])==element.get());e['animationMode']=modes[mode.get()];e.setdefault('_editor',{})['animationMode']=e['animationMode'];e['waitForAnimation']=wait.get();e['_editor']['waitForAnimation']=wait.get()
            validate(latest);atomic_json(path,latest);editor.reload();editor.refresh_project();editor.log('UI effects saved: '+name);w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(p,text='Сохранить настройки выбранного слайда / элемента',command=save).pack(fill='x',pady=10)
    sb.bind('<<ComboboxSelected>>',load_slide);eb.bind('<<ComboboxSelected>>',load_element);load_slide()
