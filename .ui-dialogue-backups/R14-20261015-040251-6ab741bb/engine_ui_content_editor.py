"""Visible editor controls for anchors, grouped dialogue fields and videos."""
from pathlib import Path
from copy import deepcopy
import json,hashlib,queue,re,shutil,threading
import tkinter as tk
from tkinter import ttk,filedialog
from engine_projects import inside
from engine_scene import atomic_json
from engine_ui import load_document,validate
from engine_ui_layout import anchors
from engine_ui_text import style
from engine_ui_content import dialogue
from engine_ui_media import video_settings


def dialogue_lines(text):
    """Blank lines separate entries, including CRLF and whitespace-only lines."""
    text=text.replace('\r\n','\n').replace('\r','\n')
    return [part.strip() for part in re.split(r'\n[ \t]*\n(?:[ \t]*\n)*',text) if part.strip()]


def dialogue_feedback(text,enabled):
    """Same validation as Save, available before the user presses the button."""
    lines=dialogue_lines(text)
    longest=max((len(line) for line in lines),default=0)
    counts=f'Реплик: {len(lines)}/1000 · Самая длинная: {longest}/4096 символов.'
    if not enabled:return counts+' Новелла выключена.',False
    try:dialogue({'lines':lines})
    except ValueError as ex:return counts+'\n'+str(ex),True
    return counts,False


def apply_element(path,sid,eid,changes):
    data=load_document(path)
    slide=next(s for s in data['slides'] if str(s['id'])==str(sid))
    element=next(e for e in slide['elements'] if str(e['id'])==str(eid))
    for key,value in changes.items():
        if key not in ('anchors','dialogue','textStyle','video'):raise ValueError('Unsupported UI setting')
        element[key]=deepcopy(value);element.setdefault('_editor',{})[key]=deepcopy(value)
    validate(data);atomic_json(path,data)
    return data


def content_dialog(editor):
    if not editor.can_edit():return
    try:
        document=editor.document;ui=document.data.get('ui')
        if not ui:raise ValueError('Сначала подключи интерфейс PowerPoint.')
        path=inside(editor.path_root,ui);data=load_document(path)
    except Exception as ex:editor.error(ex);return
    window=tk.Toplevel(editor.window);window.title('UI R14 — привязки, новелла, видео');window.geometry('800x760');window.minsize(700,620)
    outer=ttk.Frame(window,padding=12);outer.pack(fill='both',expand=True)
    slides={str(s['id']):s for s in data['slides']};sid=tk.StringVar(value=next(iter(slides),''));eid=tk.StringVar()
    row=ttk.Frame(outer);row.pack(fill='x')
    ttk.Label(row,text='Слайд').pack(side='left');sb=ttk.Combobox(row,textvariable=sid,values=list(slides),state='readonly',width=10);sb.pack(side='left',padx=6)
    ttk.Label(row,text='Элемент / группа').pack(side='left');eb=ttk.Combobox(row,textvariable=eid,state='readonly');eb.pack(side='left',fill='x',expand=True,padx=6)
    description=tk.StringVar();ttk.Label(outer,textvariable=description,wraplength=740).pack(anchor='w',pady=8)
    book=ttk.Notebook(outer);book.pack(fill='both',expand=True)
    layout=ttk.Frame(book,padding=14);novel=ttk.Frame(book,padding=14);video=ttk.Frame(book,padding=14)
    book.add(layout,text='Привязки');book.add(novel,text='Визуальная новелла');book.add(video,text='Видео')
    horizontal={'Как на слайде':'canvas','Слева':'left','По центру':'center','Справа':'right','Растянуть слева направо':'stretch'}
    vertical={'Как на слайде':'canvas','Сверху':'top','По центру':'center','Снизу':'bottom','Растянуть сверху вниз':'stretch'}
    hv=tk.StringVar();vv=tk.StringVar()
    ttk.Label(layout,text='Горизонтальная привязка к окну').pack(anchor='w');ttk.Combobox(layout,textvariable=hv,values=list(horizontal),state='readonly').pack(fill='x',pady=6)
    ttk.Label(layout,text='Вертикальная привязка к окну').pack(anchor='w');ttk.Combobox(layout,textvariable=vv,values=list(vertical),state='readonly').pack(fill='x',pady=6)
    ttk.Label(layout,text='Размер окна меняется: отступ от выбранного края сохраняется в единицах исходного слайда. Растяжение сохраняет оба отступа. Масштаб UI задаётся отдельно.\n\nДля панели реплик обычно удобно: растянуть по горизонтали, привязать снизу.',wraplength=680).pack(anchor='w',pady=14)
    enabled=tk.BooleanVar();advance=tk.BooleanVar(value=True);loop=tk.BooleanVar()
    ttk.Checkbutton(novel,text='Использовать как поле новеллы',variable=enabled).pack(anchor='w')
    ttk.Label(novel,text='Реплики разделяются пустой строкой. Обычный перенос остаётся внутри реплики.').pack(anchor='w',pady=4)
    text=tk.Text(novel,height=9,wrap='word',undo=True);text.pack(fill='both',expand=True)
    feedback=tk.StringVar();feedback_label=ttk.Label(novel,textvariable=feedback,wraplength=650)
    feedback_label.pack(anchor='w',fill='x',pady=4)
    normal_feedback_color=ttk.Style(window).lookup('TLabel','foreground') or '#808080'
    def update_dialogue_feedback(*unused):
        message,invalid=dialogue_feedback(text.get('1.0','end-1c'),enabled.get())
        feedback.set(message);feedback_label.configure(foreground='#e05050' if invalid else normal_feedback_color)
    def text_modified(event=None):
        if text.edit_modified():
            text.edit_modified(False);update_dialogue_feedback()
    text.bind('<<Modified>>',text_modified)
    enabled.trace_add('write',update_dialogue_feedback)
    ttk.Checkbutton(novel,text='Следующая реплика при нажатии на эту группу',variable=advance).pack(anchor='w',pady=3)
    ttk.Checkbutton(novel,text='Повторять с первой реплики',variable=loop).pack(anchor='w')
    row=ttk.Frame(novel);row.pack(fill='x',pady=7)
    font=tk.StringVar();size=tk.StringVar();color=tk.StringVar();align=tk.StringVar();bold=tk.BooleanVar()
    for label,var,width in [('Шрифт',font,16),('Размер',size,5),('Цвет #RRGGBB',color,9)]:
        ttk.Label(row,text=label).pack(side='left',padx=3);ttk.Entry(row,textvariable=var,width=width).pack(side='left')
    ttk.Combobox(novel,textvariable=align,values=['left','center','right'],state='readonly',width=12).pack(anchor='w')
    ttk.Checkbutton(novel,text='Жирный',variable=bold).pack(anchor='w')
    ttk.Label(novel,text='В PowerPoint сгруппируй рамку и текст. Импорт сохраняет рисунок рамки и заменяет самый большой текстовый блок группы. Для отдельных кнопок также есть UI dialogue next / reset и UI set text.',wraplength=680).pack(anchor='w',pady=5)
    types={'Нет видео':'none','Видео из файла PowerPoint / проекта':'file','Ссылка YouTube — открыть в браузере':'youtube'}
    kind=tk.StringVar();source=tk.StringVar();auto=tk.BooleanVar();repeat=tk.BooleanVar();volume=tk.StringVar(value='1');fit=tk.StringVar(value='fit')
    ttk.Combobox(video,textvariable=kind,values=list(types),state='readonly').pack(fill='x',pady=5)
    ttk.Label(video,text='Путь внутри папки UI или ссылка на YouTube:').pack(anchor='w');ttk.Entry(video,textvariable=source).pack(fill='x',pady=6)
    busy=False;messages=queue.Queue()
    def browse():
        nonlocal busy
        if busy:return
        filename=filedialog.askopenfilename(parent=window,title='Добавить видео',filetypes=[('Video','*.mp4 *.m4v *.wmv *.avi *.mov *.webm'),('All','*.*')])
        if not filename:return
        chosen_sid=sid.get();chosen_eid=eid.get();busy=True;status.set('Копирую видео в проект…')
        def copy():
            try:
                origin=Path(filename);ext=origin.suffix.lower()
                if ext not in ('.mp4','.m4v','.wmv','.avi','.mov','.webm','.mpg','.mpeg'):raise ValueError('Неподдерживаемое расширение видео')
                if origin.stat().st_size>1024**3:raise ValueError('Лимит: 1 ГиБ на видео')
                digest=hashlib.sha256()
                with origin.open('rb') as f:
                    for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
                rel='media/'+digest.hexdigest()[:24]+ext;target=path.parent/rel;target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():
                    tmp=target.with_suffix(ext+'.tmp');shutil.copyfile(origin,tmp);tmp.replace(target)
                messages.put((True,rel,chosen_sid,chosen_eid))
            except Exception as ex:messages.put((False,str(ex),chosen_sid,chosen_eid))
        threading.Thread(target=copy,name='video-import',daemon=True).start()
    ttk.Button(video,text='Выбрать видео и скопировать в проект…',command=browse).pack(fill='x',pady=5)
    ttk.Checkbutton(video,text='Автозапуск при входе на слайд (только локальное видео)',variable=auto).pack(anchor='w',pady=3)
    ttk.Checkbutton(video,text='Повторять видео',variable=repeat).pack(anchor='w')
    row=ttk.Frame(video);row.pack(fill='x',pady=6)
    ttk.Label(row,text='Громкость 0..1').pack(side='left');ttk.Entry(row,textvariable=volume,width=7).pack(side='left',padx=5)
    ttk.Combobox(row,textvariable=fit,values=['fit','fill','stretch'],state='readonly',width=10).pack(side='left')
    ttk.Label(video,text='Встроенный файл извлекается из PPTX при обновлении. Без автозапуска: нажать на постер или вызвать UI play video. Один ролик одновременно.\n\nWindows: видео со звуком внутри окна, без поворота. Повторный клик ставит на паузу. YouTube открывается обычной ссылкой в браузере. Видео отображается поверх остальных UI-элементов; переход скрывает его.',wraplength=680).pack(anchor='w',pady=12)
    status=tk.StringVar();ttk.Label(outer,textvariable=status,wraplength=740).pack(anchor='w',pady=5)
    current={}
    def load_element(event=None):
        current.clear();s=slides.get(sid.get());e=next((e for e in s['elements'] if str(e['id'])==eid.get()),None) if s else None
        if e is None:return
        current.update(deepcopy(e));description.set(str(e.get('name',e['id']))+(' · группа' if e.get('group') else ''))
        a=anchors(e.get('anchors'));hv.set(next(k for k,v in horizontal.items() if v==a['horizontal']));vv.set(next(k for k,v in vertical.items() if v==a['vertical']))
        d=e.get('dialogue') or {};enabled.set(bool(d));advance.set(d.get('clickToAdvance',True));loop.set(d.get('loop',False))
        source_text=e.get('textSlot',{}).get('sourceText','').replace('\r\n','\n').replace('\r','\n')
        text.delete('1.0','end');text.insert('1.0','\n\n'.join(d.get('lines',[])) or source_text)
        update_dialogue_feedback()
        st=style(e.get('textStyle') or e.get('textSlot',{}).get('style'));font.set(st['font']);size.set(str(st['size']));color.set('#'+''.join(f'{round(v*255):02x}' for v in st['color'][:3]));align.set(st['align']);bold.set(st['bold'])
        v=e.get('video') or {};kind.set(next(k for k,val in types.items() if val==v.get('kind','none')));source.set(v.get('source',''));auto.set(v.get('autoplay',False));repeat.set(v.get('loop',False));volume.set(str(v.get('volume',1)));fit.set(v.get('fit','fit'))
        status.set('Нажми «Сохранить элемент» перед выбором другого.')
    def load_slide(event=None):
        s=slides.get(sid.get());ids=[str(e['id']) for e in s['elements']] if s else [];eb.configure(values=ids);eid.set(ids[0] if ids else '');load_element()
    def save():
        nonlocal data,slides
        try:
            if busy:raise ValueError('Подожди окончания копирования видео.')
            if not editor.can_edit() or editor.document is not document or document.data.get('ui')!=ui:raise ValueError('Открой окно заново для текущего UI.')
            if not current:raise ValueError('Выбери элемент.')
            changes={'anchors':anchors({'horizontal':horizontal[hv.get()],'vertical':vertical[vv.get()]})}
            d=None
            if enabled.get():
                if not current.get('textSlot'):raise ValueError('У элемента нет текстового блока. Добавь текст в PowerPoint (для группы — внутрь неё), затем нажми «Обновить текущий UI из PowerPoint».')
                lines=dialogue_lines(text.get('1.0','end-1c'))
                d=dialogue({'lines':lines,'clickToAdvance':advance.get(),'loop':loop.get()})
            changes['dialogue']=d
            rgb=color.get().strip().lstrip('#')
            if len(rgb)!=6:raise ValueError('Цвет: #RRGGBB')
            changes['textStyle']=style({'font':font.get(),'size':float(size.get()),'color':[int(rgb[i:i+2],16)/255 for i in (0,2,4)]+[1],'align':align.get(),'bold':bold.get()})
            v=None;k=types[kind.get()]
            if k!='none':
                v=video_settings({'kind':k,'source':source.get().strip(),'autoplay':auto.get(),'loop':repeat.get(),'volume':float(volume.get()),'fit':fit.get()})
                if k=='file':
                    candidate=(path.parent/v['source']).resolve();candidate.relative_to(path.parent.resolve())
                    if not candidate.is_file():raise FileNotFoundError(candidate)
                    if abs(float(current.get('rotation',0)))%360>.01:raise ValueError('Для видео установи поворот фигуры 0° в PowerPoint.')
                if d:raise ValueError('Для видео и реплик используй разные элементы.')
            # Preserve fresh embedded video paths during reimport unless edited here.
            if v!=current.get('video'):changes['video']=v
            data=apply_element(path,sid.get(),eid.get(),changes);slides={str(s['id']):s for s in data['slides']}
            editor.reload();editor.refresh_project();load_element();status.set('Элемент сохранён. Проверь в Play и при изменении размера окна.')
        except Exception as ex:editor.error(ex)
    buttons=ttk.Frame(outer);buttons.pack(fill='x',pady=4)
    ttk.Button(buttons,text='Сохранить элемент',command=save).pack(side='left',fill='x',expand=True)
    def blueprints():
        from engine_ui_blueprint_ui import ui_blueprints_dialog
        ui_blueprints_dialog(editor,initial_target=(sid.get(),eid.get()))
    ttk.Button(buttons,text='Привязать Blueprint…',command=blueprints).pack(side='left',padx=6)
    def poll():
        nonlocal busy
        if not window.winfo_exists():return
        try:
            while True:
                ok,value,ss,ee=messages.get_nowait();busy=False
                if ok:
                    if (ss,ee)==(sid.get(),eid.get()):kind.set(next(k for k,v in types.items() if v=='file'));source.set(value);status.set('Видео скопировано. Нажми «Сохранить элемент».')
                    else:status.set('Видео скопировано: '+value+'. Выбери нужный элемент и укажи этот путь.')
                else:editor.error(value)
        except queue.Empty:pass
        window.after(100,poll)
    sb.bind('<<ComboboxSelected>>',load_slide);eb.bind('<<ComboboxSelected>>',load_element);load_slide();window.after(100,poll)


def payments_dialog(editor):
    if not editor.can_edit():return
    from engine_transactions import load_settings,settings
    root=editor.path_root
    try:current=load_settings(root)
    except Exception as ex:editor.error(ex);return
    w=tk.Toplevel(editor.window);w.title('Донаты / транзакции — R12');w.geometry('700x450')
    p=ttk.Frame(w,padding=16);p.pack(fill='both',expand=True)
    link=tk.StringVar(value=current['donationUrl']);api=tk.StringVar(value=current['checkoutApi'])
    ttk.Label(p,text='Платёжная ссылка для поддержки разработчика (https://):').pack(anchor='w');ttk.Entry(p,textvariable=link).pack(fill='x',pady=6)
    ttk.Label(p,text='Blueprint: UI Click → Open donation. Игрок сам подтверждает платёж на странице сервиса.',wraplength=650).pack(anchor='w',pady=5)
    ttk.Separator(p).pack(fill='x',pady=12)
    ttk.Label(p,text='Необязательно: адрес своего сервера транзакций (https://):').pack(anchor='w');ttk.Entry(p,textvariable=api).pack(fill='x',pady=6)
    ttk.Label(p,text='Blueprint: Transaction start (product, key) → далее статус проверяется узлом Transaction is в Update.\nСервер создаёт оплату и подтверждает её через API платёжного сервиса. Контракт — TRANSACTIONS_R12.txt.\n\nБез сервера доступны донаты по ссылке. Нажатие и возврат браузера не подтверждают оплату. Секретный ключ магазина в игру не помещай.',wraplength=650).pack(anchor='w',pady=10)
    def save():
        try:
            if not editor.can_edit() or editor.path_root!=root:raise ValueError('Проект изменился. Открой окно заново.')
            value=settings({'donationUrl':link.get(),'checkoutApi':api.get()});atomic_json(root/'payments.json',value);editor.refresh_project();w.destroy()
        except Exception as ex:editor.error(ex)
    ttk.Button(p,text='Сохранить настройки проекта',command=save).pack(fill='x',pady=10)
