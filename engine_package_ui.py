"""Package Hub UI. Network and Git work never run on the Tk thread."""
from pathlib import Path
import base64,json,queue,threading,time,subprocess,webbrowser
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from engine_packages import executable,search_page,package_details,clone_package,prepare_package,publish_new,package_files,run
from engine_projects import Registry

GIT_URL='https://git-scm.com/download/win'
GH_URL='https://cli.github.com/'

def dependencies(parent,publish=False):
    for name,url in [('git',GIT_URL)]+([('gh',GH_URL)] if publish else []):
        if not executable(name):
            if messagebox.askyesno('Install '+name, name+' was not found. Open its official download page?\nAfter installation, restart MyEngine Hub.',parent=parent):webbrowser.open(url)
            return False
    return True

class BackgroundWindow:
    def setup(self,parent,title,size):
        self.w=tk.Toplevel(parent);self.w.title(title);self.w.geometry(size);self.busy=False;self.queue=queue.Queue();self.closed=False
        self.status=tk.StringVar(value='Ready');self.w.protocol('WM_DELETE_WINDOW',self.close);self.w.after(80,self.poll)
    def task(self,fn,callback):
        if self.busy:return
        self.busy=True;self.callback=callback;self.status.set('Working…')
        def worker():
            try:self.queue.put(('ok',fn()))
            except Exception as ex:self.queue.put(('error',str(ex)))
        threading.Thread(target=worker,name='package-work',daemon=False).start()
    def log(self,text):self.queue.put(('progress',text))
    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,value=self.queue.get_nowait()
                if kind=='progress':self.status.set(value);continue
                self.busy=False
                if kind=='error':self.status.set(value);messagebox.showerror('GitHub packages',value,parent=self.w)
                else:
                    self.status.set('Done')
                    try:self.callback(value)
                    except Exception as ex:messagebox.showerror('GitHub packages',str(ex),parent=self.w)
        except queue.Empty:pass
        self.w.after(80,self.poll)
    def close(self):
        if self.busy:self.status.set('Wait for this network / Git operation to finish.');return
        self.closed=True;self.w.destroy()

class PackageBrowser(BackgroundWindow):
    def __init__(self,parent,engine,project=None):
        self.engine=Path(engine);self.project=Path(project) if project else None;self.repos={};self.query=0;self.page=1;self.more=True
        self.setup(parent,'MyEngine · GitHub packages','1060x740')
        top=ttk.Frame(self.w,padding=10);top.pack(fill='x')
        ttk.Label(top,text='Author (optional)').pack(side='left');self.author=tk.StringVar();ttk.Entry(top,textvariable=self.author,width=22).pack(side='left',padx=6)
        for label,fn in [('Search / refresh',self.search),('Next results',self.next),('Install Git',lambda:webbrowser.open(GIT_URL))]:ttk.Button(top,text=label,command=fn).pack(side='left',padx=3)
        ttk.Label(self.w,text='Search: MyPakege_ / MyPackege_ names and topic:mypakege. Results are public and paginated.',padding=10).pack(anchor='w')
        split=ttk.Panedwindow(self.w,orient='horizontal');split.pack(fill='both',expand=True,padx=10)
        left=ttk.Frame(split);right=ttk.Frame(split);split.add(left,weight=2);split.add(right,weight=1)
        self.tree=ttk.Treeview(left,columns=('stars',),show='tree headings',selectmode='browse');self.tree.heading('#0',text='Repository');self.tree.heading('stars',text='Stars');self.tree.column('stars',width=55)
        self.tree.pack(fill='both',expand=True);self.tree.bind('<<TreeviewSelect>>',self.details)
        self.image=ttk.Label(right,text='Select a package');self.image.pack(fill='x',pady=8);self.photo=None
        self.description=tk.Text(right,width=36,wrap='word',height=16);self.description.pack(fill='both',expand=True);self.description.configure(state='disabled')
        bottom=ttk.Frame(self.w,padding=10);bottom.pack(fill='x')
        ttk.Button(bottom,text='Open repository',command=self.open_repo).pack(side='left')
        ttk.Button(bottom,text='Clone project…',command=self.install).pack(side='left',padx=6)
        ttk.Button(bottom,text='Add by OWNER/REPO…',command=self.direct).pack(side='left',padx=6)
        ttk.Label(self.w,textvariable=self.status,wraplength=1000,padding=10).pack(fill='x')
    def selected(self):
        s=self.tree.selection()
        if not s:raise ValueError('Select a package')
        return self.repos[s[0]]
    def search(self):
        if self.busy:return
        self.repos.clear();self.tree.delete(*self.tree.get_children());self.query=0;self.page=1;self.more=True;self.filter=self.author.get().strip();self.fetch()
    def next(self):
        if self.busy:return
        if not hasattr(self,'filter'):self.search();return
        if self.more:self.page+=1
        else:self.query+=1;self.page=1
        if self.query>=3:self.status.set('All returned search pages loaded. Use an author filter if GitHub capped the results.');return
        self.fetch()
    def fetch(self):
        q,p,a=self.query,self.page,self.filter
        def received(result):
            for r in result['items']:
                key=r['full_name']
                if key not in self.repos:self.tree.insert('','end',iid=key,text=key,values=(r['stars'],))
                self.repos[key]=r
            self.more=result['more'];self.status.set(f'{len(self.repos)} unique repositories · search {q+1}/3 page {p} · total for this query: {result["total"]}'+(' · GitHub reports incomplete results' if result['incomplete'] or result['total']>1000 else '')+' · Next results loads more')
        self.task(lambda:search_page(q,p,a),received)
    def details(self,event=None):
        if self.busy:return
        try:r=self.selected()
        except ValueError:return
        key=r['full_name']
        def show(value):
            if not self.tree.selection() or self.tree.selection()[0]!=key:return
            text,data=value;self.description.configure(state='normal');self.description.delete('1.0','end');self.description.insert('1.0',text);self.description.configure(state='disabled')
            self.photo=None;self.image.configure(image='',text='No image.png preview')
            if data:
                photo=tk.PhotoImage(data=base64.b64encode(data).decode(),format='png',master=self.w);factor=max(1,(photo.width()+339)//340,(photo.height()+239)//240)
                self.photo=photo.subsample(factor,factor);self.image.configure(image=self.photo,text='')
        self.task(lambda:package_details(r),show)
    def open_repo(self):
        try:webbrowser.open(self.selected()['url'])
        except ValueError as ex:messagebox.showerror('Packages',str(ex),parent=self.w)
    def direct(self):
        if self.busy:return
        from tkinter.simpledialog import askstring
        full=askstring('Repository','OWNER/REPOSITORY',parent=self.w)
        if full:self.clone(full)
    def install(self):
        if self.busy:return
        try:self.clone(self.selected()['full_name'])
        except ValueError as ex:messagebox.showerror('Packages',str(ex),parent=self.w)
    def clone(self,full):
        if not dependencies(self.w):return
        parent=filedialog.askdirectory(parent=self.w,title='Parent folder for the downloaded project')
        if not parent:return
        def done(path):
            Registry().remember(path);self.status.set('Cloned and added to Hub: '+str(path)+'. Refresh Hub to see it. Python has not been executed.')
        self.task(lambda:clone_package(full,parent),done)

class PublishDialog(BackgroundWindow):
    def __init__(self,parent,engine,root,scene):
        self.engine=Path(engine);self.root=Path(root).resolve();self.scene=scene;self.prepared=None
        self.setup(parent,'Publish MyEngine project to GitHub','950x800')
        self.candidates=package_files(self.root);self.included={p for p,_ in self.candidates}
        top=ttk.Frame(self.w,padding=10);top.pack(fill='x')
        self.name=tk.StringVar(value='MyPackege_'+self.root.name);self.owner=tk.StringVar();self.preview=tk.StringVar(value=str(self.root/'image.png') if (self.root/'image.png').exists() else '')
        for label,var in [('Repository name',self.name),('GitHub owner (blank = signed-in user)',self.owner),('Preview PNG → image.png',self.preview)]:
            ttk.Label(top,text=label).pack(anchor='w');ttk.Entry(top,textvariable=var).pack(fill='x')
            var.trace_add('write',lambda *args:self.invalidate())
        ttk.Button(top,text='Choose PNG',command=self.choose).pack(anchor='w',pady=5)
        ttk.Label(top,text='Description → Data.txt').pack(anchor='w');self.description=tk.Text(top,height=3,wrap='word');self.description.pack(fill='x')
        if (self.root/'Data.txt').exists():self.description.insert('1.0',(self.root/'Data.txt').read_text(encoding='utf-8-sig'))
        self.description.bind('<KeyRelease>',lambda e:self.invalidate())
        ttk.Label(self.w,text='Review files below. Double-click to include / exclude. Public means anyone can download these files.',padding=10).pack(anchor='w')
        self.tree=ttk.Treeview(self.w,columns=('include','size'),show='tree headings');self.tree.heading('#0',text='Project file');self.tree.heading('include',text='Include');self.tree.heading('size',text='Bytes');self.tree.column('include',width=70);self.tree.column('size',width=100)
        self.tree.pack(fill='both',expand=True,padx=10);self.tree.bind('<Double-1>',self.toggle)
        for p,size in self.candidates:self.tree.insert('','end',iid=p,text=p,values=('yes',size))
        row=ttk.Frame(self.w,padding=10);row.pack(fill='x')
        for label,fn in [('Install Git',lambda:webbrowser.open(GIT_URL)),('Install gh',lambda:webbrowser.open(GH_URL)),('Login to GitHub',self.login),('Prepare package',self.prepare)]:ttk.Button(row,text=label,command=fn).pack(side='left',padx=3)
        self.publish_button=ttk.Button(row,text='Publish PUBLIC repository',command=self.publish,state='disabled');self.publish_button.pack(side='right')
        ttk.Label(self.w,textvariable=self.status,wraplength=910,padding=10).pack(fill='x')
    def invalidate(self):
        self.prepared=None
        if hasattr(self,'publish_button'):self.publish_button.configure(state='disabled')
    def choose(self):
        if self.busy:return
        p=filedialog.askopenfilename(parent=self.w,filetypes=[('PNG','*.png')])
        if p:self.preview.set(p)
    def toggle(self,event):
        if self.busy:return
        row=self.tree.identify_row(event.y)
        if not row:return
        if row in self.included:self.included.remove(row)
        else:self.included.add(row)
        self.tree.set(row,'include','yes' if row in self.included else 'no');self.invalidate()
    def login(self):
        if self.busy or not dependencies(self.w,True):return
        # Official gh opens a browser for device auth. No credentials stored by the engine.
        subprocess.Popen([executable('gh'),'auth','login','--hostname','github.com','--web','--git-protocol','https'],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        self.status.set('Finish gh login in the opened window, then prepare and publish.')
    def prepare(self):
        if self.busy:return
        name=self.name.get().strip();preview=self.preview.get().strip();description=self.description.get('1.0','end').strip();selected=sorted(self.included)
        import uuid
        stage=self.root/'.myengine'/('publish-'+uuid.uuid4().hex)
        signature=(name,preview,description,selected,self.owner.get().strip())
        def done(result):
            current=(self.name.get().strip(),self.preview.get().strip(),self.description.get('1.0','end').strip(),sorted(self.included),self.owner.get().strip())
            if current!=signature:self.invalidate();self.status.set('Settings changed; prepare again.');return
            self.prepared=result;self.prepared_owner=signature[-1];self.publish_button.configure(state='normal')
            self.status.set(f'Prepared {len(result["files"])} files, {result["bytes"]/1048576:.2f} MiB at {result["path"]}. Publish creates a NEW PUBLIC repository and requests a Pages site.')
        self.task(lambda:prepare_package(self.root,stage,name,self.scene,description,preview,selected),done)
    def publish(self):
        if self.busy or not self.prepared or not dependencies(self.w,True):return
        path=self.prepared['path'];owner=self.prepared_owner;self.publish_button.configure(state='disabled')
        def done(result):
            self.prepared=None
            self.status.set('Published: '+result['repository']+' · Pages requested: '+result['pages']+' (deployment can take time)'+(' · '+'; '.join(result['warnings']) if result['warnings'] else ''))
            messagebox.showinfo('Published',result['repository']+'\n\nPages: '+result['pages']+'\n\n'+'\n'.join(result['warnings']),parent=self.w)
        self.task(lambda:publish_new(path,owner,self.log),done)
