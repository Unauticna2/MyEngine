"""Visible Collider controls; advanced shape/layer data remains lossless."""
from copy import deepcopy
import json
import tkinter as tk
from tkinter import ttk
from engine_physics import Collider


FLAGS={'type','kind','enabled','isTrigger','is_trigger'}


def collider_data(value):
    """Accept every legacy scene representation while preserving extra settings."""
    parsed=Collider.from_json(value)
    if parsed is None:return None
    data=deepcopy(value) if isinstance(value,dict) else {}
    data.pop('kind',None);data.pop('is_trigger',None)
    data.update(type=parsed.kind,enabled=parsed.enabled,isTrigger=parsed.is_trigger)
    return data


class ColliderInspector:
    def __init__(self,editor,parent,value):
        self.editor=editor
        self.frame=ttk.Labelframe(parent,text='Collider',padding=5)
        self.frame.pack(fill='x',pady=6)
        row=ttk.Frame(self.frame);row.pack(fill='x')
        self.enabled=tk.BooleanVar(master=parent)
        self.trigger=tk.BooleanVar(master=parent)
        self.kind=tk.StringVar(master=parent)
        self.enabled_check=ttk.Checkbutton(row,text='Enabled',variable=self.enabled,command=self.commit)
        self.enabled_check.pack(side='left',padx=(0,12))
        self.trigger_check=ttk.Checkbutton(row,text='Is Trigger',variable=self.trigger,command=self.commit)
        self.trigger_check.pack(side='left')
        self.type_box=ttk.Combobox(self.frame,textvariable=self.kind,values=('box','mesh','voxel'),state='readonly')
        self.type_box.pack(fill='x',pady=4);self.type_box.bind('<<ComboboxSelected>>',lambda event:self.commit())
        self.help=ttk.Label(self.frame,wraplength=285);self.help.pack(anchor='w')
        self.advanced=tk.BooleanVar(master=parent,value=False)
        self.advanced_check=ttk.Checkbutton(self.frame,text='Advanced shape / layers (JSON)',variable=self.advanced,command=self.toggle_advanced)
        self.advanced_check.pack(anchor='w',pady=(5,0))
        self.extra=tk.Text(self.frame,height=5,wrap='word')
        self.set_value(value)

    def set_value(self,value):
        self.current=collider_data(value);present=self.current is not None;data=self.current or {}
        self.kind.set(data.get('type','box'));self.enabled.set(data.get('enabled',True));self.trigger.set(data.get('isTrigger',False))
        self.extra.delete('1.0','end')
        self.extra.insert('1.0',json.dumps({k:v for k,v in data.items() if k not in FLAGS},ensure_ascii=False,indent=2))
        for widget in (self.enabled_check,self.trigger_check,self.advanced_check):widget.state(['!disabled'] if present else ['disabled'])
        self.type_box.configure(state='readonly' if present else 'disabled')
        self.help.configure(text='Is Trigger: pass through + OnTrigger events.\nUnchecked: solid + OnCollision events.' if present else
                            'No Collider. Right-click → Add component\n→ Box / Mesh / Voxel Collider.')
        if not present:self.advanced.set(False)
        self.toggle_advanced()

    def value(self):
        if self.current is None:return None
        extra=json.loads(self.extra.get('1.0','end'))
        if not isinstance(extra,dict):raise ValueError('Collider advanced settings must be a JSON object')
        if FLAGS.intersection(extra):raise ValueError('Use the Collider controls for Type, Enabled and Is Trigger')
        data={**extra,'type':self.kind.get(),'enabled':self.enabled.get(),'isTrigger':self.trigger.get()}
        return collider_data(data)

    def toggle_advanced(self):
        if self.advanced.get():self.extra.pack(fill='x',pady=4)
        else:self.extra.pack_forget()

    def commit(self):
        try:
            data=self.value()
            if not self.editor.commit_collider(data):
                self.set_value(self.current);return
            self.current=deepcopy(data)
        except Exception as ex:
            self.set_value(self.current);self.editor.error(ex)
