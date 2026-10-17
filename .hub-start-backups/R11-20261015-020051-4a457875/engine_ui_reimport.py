"""Preserve imported identity and engine overrides while refreshing a UI asset."""
from copy import deepcopy
import re
from engine_ui import validate


def shape_source(element):
    if element.get('sourceShapeId') is not None:return str(element['sourceShapeId'])
    match=re.search(r'_shape_(\d+)\.png$',element.get('image',''))
    return match.group(1) if match else None


def merge_document(old,new,required=()):
    result=deepcopy(new);slide_map={};element_maps={};matches=[];used=set()
    for slide in result['slides']:
        candidates=[s for s in old['slides'] if str(s['id']) not in used and
                    s.get('sourceSlideId') is not None and s.get('sourceSlideId')==slide.get('sourceSlideId')]
        if not candidates:
            candidates=[s for s in old['slides'] if str(s['id']) not in used and not s.get('sourceSlideId') and str(s['id'])==str(slide['id'])]
        previous=candidates[0] if len(candidates)==1 else None
        original=str(slide['id']);assigned=str(previous['id']) if previous else original
        if previous is None and assigned in {str(s['id']) for s in old['slides']}:assigned='slide_'+str(slide.get('sourceSlideId',original))
        slide_map[original]=assigned
        slide['id']=slide_map[original];emap={}
        if previous:
            used.add(str(previous['id']))
            for element in slide['elements']:
                source=shape_source(element)
                found=[e for e in previous['elements'] if source is not None and shape_source(e)==source]
                if not found:found=[e for e in previous['elements'] if str(e['id'])==str(element['id'])]
                prior=found[0] if len(found)==1 else None
                eid=str(element['id']);emap[eid]=str(prior['id']) if prior else eid;element['id']=emap[eid]
                if prior and prior.get('_editor'):
                    element['_editor']=deepcopy(prior['_editor']);element.update(element['_editor'])
            if previous.get('_editor'):
                slide['_editor']=deepcopy(previous['_editor']);slide.update(slide['_editor'])
                if slide.get('advanceAfter') is None:slide.pop('advanceAfter',None)
        element_maps[slide['id']]=emap;matches.append(slide)
    result['startSlide']=slide_map.get(str(result.get('startSlide','')),str(result.get('startSlide','')))
    def actions(items):
        for action in items:
            if action.get('action') in ('slide','enableSlide','element','animation') and 'slide' in action:
                action['slide']=slide_map.get(str(action['slide']),str(action['slide']))
            if action.get('action') in ('element','animation') and 'id' in action:
                action['id']=element_maps.get(str(action.get('slide',current)),{}).get(str(action['id']),str(action['id']))
    for slide in matches:
        current=str(slide['id']);emap=element_maps[current]
        for a in slide.get('animations',[]):
            a['element']=emap.get(str(a['element']),str(a['element']))
            if 'triggerElement' in a:a['triggerElement']=emap.get(str(a['triggerElement']),str(a['triggerElement']))
        actions(slide.get('onEnter',[]))
        for e in slide['elements']:
            actions(e.get('onClick',[]))
            for a in e.get('animations',[]):
                if 'triggerElement' in a:a['triggerElement']=emap.get(str(a['triggerElement']),str(a['triggerElement']))
    validate(result)
    available={(str(s['id']),str(e['id'])) for s in result['slides'] for e in s['elements']}
    missing=[(str(s),str(e)) for s,e in required if (str(s),str(e)) not in available]
    if missing:raise ValueError('Обновление удаляет кнопки с Blueprint-привязками: '+str(missing)+'. Верни эти фигуры в PowerPoint или убери их привязки. Старый UI сохранён.')
    return result
