"""Inspector fields for an optional Light component; no hand-written JSON required."""
import tkinter as tk
from tkinter import ttk
from engine_lighting import light_settings


class LightInspector:
    def __init__(self, editor, parent, value):
        frame=ttk.Labelframe(parent,text='Light',padding=5);frame.pack(fill='x',pady=5)
        self.present=tk.BooleanVar(value=value is not None)
        ttk.Checkbutton(frame,text='Light component',variable=self.present).pack(anchor='w')
        d=light_settings(value or {});self.variables={}
        for key,label,choices in [('type','Type',('directional','point','spot')),
                                  ('colorMode','Color mode',('rgb','hsv','temperature'))]:
            ttk.Label(frame,text=label).pack(anchor='w')
            variable=tk.StringVar(value=d[key]);self.variables[key]=variable
            ttk.Combobox(frame,textvariable=variable,values=choices,state='readonly').pack(fill='x')
        for key,label in [('enabled','Enabled'),('shadows','Directional shadows')]:
            variable=tk.BooleanVar(value=d[key]);self.variables[key]=variable
            ttk.Checkbutton(frame,text=label,variable=variable).pack(anchor='w')
        for key,label in [('intensity','Intensity (negative subtracts light)'),('range','Range (Point / Spot)'),
                          ('innerAngle','Spot inner angle °'),('outerAngle','Spot outer angle °'),('temperature','Temperature 1000..40000 K')]:
            self.variables[key]=editor.field(frame,label,d[key])
        for key,label,axes in [('color','Linear RGB (signed, HDR > 1)','RGB'),('hsv','HSV (H degrees, S 0..1, V >= 0)','HSV')]:
            ttk.Label(frame,text=label).pack(anchor='w',pady=(6,1));row=ttk.Frame(frame);row.pack(fill='x')
            self.variables[key]=[]
            for axis,value in zip(axes,d[key]):
                ttk.Label(row,text=axis).pack(side='left');variable=tk.StringVar(value=str(value))
                ttk.Entry(row,textvariable=variable,width=6).pack(side='left',fill='x',expand=True)
                self.variables[key].append(variable)
        ttk.Label(frame,text='Position moves Point / Spot. Rotation aims light along local +Z.\nUp to 16 active lights. One Directional casts shadows.',wraplength=270).pack(anchor='w',pady=6)

    def value(self):
        if not self.present.get():return None
        result={}
        for key,variable in self.variables.items():
            if isinstance(variable,list):result[key]=[float(v.get()) for v in variable]
            elif key in ('type','colorMode','enabled','shadows'):result[key]=variable.get()
            else:result[key]=float(variable.get())
        return light_settings(result)
