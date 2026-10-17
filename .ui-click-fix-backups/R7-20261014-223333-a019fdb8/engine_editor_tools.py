"""Scene-level dialogs kept separate from the Inspector."""
from pathlib import Path
import copy,json,shutil
import tkinter as tk
from tkinter import ttk,filedialog,messagebox


def _commit(editor,key,value):
    editor.document.checkpoint();editor.document.data[key]=value
    editor.changed();editor.reload()


def skybox_dialog(editor):
    if not editor.can_edit():return
    from engine_skybox import sky_settings,sky_paths
    root=editor.path_root;parent=editor.window
    w=tk.Toplevel(parent);w.title('Skybox');w.geometry('650x430')
    value=copy.deepcopy(editor.document.data.get('skybox')) or {'texture':'','yaw':0,'exposure':1}
    ttk.Label(w,text='Panorama PNG/BMP, or six faces: px nx py ny pz nz.\nPaths are relative to the project.',padding=12).pack(anchor='w')
    text=tk.Text(w,height=12);text.pack(fill='both',expand=True,padx=12);text.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2))
    row=ttk.Frame(w,padding=12);row.pack(fill='x')
    def import_image():
        p=filedialog.askopenfilename(parent=w,filetypes=[('Sky image','*.png *.bmp')])
        if not p:return
        source=Path(p).resolve()
        try:
            try:rel=source.relative_to(root).as_posix()
            except ValueError:
                target=root/'assets/skyboxes'/source.name;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() and target.read_bytes()!=source.read_bytes():
                    i=1
                    while target.exists():target=root/'assets/skyboxes'/(source.stem+f'_{i}'+source.suffix);i+=1
                shutil.copy2(source,target);rel=target.relative_to(root).as_posix()
            text.delete('1.0','end');text.insert('1.0',json.dumps({'texture':rel,'yaw':0,'exposure':1},indent=2));editor.refresh_project()
        except Exception as ex:editor.error(ex)
    def apply():
        try:
            if not editor.can_edit():return
            d=sky_settings(root,json.loads(text.get('1.0','end')))
            for p in sky_paths(root,d):
                target=(root/p).resolve();target.relative_to(root)
                if not target.is_file():raise FileNotFoundError(p)
            _commit(editor,'skybox',d);w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(row,text='Choose / import panorama',command=import_image).pack(side='left')
    ttk.Button(row,text='Remove sky',command=lambda:(_commit(editor,'skybox',None),w.destroy()) if editor.can_edit() else None).pack(side='left',padx=5)
    ttk.Button(row,text='Apply',command=apply).pack(side='right')


def character_dialog(editor):
    if not editor.can_edit():return
    w=tk.Toplevel(editor.window);w.title('Player physics / Python controller');w.geometry('530x610')
    frame=ttk.Frame(w,padding=14);frame.pack(fill='both',expand=True)
    camera=copy.deepcopy(editor.document.data.get('camera',{}));d=camera.get('controller',{})
    mode=tk.StringVar(value=d.get('mode','fly'));ttk.Label(frame,text='Movement mode').pack(anchor='w')
    ttk.Combobox(frame,textvariable=mode,values=('fly','walk','script'),state='readonly').pack(fill='x',pady=5)
    fields={}
    defaults={'size':[.5,1.6,.5],'center':[0,-.6,0],'mass':75,'speed':3.5,'sprint':7,'jump':5,'script':''}
    hints={'size':'Collision box size [X,Y,Z]','center':'Box center relative to camera [X,Y,Z]','mass':'Mass','speed':'Walk speed','sprint':'Sprint speed','jump':'Jump speed','script':'Custom Python script (mode = script)'}
    for key,default in defaults.items():
        ttk.Label(frame,text=hints[key]).pack(anchor='w');value=d.get(key,default)
        fields[key]=tk.StringVar(value=value if isinstance(value,str) else json.dumps(value));ttk.Entry(frame,textvariable=fields[key]).pack(fill='x',pady=(0,6))
    ttk.Label(frame,text='Walk: WASD · Shift · Space. Physics uses an upright box.\nScript: self.entity is the camera; set Rigidbody velocity\nin fixed_update. Do not attach a second movement script.',wraplength=490).pack(anchor='w',pady=6)
    def choose():
        p=filedialog.askopenfilename(parent=w,initialdir=editor.path_root/'scripts',filetypes=[('Python','*.py')])
        if p:
            try:fields['script'].set(Path(p).resolve().relative_to(editor.path_root).as_posix());mode.set('script')
            except ValueError:editor.error('Import the script into the project first')
    ttk.Button(frame,text='Choose Python script',command=choose).pack(fill='x')
    def apply():
        try:
            if not editor.can_edit():return
            cfg={k:(v.get() if k=='script' else json.loads(v.get())) for k,v in fields.items()};cfg['mode']=mode.get()
            from engine_physics import Collider as BoxCollider
            BoxCollider.from_json({'type':'box','size':cfg['size'],'center':cfg['center']})
            from engine_assets import finite
            for key in ('mass','speed','sprint','jump'):cfg[key]=finite(cfg[key])
            if cfg['mass']<=0 or min(cfg[k] for k in ('speed','sprint','jump'))<0:raise ValueError('Invalid mass or speed')
            if cfg['mode']=='script':
                p=(editor.path_root/cfg['script']).resolve();p.relative_to(editor.path_root)
                if not cfg['script'] or not p.is_file():raise ValueError('Select an existing Python script')
            camera['controller']=cfg;camera.pop('rigidbody',None);camera.pop('freeFly',None)
            _commit(editor,'camera',camera);w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(frame,text='Replace player physics',command=apply).pack(fill='x',pady=12)


def blueprint_dialog(editor,path=None):
    if not editor.can_edit():return
    from engine_blueprint_ui import BlueprintEditor
    def generated(path):
        editor.refresh_project()
        if editor.selected is not None and editor.can_edit():
            if messagebox.askyesno('Blueprints','Attach generated script to the selected object?',parent=editor.window):
                text=editor.inspector_vars['scripts'];paths=[p.strip() for p in text.get('1.0','end').splitlines() if p.strip()]
                rel=path.resolve().relative_to(editor.path_root).as_posix()
                if rel not in paths:paths.append(rel)
                text.delete('1.0','end');text.insert('1.0','\n'.join(paths));editor.apply()
    BlueprintEditor(editor.window,editor.path_root,path,generated)


def data_asset_dialog(editor,path=None):
    from engine_scriptable import ScriptableObject
    if not editor.can_edit():return
    asset=ScriptableObject.load(path) if path else ScriptableObject({'health':100.,'speed':4.},type_name='CharacterSettings',schema={'health':{'type':'float','min':0},'speed':{'type':'float','min':0}})
    w=tk.Toplevel(editor.window);w.title('Scriptable Object');w.geometry('670x570')
    ttk.Label(w,text='Shared JSON data. Type/schema describe fields; no Python is executed.',padding=10).pack(anchor='w')
    text=tk.Text(w,wrap='none');text.pack(fill='both',expand=True,padx=10)
    text.insert('1.0',json.dumps({'type':asset.type_name,'schema':asset.schema,'data':asset.to_dict()},ensure_ascii=False,indent=2))
    def save():
        try:
            raw=json.loads(text.get('1.0','end'));value=ScriptableObject(raw['data'],type_name=raw.get('type','Data'),schema=raw.get('schema',{}))
            target=path or filedialog.asksaveasfilename(parent=w,initialdir=editor.path_root/'assets',defaultextension='.scriptable.json',filetypes=[('Scriptable Object','*.scriptable.json')])
            if not target:return
            Path(target).resolve().relative_to(editor.path_root);value.save(target);editor.refresh_project();w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(w,text='Save data asset',command=save).pack(fill='x',padx=10,pady=10)


def save_prefab_dialog(editor):
    if not editor.can_edit():return
    from engine_prefabs import save_prefab
    ids=[int(i) for i in editor.hierarchy.selection()]
    if not ids:editor.error('Select one or more objects (Ctrl-click in Hierarchy)');return
    p=filedialog.asksaveasfilename(parent=editor.window,initialdir=editor.path_root/'assets',defaultextension='.prefab.json',filetypes=[('Prefab','*.prefab.json')])
    if p:
        try:Path(p).resolve().relative_to(editor.path_root);save_prefab(p,editor.document,ids);editor.refresh_project()
        except Exception as ex:editor.error(ex)


def add_prefab_dialog(editor,path=None):
    if not editor.can_edit():return
    from engine_prefabs import load_prefab,append_prefab
    p=path or filedialog.askopenfilename(parent=editor.window,initialdir=editor.path_root,filetypes=[('Prefab','*.prefab.json')])
    if p:
        try:
            ids=append_prefab(editor.document,load_prefab(p));editor.populate_hierarchy();editor.select(ids[0]);editor.changed();editor.reload()
        except Exception as ex:editor.error(ex)


def project_trust_dialog(editor):
    if not editor.can_edit():return
    from engine_trust import allowed,set_allowed
    current=allowed(editor.path_root)
    answer=messagebox.askyesno('Project scripts','Scripts currently: '+('ALLOWED' if current else 'BLOCKED')+'\n\nAllow Python scripts and developer node plugins for this project?\nPython has normal access to your files; this is a permission switch, not a sandbox.\nChoose No to block scripts.',parent=editor.window)
    set_allowed(editor.path_root,answer);editor.reload();editor.log('Project scripts '+('allowed' if answer else 'blocked'))


def lighting_dialog(editor):
    if not editor.can_edit():return
    w=tk.Toplevel(editor.window);w.title('Shadows and sun');w.geometry('650x540')
    panel=ttk.Frame(w,padding=12);panel.pack(fill='both',expand=True)
    enabled=tk.BooleanVar(value=editor.document.data.get('shadows',{}).get('enabled',True));ttk.Checkbutton(panel,text='Enable directional shadows (polygons + voxels)',variable=enabled).pack(anchor='w')
    fields={}
    values={'size':editor.document.data.get('shadows',{}).get('size',1024),'distance':editor.document.data.get('shadows',{}).get('distance',30),'bias':editor.document.data.get('shadows',{}).get('bias',.0006)}
    for k,value in values.items():fields[k]=editor.field(panel,{'size':'Shadow size: 512 / 1024 / 2048','distance':'Distance around camera','bias':'Depth bias'}[k],str(value))
    from engine_skybox import sun_settings
    sun=sun_settings(editor.document.data.get('sun')) or {};fields['texture']=editor.field(panel,'Sun texture (PNG/BMP), empty = no sun',sun.get('texture',''))
    def choose():
        p=filedialog.askopenfilename(parent=w,filetypes=[('Sun texture','*.png *.bmp')])
        if not p:return
        source=Path(p).resolve()
        try:
            try:rel=source.relative_to(editor.path_root).as_posix()
            except ValueError:
                target=editor.path_root/'assets/sun'/source.name;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() and not messagebox.askyesno('Replace texture?',str(target),parent=w):return
                shutil.copy2(source,target);rel=target.relative_to(editor.path_root).as_posix()
            fields['texture'].set(rel);editor.refresh_project()
        except Exception as ex:editor.error(ex)
    ttk.Button(panel,text='Choose / import sun texture',command=choose).pack(anchor='w',pady=5)
    fields['sunSize']=editor.field(panel,'Sun angular size (degrees)',str(sun.get('size',8)))
    fields['brightness']=editor.field(panel,'Sun brightness',str(sun.get('brightness',1)))
    mask=tk.BooleanVar(value=sun.get('blackAsAlpha',True));ttk.Checkbutton(panel,text='Treat black as transparent (or use PNG alpha)',variable=mask).pack(anchor='w',pady=5)
    def apply():
        try:
            if not editor.can_edit():return
            from engine_render import settings
            from engine_skybox import sun_settings
            shadow=settings({'enabled':enabled.get(),'size':int(fields['size'].get()),'distance':float(fields['distance'].get()),'bias':float(fields['bias'].get())})
            texture=fields['texture'].get().strip();sun=sun_settings({'texture':texture,'size':float(fields['sunSize'].get()),'brightness':float(fields['brightness'].get()),'blackAsAlpha':mask.get()}) if texture else None
            if sun:
                p=(editor.path_root/texture).resolve();p.relative_to(editor.path_root)
                if not p.is_file():raise FileNotFoundError(texture)
            editor.document.checkpoint();editor.document.data.update(shadows=shadow,sun=sun);editor.changed();editor.reload();w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(panel,text='Apply lighting',command=apply).pack(fill='x',pady=10)
