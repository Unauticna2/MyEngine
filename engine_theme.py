"""Four persistent editor themes. Automatic mode follows the local clock."""
from pathlib import Path
from datetime import datetime
import os,json,tkinter as tk
from tkinter import ttk
from engine_scene import atomic_json

THEMES=('Light','Dark','Automatic','Sunlight')
PALETTES={
 'Light':dict(bg='#eaf0f6',panel='#ffffff',fg='#162334',muted='#3c526b',select='#bedbff',entry='#ffffff',line='#586e89',accent='#176da8'),
 'Dark':dict(bg='#202631',panel='#151c27',fg='#e8eff9',muted='#a6b7cf',select='#304f74',entry='#111924',line='#728ba9',accent='#8ccfff'),
 'Sunlight':dict(bg='#ffffff',panel='#ffffff',fg='#000000',muted='#111111',select='#ffdc00',entry='#ffffff',line='#000000',accent='#000066')}

def settings_path():return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'MyEngine2Hub/editor-settings.json'
def effective(mode,hour=None):
 if mode not in THEMES:mode='Dark'
 return ('Light' if 7<=(datetime.now().hour if hour is None else hour)<20 else 'Dark') if mode=='Automatic' else mode

class ThemeManager:
 def __init__(self,root,on_change=None):
  self.root=root;self.on_change=on_change;self.current=None;self.listeners=[]
  try:mode=json.loads(settings_path().read_text(encoding='utf-8')).get('theme','Automatic')
  except (OSError,ValueError):mode='Automatic'
  self.mode=tk.StringVar(master=root,value=mode if mode in THEMES else 'Automatic')
  self.mode.trace_add('write',self.changed);self.apply();root.after(500,self.poll)
 def changed(self,*args):
  atomic_json(settings_path(),{'theme':self.mode.get()});self.apply()
 def palette(self):return PALETTES[effective(self.mode.get())]
 def apply(self):
  mode=effective(self.mode.get());self.current=mode;p=PALETTES[mode];strong=mode=='Sunlight';font=('Segoe UI',12,'bold') if strong else ('Segoe UI',10)
  style=ttk.Style(self.root);style.configure('.',background=p['bg'],foreground=p['fg'],fieldbackground=p['entry'],font=font,borderwidth=3 if strong else 1)
  style.configure('Treeview',background=p['panel'],fieldbackground=p['panel'],foreground=p['fg'],rowheight=31 if strong else 26,font=font)
  style.configure('Treeview.Heading',font=font,background=p['bg'],foreground=p['fg'])
  style.map('Treeview',background=[('selected',p['select'])],foreground=[('selected',p['fg'])])
  style.map('TButton',background=[('active',p['select'])],foreground=[('disabled',p['muted'])])
  style.configure('TButton',padding=(10,7),borderwidth=3 if strong else 1)
  style.configure('TLabelframe.Label',foreground=p['accent'],font=font)
  style.configure('TEntry',foreground=p['fg'],fieldbackground=p['entry']);style.map('TCombobox',fieldbackground=[('readonly',p['entry'])],foreground=[('readonly',p['fg'])])
  self.restyle(self.root)
  for fn in tuple(self.listeners):fn(p,strong)
  if self.on_change:self.on_change(mode)
 def restyle(self,widget):
  p=self.palette();strong=self.current=='Sunlight';font=('Segoe UI',12,'bold') if strong else ('Segoe UI',10)
  try:
   if getattr(widget,'_engine_applied_theme',None)==self.current:
    for child in widget.winfo_children():self.restyle(child)
    return
   widget._engine_applied_theme=self.current
   if isinstance(widget,tk.Text):widget.configure(bg=p['entry'],fg=p['fg'],insertbackground=p['fg'],selectbackground=p['select'],font=font,highlightthickness=3 if strong else 1,highlightbackground=p['line'])
   elif isinstance(widget,tk.Canvas):widget.configure(bg=p['panel'],highlightthickness=2 if strong else 0,highlightbackground=p['line'])
   elif isinstance(widget,tk.Label):widget.configure(bg=p['bg'],fg=p['fg'],font=font)
   elif isinstance(widget,tk.Menu):widget.configure(bg=p['panel'],fg=p['fg'],activebackground=p['select'],activeforeground=p['fg'],font=font,borderwidth=3 if strong else 1)
   elif isinstance(widget,(tk.Frame,tk.Tk,tk.Toplevel)):widget.configure(bg=p['bg'])
   for child in widget.winfo_children():self.restyle(child)
  except tk.TclError:pass
 def poll(self):
  if not self.root.winfo_exists():return
  if self.current!=effective(self.mode.get()):self.apply()
  else:self.restyle(self.root)  # Includes new Inspector/dialog widgets.
  self.root.after(1000,self.poll)
 def selector(self,parent):
  ttk.Label(parent,text='Theme').pack(side='left',padx=(8,3))
  ttk.Combobox(parent,textvariable=self.mode,values=THEMES,state='readonly',width=12).pack(side='left')

def attach(root,on_change=None):
 manager=ThemeManager(root,on_change);root._engine_theme=manager;return manager

def manager(widget):
 root=widget
 while getattr(root,'master',None) is not None:root=root.master
 return getattr(root,'_engine_theme',None)
