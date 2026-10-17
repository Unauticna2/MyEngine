"""Build and optional release upload in a worker; Tk widgets stay on the UI thread."""
from pathlib import Path
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from engine_projects import project_scenes,read_project
from engine_platform_build import export_target,TARGETS,PublicationError
from engine_releases import load_settings,save_settings,publish_build,gh_executable
from engine_version import new_build_id

def show_build(parent,engine_root,project_root,scene=None):
    root=Path(project_root).resolve();window=tk.Toplevel(parent);window.title('Сборка игры');window.geometry('760x700')
    window.minsize(700,650)
    frame=ttk.Frame(window,padding=14);frame.pack(fill='both',expand=True)
    tabs=ttk.Notebook(frame);tabs.pack(fill='both',expand=True)
    general=ttk.Frame(tabs,padding=12);files=ttk.Frame(tabs,padding=12);release=ttk.Frame(tabs,padding=12)
    tabs.add(general,text='Игра');tabs.add(files,text='Файлы');tabs.add(release,text='GitHub / версии')
    try:name=read_project(root)['name']
    except (OSError,ValueError,KeyError):name='MyGame'
    def field(panel,label,value):
        ttk.Label(panel,text=label).pack(anchor='w',pady=(7,2));var=tk.StringVar(value=value)
        ttk.Entry(panel,textvariable=var).pack(fill='x');return var
    ttk.Label(general,text='Платформа').pack(anchor='w')
    target=tk.StringVar(value=TARGETS[0]);ttk.Combobox(general,textvariable=target,values=TARGETS,state='readonly').pack(fill='x')
    game=field(general,'Имя игры и EXE',name)
    scenes=project_scenes(root);ttk.Label(general,text='Начальная сцена').pack(anchor='w',pady=(7,2))
    selected=tk.StringVar(value=scene or (scenes[0] if scenes else ''))
    ttk.Combobox(general,textvariable=selected,values=scenes,state='readonly').pack(fill='x')
    out=field(general,'Папка для сборок',str(root/'Builds'))
    def browse():
        p=filedialog.askdirectory(parent=window,initialdir=root)
        if p:out.set(p)
    ttk.Button(general,text='Выбрать папку…',command=browse).pack(anchor='e',pady=3)
    unique=tk.BooleanVar(value=True)
    ttk.Checkbutton(general,text='Каждая сборка в отдельной папке с датой и ID',variable=unique).pack(anchor='w',pady=5)
    packages=tk.BooleanVar(value=False)
    ttk.Checkbutton(general,text='Включить установленные site-packages для Python-скриптов',variable=packages).pack(anchor='w')
    from engine_access import unlock_all,set_unlock_all
    free=tk.BooleanVar(value=unlock_all(root))
    ttk.Checkbutton(general,text='Разблокировать весь игровой контент (донат добровольный)',variable=free).pack(anchor='w',pady=8)
    ttk.Label(general,text='Сохраняется в donation_access.json → unlockAll. Игрок также может изменить этот файл.\nWindows: EXE + Data. Linux: экспериментальный запуск с системным Python / SDL2.\nAndroid и WebGL пока требуют переноса runtime.',wraplength=650).pack(anchor='w',pady=8)
    from engine_build_options import load,save,normalized
    rules=load(root);ext=field(files,'Исключить расширения (через запятую)',', '.join(rules['excludeExtensions']))
    ttk.Label(files,text='Исключить пути / шаблоны (по одному на строку)').pack(anchor='w',pady=(7,2))
    excluded_paths=tk.Text(files,height=10);excluded_paths.pack(fill='both',expand=True);excluded_paths.insert('1.0','\n'.join(rules['excludeFiles']))
    def choose_exclusion():
        p=filedialog.askopenfilename(parent=window,initialdir=root,title='Исключить файл из сборки')
        if p:
            try:rel=Path(p).resolve().relative_to(root).as_posix()
            except ValueError:messagebox.showerror('Файлы','Выбери файл внутри проекта.',parent=window);return
            excluded_paths.insert('end','\n'+rel)
    ttk.Button(files,text='Исключить файл…',command=choose_exclusion).pack(anchor='w',pady=5)
    ttk.Label(files,text='Исключение нужной скрипту библиотеки может нарушить его работу.',wraplength=620).pack(anchor='w')
    try:options=load_settings(root)
    except Exception as ex:messagebox.showerror('GitHub settings',str(ex),parent=window);options={'version':'0.1.0','repository':'','publishAfterBuild':False,'autoIncrementVersion':True}
    version_snapshot=options['version']
    version=field(release,'Последняя версия / начальный номер',options['version'])
    automatic=tk.BooleanVar(value=options['autoIncrementVersion'])
    ttk.Checkbutton(release,text='Повышать последнюю часть версии после успешной сборки (0.1.0 → 0.1.1)',variable=automatic).pack(anchor='w',pady=6)
    repo=field(release,'GitHub-репозиторий: автор/репозиторий',options['repository'])
    publish=tk.BooleanVar(value=options['publishAfterBuild'])
    ttk.Checkbutton(release,text='Разрешаю публиковать готовую игру после каждой сборки',variable=publish).pack(anchor='w',pady=14)
    ttk.Label(release,text='В GitHub Releases отправится ZIP всей готовой игры. В публичном репозитории его сможет скачать любой. Каждый билд получает отдельный тег; существующие релизы не заменяются.\n\nДля загрузки: установи GitHub CLI, войди в аккаунт и заранее создай репозиторий. Для восстановления из меню игры нужны публичные релизы. Git не нужен для скачивания.\n\nГалочка запоминается в проекте. Если её выключить, следующие сборки останутся локальными.',wraplength=650).pack(anchor='w',pady=8)
    buttons=ttk.Frame(release);buttons.pack(fill='x',pady=8)
    def install():
        import webbrowser
        webbrowser.open('https://cli.github.com/')
    def login():
        try:subprocess.Popen([gh_executable(),'auth','login','--hostname','github.com','--web'],creationflags=0x10 if os.name=='nt' else 0)
        except Exception as ex:messagebox.showerror('GitHub',str(ex),parent=window)
    ttk.Button(buttons,text='Установить GitHub CLI',command=install).pack(side='left',padx=(0,8))
    ttk.Button(buttons,text='Войти в GitHub',command=login).pack(side='left')
    status=tk.StringVar(value='Готово');ttk.Label(frame,textvariable=status,wraplength=690).pack(fill='x',pady=(10,2))
    progress=ttk.Progressbar(frame,mode='indeterminate');progress.pack(fill='x',pady=6)
    messages=queue.Queue();busy=False;last_build=None;last_options=None
    def collect_options():
        from engine_releases import settings
        result=settings({'version':version.get(),'repository':repo.get(),'publishAfterBuild':publish.get(),'autoIncrementVersion':automatic.get()})
        set_unlock_all(root,free.get())
        return result
    def begin_work():
        nonlocal busy
        busy=True;button.configure(state='disabled');retry.configure(state='disabled');progress.start(15)
    def build():
        nonlocal last_build,last_options
        if busy:return
        try:
            rules=normalized([x.strip() for x in ext.get().split(',') if x.strip()],[x.strip() for x in excluded_paths.get('1.0','end').splitlines() if x.strip()]);save(root,rules)
            last_options=collect_options()
            parent_folder=Path(out.get())
            if unique.get():parent_folder=parent_folder/new_build_id()
            kwargs=dict(exclude_extensions=rules['excludeExtensions'],exclude_files=rules['excludeFiles'],name=game.get(),scene=selected.get(),output_parent=parent_folder,include_packages=packages.get(),release_options=last_options,expected_version=version_snapshot)
        except Exception as ex:messagebox.showerror('Настройки сборки',str(ex),parent=window);return
        selected_target=target.get();last_build=None;begin_work()
        def worker():
            try:
                result=export_target(selected_target,engine_root,root,progress=lambda x:messages.put(('progress',x)),**kwargs)
                messages.put(('done',str(result)))
            except PublicationError as ex:messages.put(('publication_error',(str(ex.build),str(ex),ex.retry_publication)))
            except Exception as ex:messages.put(('error',str(ex)))
        threading.Thread(target=worker,name='player-build',daemon=False).start()
    def retry_publish():
        if busy or last_build is None:return
        # A retry uses the same authorized build/repository; it does not silently retarget a release.
        begin_work();path=last_build;options=dict(last_options)
        def worker():
            try:
                url=publish_build(path,options,lambda x:messages.put(('progress',x)))
                messages.put(('published',str(url)))
            except Exception as ex:messages.put(('publication_error',(str(path),str(ex),True)))
        threading.Thread(target=worker,name='player-build',daemon=False).start()
    def poll():
        nonlocal busy,last_build,version_snapshot
        if not window.winfo_exists():return
        while not messages.empty():
            kind,text=messages.get()
            if kind=='progress':status.set(text);continue
            busy=False;button.configure(state='normal');progress.stop()
            if kind in ('done','publication_error'):
                try:
                    import json
                    built_path=Path(text[0] if kind=='publication_error' else text)
                    built_version=json.loads((built_path/'Data/build.json').read_text(encoding='utf-8-sig'))['version']
                    version.set(built_version);last_options['version']=built_version;version_snapshot=built_version
                except (OSError,ValueError,KeyError):pass
            if kind=='publication_error':
                last_build=Path(text[0]);status.set('Сборка готова; завершающий шаг не выполнен.');retry.configure(state='normal' if text[2] else 'disabled')
                messagebox.showwarning('GitHub',text[1]+('\n\nМожно повторить публикацию без пересборки и без повышения версии.' if text[2] else '\nПроверь права записи в папку проекта.'),parent=window)
            elif kind=='error':status.set('Ошибка сборки');messagebox.showerror('Сборка',text,parent=window)
            else:status.set(text);messagebox.showinfo('Готово',text+ ('\n\nРаспространяй всю папку игры.' if kind=='done' else ''),parent=window)
        window.after(100,poll)
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=8)
    button=ttk.Button(actions,text='Собрать игру',command=build);button.pack(side='left',fill='x',expand=True)
    retry=ttk.Button(actions,text='Повторить публикацию',command=retry_publish,state='disabled');retry.pack(side='left',padx=8)
    def close():
        if busy:status.set('Дождись завершения сборки / загрузки.');return
        try:collect_options()
        except Exception as ex:messagebox.showerror('Настройки',str(ex),parent=window);return
        window.destroy()
    window.protocol('WM_DELETE_WINDOW',close);window.after(100,poll)
    return window
