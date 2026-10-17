"""Attach generated UI handlers to scene objects without editing imported UI assets."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from engine_blueprints import Graph, generated_source
from engine_projects import inside
from engine_scene import SceneDocument
from engine_ui import load_document


def binding_key(ui, slide, element):
    return hashlib.sha256(json.dumps([ui,str(slide),str(element)]).encode('utf-8')).hexdigest()


def ui_element(data, slide, element):
    for s in data['slides']:
        if str(s['id'])==str(slide):
            for e in s['elements']:
                if str(e['id'])==str(element):return e
    raise ValueError('The selected UI slide/element no longer exists. Reopen UI Blueprints.')


def binding_record(document, root, ui, slide, element):
    root=Path(root).resolve();ui=inside(root,ui).relative_to(root).as_posix()
    ui_element(load_document(root/ui),slide,element)
    key=binding_key(ui,slide,element)
    old=document.data.get('uiBlueprints',{}).get(key)
    if old:return deepcopy(old)
    stem='scripts/ui/button_'+uuid.uuid4().hex
    return {'ui':ui,'slide':str(slide),'element':str(element),
            'graph':stem+'.blueprint.json','script':stem+'.py'}


def click_graph(slide, element, action='UIVisible'):
    from engine_blueprints import SPECS
    if action not in ('UIVisible','UINextSlide','UIShowSlide','LoadScene','Print'):
        raise ValueError('Unknown UI action template')
    return {'format':1,'nodes':[
        {'id':'1','type':'UIClick','x':50,'y':70,'params':{'slide':str(slide),'element':str(element)}},
        {'id':'2','type':action,'x':360,'y':70,'params':deepcopy(SPECS[action][2])}],
        'links':[['1','next','2','in']]}


def replace_bytes(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def apply_binding(document, root, record, graph_data):
    root=Path(root).resolve();record=deepcopy(record)
    graph_data=deepcopy(graph_data);graph_data['ui']=record['ui']
    ui=inside(root,record['ui']);catalog=load_document(ui)
    ui_element(catalog,record['slide'],record['element'])
    if document.data.get('ui')!=record['ui']:raise ValueError('The scene UI has changed. Reopen UI Blueprints.')
    graph=Graph(graph_data);graph.compile()
    if [target for _,target in graph.ui_events]!=[(record['slide'],record['element'])]:
        raise ValueError('Keep one UI Click for the selected button. Configure another button from UI Blueprints.')
    slides={str(s['id']) for s in catalog['slides']}
    for nid,node in graph.nodes.items():
        if nid not in graph.used:continue
        kind=node['type'];params=node['params']
        if kind in ('UIShowSlide','UISlideEnabled') and str(params['slide']) not in slides:
            raise ValueError('Unknown UI slide: '+str(params['slide']))
        if kind=='UIElementEnabled':ui_element(catalog,params['slide'],params['element'])
        if kind=='LoadScene':SceneDocument.load(inside(root,str(params['path'])))
    py=inside(root,record['script']);bp=inside(root,record['graph'])
    if py.suffix!='.py' or not bp.name.endswith('.blueprint.json'):
        raise ValueError('UI Blueprint files must use .py and .blueprint.json')
    text,unused=generated_source(graph_data,py.read_text(encoding='utf-8-sig') if py.exists() else None)
    candidate=SceneDocument(document.data)
    index=None
    for i,scripts in enumerate(candidate.data['scripts']):
        if record['script'] in ([scripts] if isinstance(scripts,str) else scripts or []):index=i;break
    if index is None:
        name=candidate.unique_name('UIController');index=candidate.add()
        candidate.data['names'][index]=name;candidate.data['visible'][index]=False
        candidate.data['scripts'][index]=[record['script']]
    record['object']=candidate.data['names'][index]
    candidate.data.setdefault('uiBlueprints',{})[binding_key(record['ui'],record['slide'],record['element'])]=record
    candidate.validate()
    outputs=[(bp,(json.dumps(graph_data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')),
             (py,text.encode('utf-8'))]
    before={p:p.read_bytes() if p.exists() else None for p,_ in outputs};written=[]
    try:
        for path,data in outputs:replace_bytes(path,data);written.append(path)
    except BaseException:
        for path in reversed(written):
            if before[path] is None:path.unlink(missing_ok=True)
            else:replace_bytes(path,before[path])
        raise
    document.checkpoint();document.data=candidate.data
    return record,unused
