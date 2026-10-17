"""MyEngine Hub — create, add and open independent projects; export Windows players."""
from pathlib import Path
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from engine_projects import Registry,create_project,read_project,adopt_project,project_scenes,PROJECT_FILE,VERSION
from engine_build_ui import show_build

ENGINE=Path(__file__).resolve().parent

class Hub:
    def __init__(self,window):
        self.window=window;self.registry=Registry();self.build_windows=[]
        window.title('MyEngine Hub');window.geometry('1000x600');window.minsize(760,420)
        try:window.iconbitmap(str(ENGINE/'MyEngineN2.ico'))
        except tk.TclError:pass
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',background='#242831',foreground='#e1e7f0',fieldbackground='#171b22',font=('Segoe UI',10))
        style.configure('Treeview',background='#191d25',fieldbackground='#191d25',foreground='#dce7f5',rowheight=34)
        style.map('Treeview',background=[('selected','#335573')]);style.configure('TButton',padding=9)
        window.configure(bg='#242831')
        header=ttk.Frame(window,padding=20);header.pack(fill='x')
        ttk.Label(header,text='MYENGINE HUB',font=('Segoe UI',21,'bold')).pack(side='left')
        ttk.Label(header,text='Engine '+VERSION+' · Windows x64').pack(side='right')
        actions=ttk.Frame(window,padding=(20,0));actions.pack(fill='x')
        for label,fn in [('New project',self.new),('Add project',self.add),('Open Editor',self.open),('Build game',self.build),('Remove from list',self.forget)]:
            ttk.Button(actions,text=label,command=fn).pack(side='left',padx=(0,6))
        more=ttk.Frame(window,padding=(20,8));more.pack(fill='x')
        for label,fn in [('GitHub packages',self.packages),('Publish project',self.publish),('Refresh projects',self.refresh)]:ttk.Button(more,text=label,command=fn).pack(side='left',padx=(0,6))
        self.tree=ttk.Treeview(window,columns=('name','path','opened'),show='headings',selectmode='browse')
        for key,label,width in [('name','Project',190),('path','Folder',540),('opened','Last opened (UTC)',185)]:
            self.tree.heading(key,text=label);self.tree.column(key,width=width)
        self.tree.pack(fill='both',expand=True,padx=20,pady=18);self.tree.bind('<Double-1>',lambda e:self.open())
        self.status=tk.StringVar(value='Create a project or add a folder containing '+PROJECT_FILE)
        ttk.Label(window,textvariable=self.status,padding=20).pack(fill='x')
        from engine_theme import attach
        self.theme=attach(window);self.theme.selector(more)
        window.protocol('WM_DELETE_WINDOW',self.close);self.refresh()
    def refresh(self):
        self.registry=Registry(self.registry.path)
        self.tree.delete(*self.tree.get_children())
        for i,p in enumerate(self.registry.entries):self.tree.insert('','end',iid=str(i),values=(p['name'],p['path'],p.get('opened','')))
    def selected(self):
        rows=self.tree.selection()
        if not rows:raise ValueError('Select a project first.')
        return Path(self.registry.entries[int(rows[0])]['path'])
    def error(self,ex):messagebox.showerror('MyEngine Hub',str(ex),parent=self.window)
    def launch(self,root):
        p=read_project(root);self.registry.remember(root);self.refresh()
        subprocess.Popen([sys.executable,str(ENGINE/'MyEngine2Editor.py'),str(root/p['mainScene']),'--project',str(root)],cwd=ENGINE)
        self.status.set('Opened '+p['name'])
    def open(self):
        try:self.launch(self.selected())
        except Exception as ex:self.error(ex)
    def add(self):
        folder=filedialog.askdirectory(parent=self.window,title='Select an existing MyEngine project folder')
        if not folder:return
        try:
            if not (Path(folder)/PROJECT_FILE).is_file():
                scenes=project_scenes(folder)
                if not scenes:raise ValueError('No scene JSON found in this folder.')
                w=tk.Toplevel(self.window);w.title('Add existing project');w.geometry('550x180')
                ttk.Label(w,text='Choose the start scene for this existing folder:',padding=12).pack(anchor='w')
                scene=tk.StringVar(value='map.json' if 'map.json' in scenes else scenes[0])
                ttk.Combobox(w,textvariable=scene,values=scenes,state='readonly').pack(fill='x',padx=12)
                def accept():
                    try:
                        adopt_project(folder,Path(folder).name,scene.get());self.registry.remember(folder);self.refresh();w.destroy()
                    except Exception as ex:self.error(ex)
                ttk.Button(w,text='Add project',command=accept).pack(pady=12);return
            self.registry.remember(folder);self.refresh()
        except Exception as ex:self.error(ex)
    def forget(self):
        try:self.registry.forget(self.selected());self.refresh();self.status.set('Removed from this list. Project files remain on disk.')
        except Exception as ex:self.error(ex)
    def new(self):
        window=tk.Toplevel(self.window);window.title('New MyEngine project');window.geometry('560x320')
        panel=ttk.Frame(window,padding=18);panel.pack(fill='both',expand=True)
        name=tk.StringVar(value='MyGame');parent=tk.StringVar(value=str(Path.home()/'Documents/MyEngine Projects'));template=tk.StringVar(value='Basic 3D')
        for label,var in [('Project name',name),('Parent folder',parent)]:
            ttk.Label(panel,text=label).pack(anchor='w',pady=(5,3));ttk.Entry(panel,textvariable=var).pack(fill='x')
        def browse():
            p=filedialog.askdirectory(parent=window)
            if p:parent.set(p)
        ttk.Button(panel,text='Browse…',command=browse).pack(anchor='e',pady=4)
        ttk.Label(panel,text='Template').pack(anchor='w')
        ttk.Combobox(panel,textvariable=template,values=('Basic 3D','VOX + 4D demo','Empty'),state='readonly').pack(fill='x')
        def create():
            try:
                p=create_project(ENGINE,parent.get(),name.get(),template.get());window.destroy();self.launch(p)
            except Exception as ex:self.error(ex)
        ttk.Button(panel,text='Create and open',command=create).pack(fill='x',pady=15)
    def build(self):
        try:
            p=self.selected();meta=read_project(p);self.build_windows.append(show_build(self.window,ENGINE,p,meta['mainScene']))
        except Exception as ex:self.error(ex)
    def packages(self):
        from engine_package_ui import PackageBrowser
        PackageBrowser(self.window,ENGINE)
    def publish(self):
        try:
            from engine_package_ui import PublishDialog
            p=self.selected();PublishDialog(self.window,ENGINE,p,read_project(p)['mainScene'])
        except Exception as ex:self.error(ex)
    def close(self):
        # A non-daemon build thread owns its staging folder until completion.
        import threading
        if any(t.name in ('player-build','package-work') and t.is_alive() for t in threading.enumerate()):
            self.status.set('Wait for the current game build to finish.');return
        self.window.destroy()

def main():
    ready=os.environ.pop('MYENGINE_HUB_READY_FILE',None)
    w=tk.Tk();Hub(w)
    if ready:w.after_idle(lambda:Path(ready).write_text('ready',encoding='ascii'))
    w.mainloop()
if __name__=='__main__':main()
