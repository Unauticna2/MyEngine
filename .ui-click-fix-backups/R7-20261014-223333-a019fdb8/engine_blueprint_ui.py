"""Small visual node editor with typed ports, hints and a Python preview."""
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from engine_blueprints import SPECS,Graph,example,generated_source,save_python
from engine_scene import atomic_json

class BlueprintEditor:
    def __init__(self,parent,root,path=None,on_generated=None,*,data=None,on_apply=None,ui_data=None):
        self.root=Path(root).resolve();self.path=Path(path) if path else None;self.on_generated=on_generated
        self.on_apply=on_apply;self.ui_data=ui_data;self.param_vars=None
        from engine_node_api import load_plugins
        from engine_trust import allowed
        if allowed(self.root):load_plugins(self.root)
        self.data=json.loads(json.dumps(data)) if data is not None else json.loads(self.path.read_text(encoding='utf-8-sig')) if self.path else example();Graph(self.data)
        self.selected=None;self.connection=None;self.drag=None;self.dirty=False;self.items={};self.ports={}
        self.w=tk.Toplevel(parent);self.w.title('Blueprints → Python');self.w.geometry('1200x770');self.w.minsize(850,500)
        bar=ttk.Frame(self.w,padding=6);bar.pack(fill='x')
        kinds=list(SPECS)
        if on_apply:kinds=sorted(kinds,key=lambda kind:(not kind.startswith('UI'),kind not in ('LoadScene','Print'),kind))
        self.kind=tk.StringVar(value='UIVisible' if on_apply else 'Move');self.kind_box=ttk.Combobox(bar,textvariable=self.kind,values=kinds,state='readonly',width=18);self.kind_box.pack(side='left')
        generate=('Apply to UI',self.apply_to_ui) if on_apply else ('Generate Python',self.generate)
        for name,fn in [('Add node',self.add),('Open',self.open),('Save graph',self.save),generate,('Delete node',self.delete),('Disconnect',self.disconnect),('Reload nodes',self.reload_nodes)]:ttk.Button(bar,text=name,command=fn).pack(side='left',padx=3)
        panes=ttk.Panedwindow(self.w,orient='horizontal');panes.pack(fill='both',expand=True)
        area=ttk.Frame(panes);panes.add(area,weight=4)
        self.canvas=tk.Canvas(area,bg='#141a23',highlightthickness=0,scrollregion=(0,0,4000,3000))
        sx=ttk.Scrollbar(area,orient='horizontal',command=self.canvas.xview);sy=ttk.Scrollbar(area,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        sx.pack(side='bottom',fill='x');sy.pack(side='right',fill='y');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Button-1>',self.down);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',lambda e:setattr(self,'drag',None))
        self.canvas.bind('<Button-3>',lambda e:self.cancel_connection())
        right=ttk.Frame(panes,padding=10);panes.add(right,weight=1)
        self.hint=tk.StringVar(value='Click an output circle, then a compatible input. Drag node headers. Right click cancels a link.')
        ttk.Label(right,textvariable=self.hint,wraplength=280).pack(fill='x',pady=5)
        self.param_form=ttk.Frame(right);self.param_form.pack(fill='x')
        self.params=tk.Text(right,height=12,width=32,bg='#1b2431',fg='#d8e5f6',insertbackground='white');self.params.pack(fill='x')
        self.apply_button=ttk.Button(right,text='Apply parameters (JSON)',command=self.apply);self.apply_button.pack(fill='x',pady=5)
        ttk.Label(right,text='Python preview — read only').pack(anchor='w',pady=5)
        self.preview=tk.Text(right,height=16,width=32,bg='#10151c',fg='#a2d7ce',wrap='none');self.preview.pack(fill='both',expand=True)
        self.status=tk.StringVar();ttk.Label(self.w,textvariable=self.status,padding=6).pack(fill='x')
        self.w.protocol('WM_DELETE_WINDOW',self.close);self.draw()
        from engine_theme import manager
        self.theme=manager(self.w)
        if self.theme:self.theme.listeners.append(self.theme_changed)
        if on_apply and self.data['nodes']:
            node=self.data['nodes'][-1];self.selected=node['id'];self.show_parameters(node);self.draw()
    def reload_nodes(self):
        try:
            from engine_node_api import load_plugins
            names=load_plugins(self.root);self.kind_box.configure(values=list(SPECS));self.draw();self.status.set('Loaded developer nodes: '+', '.join(names))
        except Exception as ex:self.error(ex)
    def error(self,ex):messagebox.showerror('Blueprints',str(ex),parent=self.w)
    def cancel_connection(self):self.connection=None;self.status.set('Connection cancelled')
    def show_parameters(self,node):
        self.hint.set(SPECS[node['type']][1])
        params=dict(SPECS[node['type']][2]);params.update(node.get('params',{}))
        for child in self.param_form.winfo_children():child.destroy()
        simple=node['type'] in ('UIClick','UIVisible','UIShowSlide','UINextSlide','UIElementEnabled','UISlideEnabled','LoadScene','Print')
        self.param_vars={} if simple else None
        if not simple:
            self.params.pack(fill='x',before=self.apply_button)
            self.params.delete('1.0','end');self.params.insert('1.0',json.dumps(params,ensure_ascii=False,indent=2))
            self.apply_button.configure(text='Apply parameters (JSON)');return
        self.params.pack_forget();self.apply_button.configure(text='Apply parameters')
        slides={str(s['id']):s for s in (self.ui_data or {}).get('slides',[])}
        widgets={}
        for key,value in params.items():
            if isinstance(value,bool):
                var=tk.BooleanVar(value=value);widget=ttk.Checkbutton(self.param_form,text=key,variable=var)
            else:
                ttk.Label(self.param_form,text={'slide':'Slide ID','element':'Element ID','path':'Scene path','text':'Text'}.get(key,key)).pack(anchor='w',pady=(5,0))
                var=tk.StringVar(value=str(value));values=None
                if key=='slide' and slides:values=list(slides)
                if key=='element' and slides:values=[str(e['id']) for e in slides.get(str(params.get('slide')),{}).get('elements',[])]
                if key=='path' and node['type']=='LoadScene':
                    from engine_projects import project_scenes
                    values=project_scenes(self.root)
                widget=ttk.Combobox(self.param_form,textvariable=var,values=values,state='normal' if key=='path' else 'readonly') if values is not None else ttk.Entry(self.param_form,textvariable=var)
            widget.pack(fill='x',pady=3);self.param_vars[key]=var;widgets[key]=widget
        if 'slide' in widgets and 'element' in widgets and slides:
            def change_slide(event=None):
                elements=[str(e['id']) for e in slides.get(self.param_vars['slide'].get(),{}).get('elements',[])]
                widgets['element'].configure(values=elements)
                if self.param_vars['element'].get() not in elements:self.param_vars['element'].set(elements[0] if elements else '')
            widgets['slide'].bind('<<ComboboxSelected>>',change_slide)
        if not params:ttk.Label(self.param_form,text='No parameters').pack(anchor='w')
    def draw(self):
        from engine_theme import manager
        tm=manager(self.w);pal=tm.palette() if tm else {'panel':'#141a23','fg':'#f1f5fa','line':'#96b8d5','select':'#ffcf65','bg':'#263142'};strong=bool(tm and tm.current=='Sunlight')
        c=self.canvas;c.delete('all');self.items={};self.ports={}
        for n in self.data['nodes']:
            x,y=n.get('x',40),n.get('y',40);spec=SPECS[n['type']];h=50+24*max(len(spec[3]),len(spec[4]),1)
            item=c.create_rectangle(x,y,x+210,y+h,fill=pal['bg'],outline=pal['select'] if n['id']==self.selected else pal['line'],width=4 if strong else 2);self.items[item]=n['id']
            item=c.create_text(x+12,y+17,text=spec[0],anchor='w',fill=pal['fg'],font=('Segoe UI',11,'bold'));self.items[item]=n['id']
            for side,ports in [('in',spec[3]),('out',spec[4])]:
                for j,(port,kind) in enumerate(ports.items()):
                    px=x if side=='in' else x+210;py=y+48+j*24;color=({'exec':'#000000','number':'#006040','bool':'#800060'} if tm and tm.current!='Dark' else {'exec':'white','number':'#64d4ad','bool':'#dc85de'})[kind]
                    item=c.create_oval(px-6,py-6,px+6,py+6,fill=color,outline=color);self.ports[item]=(n['id'],port,side,kind,px,py)
                    c.create_text(px+(12 if side=='in' else -12),py,text=port,anchor='w' if side=='in' else 'e',fill=color,font=('Segoe UI',11,'bold') if strong else ('Segoe UI',9))
        coords={(p[0],p[1],p[2]):p[4:6] for p in self.ports.values()}
        for a,ap,b,bp in self.data['links']:
            ax,ay=coords[a,ap,'out'];bx,by=coords[b,bp,'in']
            line=c.create_line(ax,ay,ax+65,ay,bx-65,by,bx,by,smooth=True,arrow='last',width=4 if strong else 2,fill=pal['line']);c.tag_lower(line)
        try:
            code,unused=generated_source(self.data);self.status.set(f'{len(self.data["nodes"])} nodes · {len(unused)} disconnected from events')
        except Exception as ex:code=str(ex);self.status.set('Graph error: '+str(ex))
        self.preview.configure(state='normal');self.preview.delete('1.0','end');self.preview.insert('1.0',code);self.preview.configure(state='disabled')
    def down(self,event):
        c=self.canvas;x,y=c.canvasx(event.x),c.canvasy(event.y);items=c.find_overlapping(x-6,y-6,x+6,y+6)
        port=next((self.ports[i] for i in reversed(items) if i in self.ports),None)
        if port:
            nid,name,side,kind,_,_=port
            if side=='out':self.connection=port;self.status.set('Select a '+kind+' input');return
            if self.connection:
                a,ap,_,at,_,_=self.connection
                if at!=kind:self.error('Port types do not match');return
                link=[a,ap,nid,name];old=list(self.data['links'])
                self.data['links']=[l for l in old if not (kind!='exec' and l[2:]==[nid,name]) and not (kind=='exec' and l[:2]==[a,ap])]+[link]
                try:Graph(self.data)
                except Exception as ex:self.data['links']=old;self.error(ex);return
                self.connection=None;self.dirty=True;self.draw()
            return
        nid=next((self.items[i] for i in reversed(items) if i in self.items),None)
        if nid:
            self.selected=nid;n=next(n for n in self.data['nodes'] if n['id']==nid);self.show_parameters(n)
            if y<n.get('y',40)+34:self.drag=(nid,x-n.get('x',40),y-n.get('y',40))
            self.draw()
    def motion(self,event):
        if not self.drag:return
        nid,dx,dy=self.drag;n=next(n for n in self.data['nodes'] if n['id']==nid)
        n['x']=max(10,self.canvas.canvasx(event.x)-dx);n['y']=max(10,self.canvas.canvasy(event.y)-dy);self.dirty=True;self.draw()
    def add(self):
        if len(self.data['nodes'])>=256:self.error('Limit: 256 nodes');return
        used={n['id'] for n in self.data['nodes']};i=1
        while str(i) in used:i+=1
        n={'id':str(i),'type':self.kind.get(),'params':dict(SPECS[self.kind.get()][2]),'x':self.canvas.canvasx(50),'y':self.canvas.canvasy(70+len(used)%5*55)}
        self.data['nodes'].append(n)
        try:Graph(self.data)
        except Exception as ex:self.data['nodes'].pop();self.error(ex);return
        self.selected=str(i);self.dirty=True;self.show_parameters(n);self.draw()
    def apply(self):
        if self.selected is None:return True
        n=next(n for n in self.data['nodes'] if n['id']==self.selected);old=n.get('params',{})
        try:
            p={key:var.get() for key,var in self.param_vars.items()} if self.param_vars is not None else json.loads(self.params.get('1.0','end'))
            if not isinstance(p,dict):raise ValueError('Parameters must be a JSON object')
            n['params']=p;Graph(self.data).compile();self.dirty=True;self.draw();return True
        except Exception as ex:n['params']=old;self.error(ex);return False
    def apply_to_ui(self):
        if not self.apply():return
        try:
            path,message=self.on_apply(self.data)
            self.path=Path(path);self.dirty=False;self.draw();self.status.set(message)
        except Exception as ex:self.error(ex)
    def delete(self):
        if self.selected is None:return
        self.disconnect();self.data['nodes']=[n for n in self.data['nodes'] if n['id']!=self.selected];self.selected=None;self.dirty=True;self.draw()
    def disconnect(self):
        self.data['links']=[l for l in self.data['links'] if l[0]!=self.selected and l[2]!=self.selected];self.dirty=True;self.draw()
    def confirm(self):
        if not self.dirty:return True
        answer=messagebox.askyesnocancel('Blueprints','Save this graph?',parent=self.w)
        return False if answer is None else self.save() if answer else True
    def save(self):
        try:
            Graph(self.data).compile()
            if self.path is None:
                p=filedialog.asksaveasfilename(parent=self.w,initialdir=self.root/'scripts',defaultextension='.blueprint.json',filetypes=[('Blueprint','*.blueprint.json')])
                if not p:return False
                self.path=Path(p)
            self.path.resolve().relative_to(self.root.resolve());atomic_json(self.path,self.data);self.dirty=False;self.status.set('Saved '+self.path.name);return True
        except Exception as ex:self.error(ex);return False
    def open(self):
        if not self.confirm():return
        p=filedialog.askopenfilename(parent=self.w,initialdir=self.root,filetypes=[('Blueprint','*.blueprint.json')])
        if not p:return
        try:
            data=json.loads(Path(p).read_text(encoding='utf-8-sig'));Graph(data)
            self.data=data;self.path=Path(p);self.selected=None;self.connection=None;self.dirty=False;self.draw()
        except Exception as ex:self.error(ex)
    def generate(self):
        if not self.save():return
        suggested=self.path.name.removesuffix('.blueprint.json')+'.py'
        p=filedialog.asksaveasfilename(parent=self.w,initialdir=self.path.parent,initialfile=suggested,defaultextension='.py',filetypes=[('Python','*.py')],confirmoverwrite=False)
        if not p:return
        try:
            path=Path(p);path.resolve().relative_to(self.root.resolve());unused=save_python(path,self.data)
            self.status.set('Generated '+path.name+f' · {len(unused)} unused nodes; your code outside the region is preserved')
            if self.on_generated:self.on_generated(path)
        except Exception as ex:self.error(ex)
    def theme_changed(self,*args):
        if self.w.winfo_exists():self.draw()
    def close(self):
        if self.confirm():
            if self.theme and self.theme_changed in self.theme.listeners:self.theme.listeners.remove(self.theme_changed)
            self.w.destroy()
