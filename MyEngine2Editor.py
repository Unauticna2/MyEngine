"""MyEngine 2 desktop editor. Tk UI and native viewport live in separate processes."""
from __future__ import annotations
import copy
import ctypes as C
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from engine_scene import SceneDocument, atomic_json
from engine_editor_link import Channel

ENGINE_ROOT=Path(__file__).resolve().parent
ROOT=ENGINE_ROOT


class Editor:
    def __init__(self,window,scene=None,launch=True):
        self.window=window;self.path_root=ROOT.resolve();self.path=Path(scene or ROOT/'map-vox.json').resolve()
        self.document=SceneDocument.load(self.path)
        self.saved=copy.deepcopy(self.document.data);self.selected=None;self.playing=False
        self.process=None;self.channel=None;self.authenticated=False;self.native_hwnd=0;self.pending=[]
        self.closing=False;self.ready=False;self.inspector_vars={};self.edit_transaction=None;self.log_offset=0;self.log_timer=0;self.gizmo_active=False
        self.token=secrets.token_hex(32)
        self.temp=Path(tempfile.mkdtemp(prefix='session-',dir=self.session_directory()))
        self.preview=self.temp/'preview.json';self.write_preview()
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen(2);self.listener.setblocking(False)
        self.port=self.listener.getsockname()[1]
        self.status=tk.StringVar(value='Edit mode — right mouse: look, WASD: move, Space/Ctrl: up/down')
        self.build_ui();self.populate_hierarchy();self.refresh_project()
        from engine_editor_input import EditorTextFocus
        self.text_input = EditorTextFocus(self.window, self.log)
        from engine_window_menu import attach_tk
        self.title_menu=attach_tk(self.window,ENGINE_ROOT,self.path_root)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.after(20,self.poll)
        if launch:self.window.after(120,self.launch)
        if len(self.document.data['model']):self.select(0)

    @staticmethod
    def session_directory():
        p=ROOT/'.myengine';p.mkdir(exist_ok=True);return p

    def build_ui(self):
        w=self.window;w.title('MyEngine 2');w.geometry('1400x900');w.minsize(1000,660)
        try:w.iconbitmap(str(ENGINE_ROOT/'MyEngineN2.ico'))
        except tk.TclError:pass
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',background='#25282e',foreground='#e0e5ee',fieldbackground='#191c21',font=('Segoe UI',10))
        style.configure('Treeview',background='#1d2026',fieldbackground='#1d2026',foreground='#dbe2ee',rowheight=25)
        style.map('Treeview',background=[('selected','#385575')],foreground=[('selected','#ffffff')])
        style.configure('TButton',padding=(10,5));style.configure('TLabelframe.Label',foreground='#8bc8ee')
        style.map('TButton',background=[('active','#3b4654')])
        w.configure(bg='#25282e')
        toolbar=ttk.Frame(w,padding=6);toolbar.pack(fill='x')
        ttk.Label(toolbar,text='MYENGINE 2',font=('Segoe UI',13,'bold')).pack(side='left',padx=(6,20))
        for name,fn in [('New scene',self.new_scene),('Open',self.open_scene),('Save',self.save),('Save As',self.save_as),('Undo',self.undo),('Redo',self.redo)]:
            ttk.Button(toolbar,text=name,command=fn).pack(side='left',padx=2)
        self.play_button=ttk.Button(toolbar,text='▶ Play',command=self.play);self.play_button.pack(side='left',padx=(20,2))
        ttk.Button(toolbar,text='■ Stop',command=self.stop).pack(side='left',padx=2)
        ttk.Button(toolbar,text='Restart viewport',command=self.restart).pack(side='right',padx=4)
        ttk.Button(toolbar,text='Build game',command=self.build_game).pack(side='right',padx=3)
        extra=ttk.Frame(w,padding=(6,0));extra.pack(fill='x')
        from engine_editor_tools import skybox_dialog,character_dialog,blueprint_dialog
        from engine_ui_blueprint_ui import ui_blueprints_dialog
        for label,fn in [('Skybox',lambda:skybox_dialog(self)),('Player physics',lambda:character_dialog(self)),('Blueprints',lambda:blueprint_dialog(self)),('UI Blueprints',lambda:ui_blueprints_dialog(self)),('GitHub packages',self.packages),('Publish project',self.publish)]:
            ttk.Button(extra,text=label,command=fn).pack(side='left',padx=3,pady=3)
        from engine_editor_tools import data_asset_dialog,save_prefab_dialog,add_prefab_dialog,project_trust_dialog,lighting_dialog
        assets_button=ttk.Menubutton(extra,text='Assets / extensions');assets_button.pack(side='left',padx=3)
        assets_menu=tk.Menu(assets_button,tearoff=False);assets_button.configure(menu=assets_menu)
        for label,fn in [('New Scriptable Object',lambda:data_asset_dialog(self)),('Save selected as prefab',lambda:save_prefab_dialog(self)),('Instantiate prefab',lambda:add_prefab_dialog(self)),('Project script permission',lambda:project_trust_dialog(self)),('Shadows / sun texture',lambda:lighting_dialog(self))]:assets_menu.add_command(label=label,command=fn)
        from engine_settings_ui import runtime_dialog,ui_dialog
        assets_menu.add_command(label='Game controls / diagnostics',command=lambda:runtime_dialog(self))
        assets_menu.add_command(label='PowerPoint / 2D interface',command=lambda:ui_dialog(self))
        from engine_commerce_ui import commerce_dialog
        assets_menu.add_command(label='Коммерция / генератор сайта',command=lambda:commerce_dialog(self))
        vertical=ttk.Panedwindow(w,orient='vertical');vertical.pack(fill='both',expand=True,padx=6)
        top=ttk.Panedwindow(vertical,orient='horizontal');vertical.add(top,weight=4)
        left=ttk.Labelframe(top,text='Hierarchy',padding=5,width=240);top.add(left,weight=0)
        self.hierarchy=ttk.Treeview(left,show='tree',selectmode='extended',height=15);self.hierarchy.pack(fill='both',expand=True)
        self.hierarchy.bind('<<TreeviewSelect>>',self.on_selection)
        self.hierarchy.bind('<Button-3>',self.hierarchy_context_menu)
        left.bind('<Button-3>',self.hierarchy_context_menu)
        hint=ttk.Label(left,text='Right-click: Create / Add component',padding=(0,5))
        hint.pack(fill='x');hint.bind('<Button-3>',self.hierarchy_context_menu)
        center=ttk.Frame(top);top.add(center,weight=1)
        bar=ttk.Frame(center);bar.pack(fill='x')
        self.tool=tk.StringVar(value='move')
        for label,mode in [('Move','move'),('Rotate','rotate'),('Scale','scale'),('4D rotate','rotate4')]:
            ttk.Radiobutton(bar,text=label,variable=self.tool,value=mode,
                            command=lambda:self.send(op='tool',mode=self.tool.get())).pack(side='left',padx=3)
        ttk.Label(center,text='X red  ·  Y green  ·  Z blue  ·  W magenta  |  Ctrl: snap',padding=4).pack(fill='x')
        ttk.Button(bar,text='Focus selected',command=self.focus).pack(side='right')
        self.viewport=tk.Frame(center,bg='#0b0d10',width=660,height=440);self.viewport.pack(fill='both',expand=True)
        self.viewport.bind('<Configure>',lambda e:self.resize_viewport())
        self.placeholder=tk.Label(self.viewport,text='MyEngine 2\n\nLoading native viewport…',fg='#8895a8',bg='#0b0d10',font=('Segoe UI',14))
        self.placeholder.place(relx=.5,rely=.5,anchor='center')
        right=ttk.Labelframe(top,text='Inspector',padding=5,width=335);top.add(right,weight=0)
        canvas=tk.Canvas(right,width=320,bg='#25282e',highlightthickness=0);self.inspector_canvas=canvas
        right.bind('<Button-3>',self.inspector_context_menu);canvas.bind('<Button-3>',self.inspector_context_menu)
        scroll=ttk.Scrollbar(right,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        self.inspector=ttk.Frame(canvas);item=canvas.create_window((0,0),window=self.inspector,anchor='nw')
        self.inspector.bind('<Button-3>',self.inspector_context_menu)
        self.inspector.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.bottom=ttk.Notebook(vertical);vertical.add(self.bottom,weight=1)
        project=ttk.Frame(self.bottom,padding=4);self.bottom.add(project,text='Project')
        pbar=ttk.Frame(project);pbar.pack(fill='x')
        ttk.Button(pbar,text='Refresh',command=self.refresh_project).pack(side='left')
        ttk.Button(pbar,text='New scene',command=self.new_scene).pack(side='left',padx=3)
        ttk.Button(pbar,text='Import file',command=self.import_file).pack(side='left',padx=3)
        ttk.Label(pbar,text='Double-click: open scene / add model or voxel / attach script or texture').pack(side='left',padx=10)
        self.project=ttk.Treeview(project,columns=('kind',),show='tree headings',height=6)
        self.project.heading('#0',text='Assets');self.project.heading('kind',text='Type');self.project.column('kind',width=120)
        self.project.pack(fill='both',expand=True);self.project.bind('<Double-1>',self.project_open)
        logs=ttk.Frame(self.bottom);self.bottom.add(logs,text='Console')
        self.console=tk.Text(logs,height=6,bg='#15181d',fg='#bccadd',wrap='word',state='disabled')
        self.console.pack(fill='both',expand=True)
        ttk.Label(w,textvariable=self.status,padding=5).pack(fill='x')
        from engine_theme import attach
        self.theme=attach(w,lambda mode:self.send(op='appearance',outlines=mode=='Sunlight'));self.theme.selector(extra)
        for key,fn in [('<Control-n>',self.new_scene),('<Control-s>',self.save),('<Control-z>',self.undo),('<Control-y>',self.redo)]:
            w.bind(key,lambda e,f=fn:f())

    def log(self,text):
        self.console.configure(state='normal');self.console.insert('end',str(text)+'\n');self.console.see('end');self.console.configure(state='disabled')
        self.status.set(str(text))
    def error(self,error):self.log('ERROR: '+str(error));messagebox.showerror('MyEngine 2',str(error),parent=self.window)
    def changed(self):
        dirty=self.document.data!=self.saved
        self.window.title(f'MyEngine 2 — {self.path.name}'+(' *' if dirty else '')+(' [Play]' if self.playing else ''))
    def can_edit(self):
        if self.playing:self.log('Stop Play before editing. Play changes are not saved.');return False
        if self.gizmo_active:self.log('Finish dragging the gizmo first.');return False
        if self.edit_transaction:self.log('Waiting for the previous change…');return False
        return True
    def write_preview(self):atomic_json(self.preview,self.document.data)
    def send(self,**command):
        if self.channel and self.authenticated:self.channel.send(command)
        else:self.pending.append(command)
    def reload(self):self.write_preview();self.send(op='reload',path=str(self.preview),play=self.playing,scene_identity=str(self.path))

    def launch(self):
        exe=ENGINE_ROOT/'MyEngine2.exe'
        if not exe.is_file():
            self.placeholder.configure(text='Run build.cmd first, then Restart viewport.');self.log('MyEngine2.exe missing. Run build.cmd.');return
        if sys.platform!='win32':self.log('Native viewport requires Windows x64.');return
        try:
            env=os.environ.copy();env['MYENGINE_LOG_DIR']=str(ROOT/'.myengine')
            self.process=subprocess.Popen([str(exe),str(self.preview),'--project',str(ROOT),'--editor',str(self.port),self.token],cwd=ROOT,env=env)
            self.log('Starting native viewport…')
        except Exception as ex:self.error(ex)

    def stop_process(self):
        if self.channel:self.channel.close();self.channel=None
        self.authenticated=False;self.native_hwnd=0
        if self.process and self.process.poll() is None:
            # Only the exact child process started by this editor is controlled.
            if sys.platform=='win32' and getattr(self,'user32',None) and getattr(self,'last_hwnd',0):
                pid=C.c_uint32();self.user32.GetWindowThreadProcessId(self.last_hwnd,C.byref(pid))
                if pid.value==self.process.pid:self.user32.PostMessageW(self.last_hwnd,0x10,0,0)
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
        self.process=None;self.last_hwnd=0
    def restart(self):
        self.stop_process();self.playing=False;self.edit_transaction=None;self.pending.clear();self.log_offset=0;self.write_preview();self.launch()
        self.send(op='appearance',outlines=self.theme.current=='Sunlight')

    def embed(self,hwnd):
        if sys.platform!='win32':return
        u=C.WinDLL('user32',use_last_error=True);self.user32=u
        for name,args,result in [
            ('SetParent',[C.c_void_p,C.c_void_p],C.c_void_p),
            ('GetWindowLongPtrW',[C.c_void_p,C.c_int],C.c_ssize_t),
            ('SetWindowLongPtrW',[C.c_void_p,C.c_int,C.c_ssize_t],C.c_ssize_t),
            ('SetWindowPos',[C.c_void_p,C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_int,C.c_uint],C.c_int),
            ('SetFocus',[C.c_void_p],C.c_void_p),
            ('GetWindowThreadProcessId',[C.c_void_p,C.POINTER(C.c_uint32)],C.c_uint32),
            ('PostMessageW',[C.c_void_p,C.c_uint,C.c_size_t,C.c_ssize_t],C.c_int)]:
            f=getattr(u,name);f.argtypes=args;f.restype=result
        pid=C.c_uint32();u.GetWindowThreadProcessId(hwnd,C.byref(pid))
        if not self.process or pid.value!=self.process.pid:raise ValueError('Unexpected viewport process')
        style=u.GetWindowLongPtrW(hwnd,-16)
        u.SetWindowLongPtrW(hwnd,-16,(style & ~0x80CF0000)|0x46000000)
        C.set_last_error(0);old=u.SetParent(hwnd,self.viewport.winfo_id())
        if not old and C.get_last_error():raise C.WinError(C.get_last_error())
        self.native_hwnd=hwnd;self.last_hwnd=hwnd;self.placeholder.place_forget();self.resize_viewport()
    def resize_viewport(self):
        if self.native_hwnd:self.user32.SetWindowPos(self.native_hwnd,None,0,0,max(1,self.viewport.winfo_width()),max(1,self.viewport.winfo_height()),0x64)

    def rollback_pending(self):
        self.gizmo_active=False
        if self.edit_transaction:
            self.document.data=self.edit_transaction;self.edit_transaction=None
            if self.document.undo_stack:self.document.undo_stack.pop()
            self.populate_hierarchy();self.show_inspector();self.changed()

    def poll(self):
        if self.closing:return
        try:
            if self.channel is None:
                try:conn,_=self.listener.accept();self.channel=Channel(conn);self.authenticated=False;self.hello_time=time.monotonic()
                except BlockingIOError:pass
            if self.channel:
                for m in self.channel.poll():
                    if not self.authenticated:
                        if m.get('type')!='hello' or not secrets.compare_digest(str(m.get('token','')),self.token):
                            self.channel.close();break
                        self.embed(int(m['hwnd']));self.authenticated=True;self.log('Viewport connected. Edit mode.')
                        for command in self.pending:self.channel.send(command)
                        self.pending.clear()
                        self.channel.send({'op':'tool','mode':self.tool.get()})
                    elif m.get('type')=='fullscreen':
                        if self.title_menu:self.title_menu.toggle_fullscreen()
                    elif m.get('type')=='gizmo_begin':self.gizmo_active=True
                    elif m.get('type')=='gizmo_cancel':self.gizmo_active=False;self.show_inspector()
                    elif m.get('type')=='gizmo_commit':
                        self.gizmo_active=False
                        names=self.document.data['names']
                        if m.get('changed') and m['name'] in names:
                            index=names.index(m['name']);obj=self.document.object(index);obj.update(m['transform'])
                            self.document.set_object(index,obj);self.selected=index;self.changed();self.show_inspector()
                    elif m.get('type')=='error':
                        self.log('ENGINE ERROR: '+m['message']);self.bottom.select(1)
                        if self.edit_transaction and m.get('op')=='object':
                            self.rollback_pending()
                    elif m.get('type')=='ok':
                        if m.get('op')=='object':self.edit_transaction=None
                        if m.get('mode'):self.playing=m['mode']=='Play';self.play_button.configure(text='▶ Playing' if self.playing else '▶ Play');self.changed()
                if self.channel.closed or not self.authenticated and time.monotonic()-self.hello_time>5:
                    self.channel.close();self.channel=None;self.authenticated=False;self.rollback_pending()
            if self.process and self.process.poll() is not None:
                self.log(f'Viewport exited ({self.process.returncode}). See engine.log.');self.process=None;self.native_hwnd=0;self.rollback_pending()
                self.placeholder.configure(text='Viewport closed. Click Restart viewport.');self.placeholder.place(relx=.5,rely=.5,anchor='center')
        except Exception as ex:
            self.log('Viewport link: '+str(ex))
            if self.channel:self.channel.close();self.channel=None
            self.authenticated=False;self.rollback_pending()
        if time.monotonic()>self.log_timer:
            self.log_timer=time.monotonic()+.5
            try:
                path=ROOT/'.myengine/engine.log'
                if path.exists():
                    if path.stat().st_size<self.log_offset:self.log_offset=0
                    with path.open('rb') as log:
                        log.seek(self.log_offset);chunk=log.read(8192);self.log_offset=log.tell()
                    if chunk:
                        self.console.configure(state='normal');self.console.insert('end',chunk.decode('utf-8',errors='replace'))
                        self.console.see('end');self.console.configure(state='disabled')
            except OSError:pass
        self.window.after(20,self.poll)

    def populate_hierarchy(self):
        self.hierarchy.delete(*self.hierarchy.get_children())
        for i,name in enumerate(self.document.data['names']):
            kind='◆ ' if self.document.data['voxels'][i] else '◇ '
            self.hierarchy.insert('', 'end',iid=str(i),text=kind+name)
        if self.selected is not None and self.selected<len(self.document.data['model']):self.hierarchy.selection_set(str(self.selected))
        else:self.selected=None
        self.changed()
    def select(self,i):self.selected=i;self.hierarchy.selection_set(str(i));self.show_inspector()
    def on_selection(self,event=None):
        selected=self.hierarchy.selection()
        if selected:
            index=int(selected[0]);changed=index!=self.selected
            self.selected=index
            if changed or not self.inspector_vars:self.show_inspector()
            self.send(op='select',name=self.document.data['names'][self.selected])
    def hierarchy_context_menu(self,event):
        row=self.hierarchy.identify_row(event.y) if event.widget is self.hierarchy else ''
        if row:
            index=int(row)
            if index!=self.selected:self.select(index)
            self.hierarchy.focus(row)
            self.send(op='select',name=self.document.data['names'][index])
        else:
            selected=self.hierarchy.selection()
            if selected:self.hierarchy.selection_remove(*selected)
            self.selected=None
            self.show_inspector();self.send(op='select',name=None)
        self.popup_object_menu(event);return 'break'

    def inspector_context_menu(self,event):
        self.popup_object_menu(event);return 'break'

    def object_context_menu(self):
        """Build commands at opening time, so their target/availability is current."""
        menu=tk.Menu(self.window,tearoff=False)
        editable=not (self.playing or self.gizmo_active or self.edit_transaction)
        selected=self.selected is not None and self.selected<len(self.document.data['model'])
        state='normal' if editable else 'disabled'
        create=tk.Menu(menu,tearoff=False)
        for label,kind in [('Cube','cube'),('Voxel','voxel'),('Empty','empty'),('Liquid','liquid')]:
            create.add_command(label=label,command=lambda k=kind:self.add(k),state=state)
        lights=tk.Menu(create,tearoff=False)
        for kind in ('directional','point','spot'):
            lights.add_command(label=kind.title()+' Light',command=lambda k=kind:self.add(k),state=state)
        create.add_cascade(label='Light',menu=lights,state=state)
        menu.add_cascade(label='Create',menu=create,state=state)
        components=tk.Menu(menu,tearoff=False)
        for label,kind in [('Box Collider','box'),('Mesh Collider','mesh'),('Voxel Collider','voxel'),('Rigidbody','rigidbody'),('Liquid','liquid')]:
            components.add_command(label=label,command=lambda k=kind:self.add_component(k),state='normal' if editable and selected else 'disabled')
        menu.add_cascade(label='Add component',menu=components,state='normal' if editable and selected else 'disabled')
        menu.add_separator()
        for label,fn in [('Duplicate',self.duplicate),('Delete',self.delete)]:
            menu.add_command(label=label,command=fn,state='normal' if editable and selected else 'disabled')
        return menu

    def popup_object_menu(self,event):
        previous=getattr(self,'_object_popup',None)
        if previous is not None:previous.destroy()
        menu=self._object_popup=self.object_context_menu()
        if getattr(self,'theme',None):self.theme.restyle(menu)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def bind_inspector_context(self,widget):
        widget.bind('<Button-3>',self.inspector_context_menu)
        for child in widget.winfo_children():self.bind_inspector_context(child)

    def field(self,parent,label,value):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(6,1))
        var=tk.StringVar(value=value);entry=ttk.Entry(parent,textvariable=var);entry.pack(fill='x');return var
    def show_inspector(self):
        for w in self.inspector.winfo_children():w.destroy()
        self.inspector_vars={}
        if self.selected is None:return
        obj=self.document.object(self.selected);f=self.inspector;v=self.inspector_vars
        v['names']=self.field(f,'Name',obj['names'])
        checks=ttk.Frame(f);checks.pack(fill='x',pady=5)
        for k in ('active','visible'):
            v[k]=tk.BooleanVar(value=obj[k]);ttk.Checkbutton(checks,text=k.title(),variable=v[k]).pack(side='left',padx=4)
        from engine_collider_editor import ColliderInspector
        v['colliders']=ColliderInspector(self,f,obj.get('colliders'))
        for key,label in [('omitModelInBuild','Omit model in build (keep behaviour / physics)'),('editorOnly','Editor only (exclude whole object)'),('scriptTrusted','Allow scripts on this object'),('castShadows','Cast shadows'),('receiveShadows','Receive shadows')]:
            v[key]=tk.BooleanVar(value=obj[key]);ttk.Checkbutton(f,text=label,variable=v[key]).pack(anchor='w')
        transform=ttk.Labelframe(f,text='Transform',padding=5);transform.pack(fill='x',pady=5)
        for key,label,axes,default in [('positions','Position','xyz',0),('rotations','Rotation °','xyz',0),('scales','Scale','xyz',1),('colors','Color','rgb',1),('rotations4D','4D planes °',('xw','yw','zw'),0)]:
            ttk.Label(transform,text=label).pack(anchor='w')
            row=ttk.Frame(transform);row.pack(fill='x',pady=(1,5));v[key]={}
            raw=obj[key] or {}
            for j,axis in enumerate(axes):
                value=raw.get(axis,default) if isinstance(raw,dict) else raw[j]
                ttk.Label(row,text=axis.upper()).pack(side='left')
                var=tk.StringVar(value=f'{value:g}');v[key][axis]=var
                ttk.Entry(row,textvariable=var,width=6).pack(side='left',expand=True,fill='x',padx=(2,5))
        pos=obj['positions'];v['w']=self.field(transform,'W (fourth dimension)',pos.get('w',0) if isinstance(pos,dict) else 0)
        scale=obj['scales'];v['scale_w']=self.field(transform,'Scale W (.4d)',scale.get('w',1) if isinstance(scale,dict) else 1)
        v['layerSpacings']=self.field(transform,'Layer spacing',obj['layerSpacings'] or .1)
        v['model']=self.field(f,'Model (.obj / .4d / .vox), empty = none',obj['model'] or '')
        v['textures']=self.field(f,'Texture (.png / .bmp)',obj['textures'] or '')
        v['voxels']=self.field(f,'Voxel file (.vox / .vxl.json)',obj['voxels'] if isinstance(obj['voxels'],str) else (obj['voxels'] or {}).get('path',''))
        from engine_materials import material_settings
        material=ttk.Labelframe(f,text='Material / transparency',padding=5);material.pack(fill='x',pady=5)
        current=material_settings(obj.get('materials'));v['materials']={}
        for key,label in [('metallic','Metallic 0..1'),('roughness','Roughness 0..1'),('reflectionStrength','Reflection strength 0..1'),('opacity','Opacity 0..1'),('alphaCutoff','Cutout threshold 0..1'),('voxelDensity','Voxel volume density 0..100')]:
            v['materials'][key]=self.field(material,label,current[key])
        v['materialMode']=tk.StringVar(value=current['mode'])
        ttk.Label(material,text='Render mode').pack(anchor='w')
        ttk.Combobox(material,textvariable=v['materialMode'],values=('opaque','cutout','transparent'),state='readonly').pack(fill='x')
        v['twoSided']=tk.BooleanVar(value=current['twoSided'])
        ttk.Checkbutton(material,text='Two sided',variable=v['twoSided']).pack(anchor='w')
        from engine_light_editor import LightInspector
        v['lights']=LightInspector(self,f,obj.get('lights'))
        ttk.Label(material,text='Reflects real models, textures and scene sky.\nOne shared local probe; quality is in Shadows / sun texture.',wraplength=260).pack(anchor='w',pady=4)
        ttk.Label(f,text='Scripts — one project path per line').pack(anchor='w',pady=(8,2))
        scripts=tk.Text(f,height=3,bg='#191c21',fg='#dbe2ee',insertbackground='white',wrap='none')
        raw=obj['scripts'] or [];scripts.insert('1.0',raw if isinstance(raw,str) else '\n'.join(raw));scripts.pack(fill='x');v['scripts']=scripts
        for key,label in [('rigidbodies','Rigidbody JSON (null = static)'),('liquids','Liquid JSON (null = disabled)')]:
            ttk.Label(f,text=label).pack(anchor='w',pady=(8,2))
            text=tk.Text(f,height=4,bg='#191c21',fg='#dbe2ee',insertbackground='white',wrap='word')
            text.insert('1.0',json.dumps(obj[key],ensure_ascii=False));text.pack(fill='x');v[key]=text
        ttk.Label(f,text='Right-click: Add component',padding=(0,5)).pack(anchor='w')
        ttk.Label(f,text='Voxel: static surface with holes.\nFalling object: Box + Rigidbody.').pack(anchor='w',pady=4)
        ttk.Button(f,text='Apply changes',command=self.apply).pack(fill='x',pady=10)
        ttk.Label(f,text='Collider switches apply immediately.\nOther fields: Apply changes.\nCtrl+S saves the scene file.').pack(anchor='w')
        self.bind_inspector_context(f)
        self.inspector_canvas.yview_moveto(0)
    def preset(self,key,data):
        if not self.can_edit():return
        if key=='colliders':self.inspector_vars[key].set_value(data);return
        text=self.inspector_vars[key];text.delete('1.0','end');text.insert('1.0',json.dumps(data))
    @staticmethod
    def validate_collider(obj):
        from engine_collider_editor import collider_data
        data=collider_data(obj.get('colliders'))
        if data is None:return
        if obj.get('liquids') is not None:raise ValueError('Liquid must be a separate object without a Collider')
        if data['type']=='voxel' and not (obj.get('voxels') or str(obj.get('model','')).lower().endswith('.vox')):
            raise ValueError('Voxel Collider needs a voxel model; choose Box Collider for a cube')
        if data['type']=='mesh' and (not obj.get('model') or str(obj['model']).lower().endswith('.vox')):
            raise ValueError('Mesh Collider needs a polygon model')
        rb=obj.get('rigidbodies')
        if data['type'] in ('mesh','voxel') and rb is not None and rb is not False:
            if not isinstance(rb,dict) or not rb.get('isKinematic',rb.get('is_kinematic',rb.get('kinematic',False))):
                raise ValueError('Dynamic bodies need Box Collider; Mesh/Voxel Collider is static or kinematic')

    def commit_collider(self,data):
        if self.selected is None or not self.can_edit():return False
        i=self.selected;obj=self.document.object(i);obj['colliders']=data
        self.validate_collider(obj)
        before=copy.deepcopy(self.document.data);self.document.set_object(i,obj)
        if self.channel and self.authenticated:
            self.edit_transaction=before;self.send(op='object',old_name=obj['names'],object=obj)
        self.changed();self.log('Collider updated: '+obj['names']+' — Ctrl+S to save')
        return True

    def add_component(self,kind):
        if self.selected is None or not self.can_edit():return
        obj=self.document.object(self.selected)
        try:
            if kind in ('box','mesh','voxel'):
                from engine_collider_editor import collider_data
                data=collider_data(obj['colliders']) or {}
                data['type']=kind;key='colliders'
            elif kind=='rigidbody':
                if obj['rigidbodies'] is not None:self.log('Object already has a Rigidbody');return
                key='rigidbodies';data={'mass':1,'useGravity':True}
            elif kind=='liquid':
                if obj['liquids'] is not None:self.log('Object already has Liquid');return
                key='liquids';data={'nx':32,'nz':32,'cellSize':.25,'depth':.6}
            else:raise ValueError('Unknown component: '+kind)
            changes={key:data}
            if kind=='rigidbody' and (obj['colliders'] is None or obj['colliders'] is False):
                changes['colliders']={'type':'box'}
            candidate=copy.deepcopy(obj);candidate.update(changes)
            self.validate_collider(candidate)
            # Validate before changing Inspector fields, including incompatible liquids.
            from engine_scene import DEFAULTS
            SceneDocument({k:[candidate[k]] for k in DEFAULTS})
            for key,data in changes.items():self.preset(key,data)
            if self.apply():
                self.show_inspector()
            else:
                for key in changes:self.preset(key,obj[key])
        except Exception as ex:self.error(ex)

    def apply(self):
        if self.selected is None or not self.can_edit():return False
        try:
            i=self.selected;obj=self.document.object(i);old_name=obj['names'];v=self.inspector_vars
            for k in ('names','model','textures'):obj[k]=v[k].get().strip() or None
            if not obj['names']:raise ValueError('Name cannot be empty')
            for k in ('positions','rotations','scales','colors','rotations4D'):
                obj[k]={a:float(var.get()) for a,var in v[k].items()}
                if not all(math.isfinite(x) for x in obj[k].values()):raise ValueError('Numbers must be finite')
            if any(abs(x)<1e-5 for x in obj['scales'].values()):raise ValueError('Scale cannot be zero')
            obj['scales']['w']=float(v['scale_w'].get())
            if abs(obj['scales']['w'])<1e-5:raise ValueError('W scale cannot be zero')
            obj['positions']['w']=float(v['w'].get());obj['layerSpacings']=float(v['layerSpacings'].get())
            if obj['layerSpacings']<=0:raise ValueError('Layer spacing must be positive')
            for k in ('active','visible','omitModelInBuild','editorOnly','scriptTrusted','castShadows','receiveShadows'):obj[k]=v[k].get()
            from engine_materials import material_settings
            obj['materials']=material_settings({**{key:float(var.get()) for key,var in v['materials'].items()},'mode':v['materialMode'].get(),'twoSided':v['twoSided'].get()})
            obj['lights']=v['lights'].value()
            voxel=v['voxels'].get().strip()
            if isinstance(obj['voxels'],dict) and voxel:obj['voxels']['path']=voxel
            else:obj['voxels']=voxel or None
            obj['scripts']=[s.strip() for s in v['scripts'].get('1.0','end').splitlines() if s.strip()]
            obj['colliders']=v['colliders'].value()
            for k in ('rigidbodies','liquids'):obj[k]=json.loads(v[k].get('1.0','end'))
            self.validate_collider(obj)
            before=copy.deepcopy(self.document.data);self.document.set_object(i,obj)
            if self.channel and self.authenticated:self.edit_transaction=before;self.send(op='object',old_name=old_name,object=obj)
            self.populate_hierarchy();self.log('Applied: '+obj['names'])
            v['colliders'].current=copy.deepcopy(obj['colliders'])
            return True
        except Exception as ex:self.error(ex);return False

    def add(self,kind):
        if not self.can_edit():return
        try:
            # Empty/Basic projects do not necessarily include both primitives.
            asset={'cube':'Cube.obj','voxel':'VoxelSphere.vxl.json'}.get(kind)
            if asset:
                target=self.path_root/'assets'/asset
                if not target.exists():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with (ENGINE_ROOT/'assets'/asset).open('rb') as source:
                        try:destination=target.open('xb')
                        except FileExistsError:pass
                        else:
                            try:
                                with destination:shutil.copyfileobj(source,destination)
                            except BaseException:target.unlink(missing_ok=True);raise
                    self.refresh_project()
            i=self.document.add('assets/Cube.obj' if kind=='cube' else None,'assets/VoxelSphere.vxl.json' if kind=='voxel' else None)
            if kind=='liquid':
                self.document.data['names'][i]=self.document.unique_name('Liquid')
                self.document.data['liquids'][i]={'nx':32,'nz':32,'cellSize':.25,'depth':.6}
                self.document.data['colors'][i]={'r':.06,'g':.35,'b':.8}
                self.document.data['materials'][i]={'metallic':0,'roughness':.16,'reflectionStrength':.65,'mode':'transparent','opacity':.55}
            if kind in ('directional','point','spot'):
                from engine_lighting import light_settings
                self.document.data['names'][i]=self.document.unique_name(kind.title()+' Light')
                self.document.data['lights'][i]=light_settings({'type':kind})
                self.document.data['positions'][i]={'x':0,'y':3,'z':0}
                self.document.data['rotations'][i]={'x':60 if kind=='directional' else 90,'y':0,'z':0}
            self.populate_hierarchy();self.select(i);self.reload()
        except Exception as ex:self.error(ex)
    def duplicate(self):
        if self.selected is None or not self.can_edit():return
        self.selected=self.document.duplicate(self.selected);self.populate_hierarchy();self.show_inspector();self.reload()
    def delete(self):
        if self.selected is None or not self.can_edit():return
        self.document.remove(self.selected);self.selected=None;self.populate_hierarchy();self.show_inspector();self.reload()
    def focus(self):
        if self.selected is not None:self.send(op='focus',name=self.document.data['names'][self.selected])
    def undo(self):
        if self.can_edit() and self.document.undo():self.populate_hierarchy();self.show_inspector();self.reload()
    def redo(self):
        if self.can_edit() and self.document.redo():self.populate_hierarchy();self.show_inspector();self.reload()
    def play(self):
        if self.playing or not self.can_edit():return
        if not self.authenticated:self.log('Start the viewport before Play.');return
        self.playing=True;self.reload();self.changed()
    def stop(self):
        if not self.playing:return
        self.playing=False;self.reload();self.play_button.configure(text='▶ Play');self.changed()
    def save(self):
        if not self.can_edit():return False
        try:self.document.save(self.path);self.saved=copy.deepcopy(self.document.data);self.changed();self.refresh_project();self.log('Saved: '+self.path.name);return True
        except Exception as ex:self.error(ex);return False
    def save_as(self):
        if not self.can_edit():return False
        path=filedialog.asksaveasfilename(parent=self.window,initialdir=ROOT,defaultextension='.json',filetypes=[('Scene','*.json')])
        if not path:return False
        old=self.path;self.path=Path(path)
        if not self.save():self.path=old;return False
        return True
    def confirm_unsaved(self):
        if self.document.data==self.saved:return True
        answer=messagebox.askyesnocancel('MyEngine 2','Save changes to this scene?',parent=self.window)
        if answer is None:return False
        return self.save() if answer else True

    def activate_scene(self,path,document):
        # Prepare the viewport file before changing the current edit document.
        atomic_json(self.preview,document.data)
        self.path=Path(path).resolve();self.document=document;self.saved=copy.deepcopy(document.data);self.selected=None
        self.populate_hierarchy();self.show_inspector();self.refresh_project()
        self.send(op='reload',path=str(self.preview),play=False,scene_identity=str(self.path))
        self.send(op='select',name=None)

    def new_scene(self,path=None):
        if not self.can_edit() or not self.confirm_unsaved():return False
        try:
            if path is None:
                folder=self.path_root/'scenes';folder.mkdir(parents=True,exist_ok=True)
                name='NewScene.json';number=2
                while (folder/name).exists():name=f'NewScene{number}.json';number+=1
                path=filedialog.asksaveasfilename(parent=self.window,title='New scene — choose a new filename',
                    initialdir=folder,initialfile=name,defaultextension='.json',filetypes=[('Scene','*.json')])
            if not path:return False
            from engine_projects import create_scene
            target,document=create_scene(self.path_root,path)
            self.activate_scene(target,document)
            self.log('Created scene: '+target.relative_to(self.path_root).as_posix())
            return True
        except Exception as ex:self.error(ex);return False

    def open_scene(self,path=None):
        if not self.can_edit() or not self.confirm_unsaved():return
        path=path or filedialog.askopenfilename(parent=self.window,initialdir=ROOT,filetypes=[('Scene','*.json')])
        if not path:return
        try:
            document=SceneDocument.load(path)
            self.activate_scene(path,document)
        except Exception as ex:self.error(ex)

    def refresh_project(self):
        if not hasattr(self,'project'):return
        self.project.delete(*self.project.get_children())
        allowed={'.obj','.4d','.vox','.png','.bmp','.json','.py','.ico'}
        def visit(path,parent='',depth=0):
            if depth>6:return
            for p in sorted(path.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower())):
                if p.name.startswith('.') or p.name.lower() in ('__pycache__','build','builds','legacy') or p.is_symlink():continue
                key=str(p.relative_to(ROOT))
                if p.is_dir():
                    self.project.insert(parent,'end',iid=key,text=p.name,values=('Folder',),open=depth==0);visit(p,key,depth+1)
                elif p.suffix.lower() in allowed:self.project.insert(parent,'end',iid=key,text=p.name,values=(p.suffix,))
        visit(ROOT)
    def project_open(self,event=None):
        selection=self.project.selection()
        if not selection:return
        path=ROOT/selection[0];rel=path.relative_to(ROOT).as_posix()
        if path.is_dir():return
        try:
            if path.name=='project.myengine.json':return
            if path.name.endswith('.prefab.json'):
                from engine_editor_tools import add_prefab_dialog
                add_prefab_dialog(self,path);return
            if path.name.endswith('.scriptable.json'):
                from engine_editor_tools import data_asset_dialog
                data_asset_dialog(self,path);return
            if path.name.endswith('.blueprint.json'):
                from engine_editor_tools import blueprint_dialog
                blueprint_dialog(self,path);return
            if path.name.endswith('.sky.json'):return
            if path.suffix=='.json' and not path.name.endswith('.vxl.json'):self.open_scene(path);return
            if not self.can_edit():return
            if path.suffix.lower() in ('.obj','.4d','.vox') or path.name.endswith('.vxl.json'):
                voxel=path.suffix.lower()=='.vox' or path.name.endswith('.vxl.json')
                i=self.document.add(None if voxel else rel,rel if voxel else None)
                if path.suffix.lower()=='.4d':
                    from engine_assets import four_d_spacing
                    self.document.data['layerSpacings'][i]=four_d_spacing(path)
                self.populate_hierarchy();self.select(i);self.reload()
            elif self.selected is not None and path.suffix.lower() in ('.png','.bmp'):
                self.inspector_vars['textures'].set(rel);self.apply()
            elif self.selected is not None and path.suffix=='.py':
                self.inspector_vars['scripts'].insert('end','\n'+rel);self.apply()
        except Exception as ex:self.error(ex)
    def import_file(self):
        source=filedialog.askopenfilename(parent=self.window)
        if not source:return
        source=Path(source);target=ROOT/('scripts' if source.suffix=='.py' else 'assets')/source.name
        try:
            if source.resolve()==target.resolve():return
            if target.exists() and not messagebox.askyesno('Replace asset?',str(target),parent=self.window):return
            target.parent.mkdir(exist_ok=True);shutil.copy2(source,target);self.refresh_project()
        except Exception as ex:self.error(ex)
    def packages(self):
        from engine_package_ui import PackageBrowser
        PackageBrowser(self.window,ENGINE_ROOT,ROOT)
    def publish(self):
        if not self.can_edit() or not self.save():return
        from engine_package_ui import PublishDialog
        PublishDialog(self.window,ENGINE_ROOT,ROOT,self.path.relative_to(ROOT).as_posix())
    def build_game(self):
        if not self.can_edit():return
        if not self.save():return
        from engine_build_ui import show_build
        try:show_build(self.window,ENGINE_ROOT,ROOT,self.path.resolve().relative_to(ROOT).as_posix())
        except Exception as ex:self.error(ex)
    def close(self):
        import threading
        if any(t.name in ('player-build','package-work') and t.is_alive() for t in threading.enumerate()):self.log('Wait for the current build to finish.');return
        if self.gizmo_active:self.log('Release the gizmo before closing.');return
        if self.edit_transaction:self.log('Wait for the Inspector change to finish.');return
        # Saved edit document is independent of runtime simulation state.
        was_playing=self.playing;self.playing=False
        if not self.confirm_unsaved():self.playing=was_playing;return
        self.closing=True;self.stop_process();self.listener.close();shutil.rmtree(self.temp,ignore_errors=True);self.window.destroy()


def main():
    global ROOT
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('scene',nargs='?');parser.add_argument('--project')
    args=parser.parse_args()
    if args.project:ROOT=Path(args.project).resolve()
    if sys.platform=='win32':
        # Match the engine's default DPI-unaware context before creating Tk windows.
        try:C.WinDLL('user32').SetProcessDpiAwarenessContext(C.c_void_p(-1))
        except (AttributeError,OSError):pass
    root=tk.Tk()
    try:Editor(root,args.scene)
    except Exception as ex:messagebox.showerror('MyEngine 2',str(ex));root.destroy();return
    root.mainloop()
if __name__=='__main__':main()
