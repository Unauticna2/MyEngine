"""One coordinate transform shared by UI drawing and pointer hit tests."""
import math
MODES=('fit','fill','stretch','match','width','height')

def normalized(value=None):
    value={} if value is None else value
    if not isinstance(value,dict):raise ValueError('UI scale settings must be an object')
    mode=value.get('mode','fit');match=float(value.get('match',.5))
    if mode not in MODES:raise ValueError('Unknown UI scale mode: '+str(mode))
    if not math.isfinite(match) or not 0<=match<=1:raise ValueError('UI width/height match must be 0..1')
    return {'mode':mode,'match':match}

def transform(canvas_width,canvas_height,width,height,settings):
    if min(canvas_width,canvas_height,width,height)<=0:raise ValueError('UI dimensions must be positive')
    sx=width/canvas_width;sy=height/canvas_height;mode=settings['mode']
    if mode!='stretch':
        scale=min(sx,sy) if mode=='fit' else max(sx,sy) if mode=='fill' else sx if mode=='width' else sy if mode=='height' else math.exp(math.log(sx)*(1-settings['match'])+math.log(sy)*settings['match'])
        sx=sy=scale
    return sx,sy,(width-canvas_width*sx)*.5,(height-canvas_height*sy)*.5

def clip_rect(canvas_width,canvas_height,width,height,t):
    sx,sy,ox,oy=t
    left=max(0,math.floor(ox));top=max(0,math.floor(oy))
    right=min(width,math.ceil(ox+canvas_width*sx));bottom=min(height,math.ceil(oy+canvas_height*sy))
    return left,height-bottom,max(0,right-left),max(0,bottom-top)

def ui_scale_dialog(editor):
    if not editor.can_edit():return
    import tkinter as tk
    from tkinter import ttk
    from engine_editor_tools import _commit
    from engine_ui_native import status
    document=editor.document;current=normalized(document.data.get('uiScale'))
    w=tk.Toplevel(editor.window);w.title('UI — масштаб и загрузка');w.geometry('620x410');w.transient(editor.window)
    p=ttk.Frame(w,padding=16);p.pack(fill='both',expand=True)
    modes={'Растянуть по ширине и высоте — без полос':'stretch',
           'Заполнить окно — обрезка краёв, без искажения':'fill',
           'Вписать целиком — возможны полосы':'fit',
           'По ширине':'width','По высоте':'height','Баланс ширины и высоты':'match'}
    mode=tk.StringVar(value=next(k for k,v in modes.items() if v==current['mode']))
    ttk.Label(p,text='Масштаб интерфейса в этой сцене:').pack(anchor='w',pady=6)
    ttk.Combobox(p,textvariable=mode,values=list(modes),state='readonly').pack(fill='x')
    match=tk.DoubleVar(value=current['match']);value=tk.StringVar()
    def label(*args):value.set(f'Ширина 0 ← {match.get():.2f} → 1 Высота')
    ttk.Label(p,textvariable=value).pack(anchor='w',pady=(12,0));label()
    ttk.Scale(p,from_=0,to=1,variable=match,command=label).pack(fill='x')
    ttk.Label(p,text='Ползунок действует в режиме «Баланс ширины и высоты».\nРастянуть: весь слайд виден, пропорции могут измениться.\nЗаполнить: пропорции сохранены, края могут обрезаться.\nНажатия кнопок учитывают тот же масштаб.',wraplength=580).pack(anchor='w',pady=12)
    ttk.Label(p,text='Обработка изображений: '+status(),wraplength=580).pack(anchor='w',pady=6)
    ttk.Label(p,text='Изображения готовятся в фоновых потоках; короткая полоска\nвнизу UI показывает загрузку. Повторный показ использует кеш.',wraplength=580).pack(anchor='w')
    def save():
        try:
            if not editor.can_edit() or editor.document is not document:raise ValueError('Открой настройки для текущей сцены заново.')
            _commit(editor,'uiScale',normalized({'mode':modes[mode.get()],'match':match.get()}));w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(p,text='Применить',command=save).pack(fill='x',pady=12)
