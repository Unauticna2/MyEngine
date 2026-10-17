"""PowerPoint JSON punctuation, transition metadata and stable source IDs."""
import json
import math
import xml.etree.ElementTree as ET
import zipfile

ANIMATION_MODES=('imported','auto','click','loop','manual')
TRANSITIONS=('none','fade','push')
DIRECTIONS=('left','right','up','down')


def normalize_quotes(text):
    # Only normalize delimiters. Quotes and nonbreaking spaces INSIDE a normal
    # JSON string are data and must survive unchanged.
    out=[];closing=None;escape=False
    pairs={'“':{'”'},'„':{'“','”'},'«':{'»'}}
    for ch in text:
        if closing is None:
            if ch=='"':closing={'"'};out.append(ch)
            elif ch in pairs:closing=pairs[ch];out.append('"')
            else:out.append(' ' if ch in '\u00a0\u202f' else ch)
        elif escape:out.append(ch);escape=False
        elif ch=='\\':out.append(ch);escape=True
        elif ch in closing:out.append('"');closing=None
        else:out.append(ch)
    return ''.join(out)


def loads_metadata(text):
    try:return json.loads(text)
    except ValueError:return json.loads(normalize_quotes(text))


def transition_settings(value=None):
    value=value or {};kind=value.get('kind','none');direction=value.get('direction','left')
    duration=float(value.get('duration',.35))
    if kind not in TRANSITIONS or direction not in DIRECTIONS or not math.isfinite(duration) or not 0<=duration<=30:
        raise ValueError('Transition: none/fade/push, direction left/right/up/down, duration 0..30 seconds')
    return {'kind':kind,'direction':direction,'duration':duration}


def enrich_snapshot(path,document):
    """Read effects from the exact SaveCopyAs snapshot, including unsaved edits."""
    from engine_pptx_layers import NS, tag, relationships, resolve_part
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist()
        if len(infos)>20000 or sum(i.file_size for i in infos if i.filename.endswith(('.xml','.rels')))>256*1024*1024:raise ValueError('PPTX snapshot too large')
        data={i.filename:archive.read(i) for i in infos if i.filename.endswith(('.xml','.rels'))}
    presentation=ET.fromstring(data['ppt/presentation.xml']);rels,_=relationships(data,'ppt/presentation.xml')
    order=list(presentation.find('p:sldIdLst',NS));warnings=document.setdefault('warnings',[])
    for node,entry in zip(order,document['slides']):
        entry['sourceSlideId']=node.get('id')
        part=resolve_part('ppt/presentation.xml',rels[node.get(tag('r:id'))]);slide=ET.fromstring(data[part])
        tr=slide.find('.//p:transition',NS)
        if tr is None:continue
        # Office 2010+ stores milliseconds in p14:dur; older decks use spd.
        duration=next((v for k,v in tr.attrib.items() if k.endswith('}dur')),None)
        seconds=float(duration)/1000 if duration is not None else {'slow':1.,'med':.7,'fast':.35}.get(tr.get('spd'),.35)
        effect=next((e for e in tr if e.tag.rsplit('}',1)[-1] not in ('sndAc','extLst')),None)
        kind=effect.tag.rsplit('}',1)[-1] if effect is not None else 'none'
        direction={'l':'left','r':'right','u':'up','d':'down'}.get(effect.get('dir') if effect is not None else '', 'left')
        if kind=='cut':kind='none'
        if kind not in TRANSITIONS:
            warnings.append(f"Slide {entry['id']}: PowerPoint transition {kind!r} uses fade in MyEngine.")
            kind='fade'
        entry.setdefault('transition',transition_settings({'kind':kind,'direction':direction,'duration':seconds}))
        if 'advTm' in tr.attrib:entry.setdefault('advanceAfter',float(tr.get('advTm'))/1000)
        entry.setdefault('advanceOnClick',tr.get('advClick','1') not in ('0','false'))
