"""Pick an imported UI element and edit its click Blueprint."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from engine_projects import inside, project_scenes
from engine_ui import load_document
from engine_ui_blueprints import binding_key, binding_record, click_graph, apply_binding


def ui_blueprints_dialog(editor):
    if not editor.can_edit():return
    document=editor.document;ui=document.data.get('ui')
    try:
        if not ui:raise ValueError('First attach your interface: Assets / extensions → PowerPoint / 2D interface.')
        catalog=load_document(inside(editor.path_root,ui))
    except Exception as error:editor.error(error);return
    window=tk.Toplevel(editor.window);window.title('UI Blueprints — imported PowerPoint buttons')
    window.geometry('820x560');window.minsize(680,480);window.transient(editor.window)
    panel=ttk.Frame(window,padding=14);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='Выбери фигуру → Create / edit Blueprint → Apply to UI → Ctrl+S → Play.',wraplength=760).pack(anchor='w',pady=(0,8))
    ttk.Label(panel,text=ui,wraplength=760).pack(anchor='w')
    labels=[str(s['id'])+' — '+str(s.get('name','Slide')) for s in catalog['slides']]
    slide=tk.StringVar(value=labels[0] if labels else '')
    picker=ttk.Combobox(panel,textvariable=slide,values=labels,state='readonly');picker.pack(fill='x',pady=8)
    list_frame=ttk.Frame(panel);list_frame.pack(fill='both',expand=True)
    tree=ttk.Treeview(list_frame,columns=('id','name','binding'),show='headings',selectmode='browse',height=10)
    for key,label,width in [('id','Element ID',160),('name','PowerPoint shape',230),('binding','Blueprint',300)]:
        tree.heading(key,text=label);tree.column(key,width=width)
    scroll=ttk.Scrollbar(list_frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
    tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    templates={'Скрыть интерфейс':'UIVisible','Следующий слайд':'UINextSlide',
               'Открыть слайд':'UIShowSlide','Предыдущий слайд':'UIPreviousSlide','Проиграть анимацию':'UIPlayAnimation','Выйти из игры':'QuitGame','Загрузить сцену':'LoadScene','Сообщение в Console':'Print'}
    ttk.Label(panel,text='Первое действие для нового графа (дальше можно соединять любые узлы):').pack(anchor='w',pady=(8,2))
    template=tk.StringVar(value=next(iter(templates)))
    ttk.Combobox(panel,textvariable=template,values=list(templates),state='readonly').pack(fill='x')
    status=tk.StringVar(value='Обработчики работают в Play. Активный Blueprint заменяет прежний onClick этой кнопки.')
    ttk.Label(panel,textvariable=status,wraplength=760).pack(fill='x',pady=8)
    def current_slide():
        index=picker.current()
        return catalog['slides'][index] if 0<=index<len(catalog['slides']) else None
    def refresh(event=None):
        selected=tree.selection();tree.delete(*tree.get_children());s=current_slide()
        if s is None:return
        records=document.data.get('uiBlueprints',{})
        for i,element in enumerate(s['elements']):
            record=records.get(binding_key(ui,s['id'],element['id']),{})
            tree.insert('','end',iid=str(i),values=(element['id'],element.get('name',element['id']),record.get('graph','—')))
        items=tree.get_children()
        if items:tree.selection_set(selected[0] if selected and selected[0] in items else items[0])
    def open_graph(event=None):
        try:
            if not editor.can_edit():return
            if editor.document is not document or document.data.get('ui')!=ui:
                raise ValueError('The current scene/interface changed. Reopen UI Blueprints.')
            selection=tree.selection();s=current_slide()
            if not selection or s is None:raise ValueError('Select a UI element first.')
            element=s['elements'][int(selection[0])]
            record=binding_record(document,editor.path_root,ui,s['id'],element['id'])
            path=inside(editor.path_root,record['graph'])
            if path.exists():data=json.loads(path.read_text(encoding='utf-8-sig'))
            else:
                data=click_graph(s['id'],element['id'],templates[template.get()])
                action=data['nodes'][1]
                if action['type'] in ('UIShowSlide','UIPlayAnimation'):action['params']['slide']=str(s['id'])
                if action['type']=='UIPlayAnimation':action['params']['element']=str(element['id'])
                if action['type']=='LoadScene':
                    scenes=project_scenes(editor.path_root)
                    current=editor.path.resolve().relative_to(editor.path_root).as_posix()
                    choices=sorted(scenes,key=lambda name:(name==current,not name.startswith('scenes/'),name))
                    if choices:action['params']['path']=choices[0]
            def apply(data):
                if not editor.can_edit():raise ValueError('Stop Play and finish any object edit first.')
                if editor.document is not document:raise ValueError('The scene changed. Reopen UI Blueprints.')
                saved,unused=apply_binding(document,editor.path_root,record,data)
                editor.populate_hierarchy();editor.show_inspector();editor.refresh_project();editor.reload()
                editor.log('UI Blueprint applied: '+str(element['id'])+' → '+saved['script']+'; Ctrl+S to save scene, then Play.')
                if window.winfo_exists():refresh();status.set('Применено. Сохрани сцену Ctrl+S и нажми Play.')
                return inside(editor.path_root,saved['graph']),f'Applied to UI · {len(unused)} unused nodes · save scene with Ctrl+S, then Play'
            from engine_blueprint_ui import BlueprintEditor
            graph=BlueprintEditor(window,editor.path_root,path,data=data,on_apply=apply,ui_data=catalog)
            graph.w.title('UI Blueprint — '+str(element.get('name',element['id'])))
        except Exception as error:messagebox.showerror('UI Blueprints',str(error),parent=window)
    from engine_ui_settings import ui_effects_dialog
    ttk.Button(panel,text='Переходы / анимации UI…',command=lambda:ui_effects_dialog(editor)).pack(fill='x',pady=4)
    ttk.Button(panel,text='Create / edit Blueprint',command=open_graph).pack(fill='x',pady=4)
    picker.bind('<<ComboboxSelected>>',refresh);tree.bind('<Double-1>',open_graph);refresh()
