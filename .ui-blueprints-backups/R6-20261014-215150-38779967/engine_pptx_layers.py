"""Read PPTX metadata and prepare a temporary deck for LibreOffice rendering.

No Office automation. Each sprite is rendered on white and black mattes so
translucent fills and shadows can be recovered without colour-key artefacts.
"""
from copy import deepcopy
from pathlib import PurePosixPath
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
      'ct': 'http://schemas.openxmlformats.org/package/2006/content-types'}
for _prefix in ('p', 'a', 'r'):
    ET.register_namespace(_prefix, NS[_prefix])
# LibreOffice's format detection requires unprefixed Content_Types elements.
ET.register_namespace('', NS['ct'])


def tag(name):
    prefix, local = name.split(':')
    return '{' + NS[prefix] + '}' + local


def xml_bytes(node):
    return ET.tostring(node, encoding='utf-8', xml_declaration=True)


def relationships(data, part):
    path = PurePosixPath(part)
    name = str(path.parent / '_rels' / (path.name + '.rels'))
    if name not in data:
        return {}, None
    root = ET.fromstring(data[name])
    return {e.get('Id'): e for e in root}, root


def resolve_part(part, relation):
    if relation is None or relation.get('TargetMode') == 'External':
        raise ValueError('Expected an internal PPTX relationship')
    target = relation.get('Target', '')
    result = posixpath.normpath(posixpath.join(posixpath.dirname(part), target)) if not target.startswith('/') else target[1:]
    if result.startswith('../') or '\\' in result:
        raise ValueError('Invalid PPTX relationship')
    return result


def metadata(shape):
    props = shape.find('.//p:cNvPr', NS)
    name = props.get('name', '?') if props is not None else '?'
    alt = props.get('descr', '').strip() if props is not None else ''
    # A visible caption only becomes metadata when the entire text is JSON
    # with the explicit myengine wrapper. Alt Text has precedence.
    text = '\n'.join(''.join(t.text or '' for t in p.findall('.//a:t', NS))
                     for p in shape.findall('p:txBody/a:p', NS)).strip()
    inline = not alt.startswith('{') and text.startswith('{') and re.search(r'"myengine"\s*:', text)
    raw = text if inline else alt if alt.startswith('{') else ''
    if not raw:
        return {}, False
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('expected a JSON object')
        result = value.get('myengine', value)
        if not isinstance(result, dict):
            raise ValueError('myengine must be a JSON object')
        return result, bool(inline)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid JSON in shape '{name}': {exc}") from exc


def shape_xfrm(shape):
    for path in ('p:spPr/a:xfrm', 'p:grpSpPr/a:xfrm', 'p:xfrm'):
        node = shape.find(path, NS)
        if node is not None:
            return node
    return None


def inherited_xfrm(data, slide_part, shape):
    node = shape_xfrm(shape)
    if node is not None and node.find('a:off', NS) is not None and node.find('a:ext', NS) is not None:
        return node
    ph = shape.find('.//p:ph', NS)
    if ph is None:
        return None
    part = slide_part
    for relation_kind in ('slideLayout', 'slideMaster'):
        rels, _ = relationships(data, part)
        relation = next((r for r in rels.values() if r.get('Type', '').endswith('/'+relation_kind)), None)
        if relation is None:
            break
        part = resolve_part(part, relation)
        root = ET.fromstring(data[part])
        for candidate in root.findall('.//p:sp', NS):
            cph = candidate.find('.//p:ph', NS)
            if cph is None:
                continue
            matches = (cph.get('idx', '0') == ph.get('idx', '0')) if relation_kind == 'slideLayout' else (cph.get('type', 'obj') == ph.get('type', 'obj'))
            if matches:
                xfrm = shape_xfrm(candidate)
                if xfrm is not None and xfrm.find('a:off', NS) is not None and xfrm.find('a:ext', NS) is not None:
                    return xfrm
                ph = cph
    return None


def animations(slide, mapping, width, height, warnings, index):
    """Translate the common main-sequence effects; warn for other timelines."""
    output = []
    main = slide.find('.//p:cTn[@nodeType="mainSeq"]', NS)
    if main is None:
        if slide.find('p:timing', NS) is not None:
            warnings.append(f'Slide {index}: unsupported animation timeline; use JSON animations.')
        return output
    group, last_start, last_end = 0, 0., 0.
    for effect in main.findall('.//p:cTn', NS):
        cls = effect.get('presetClass')
        if cls is None:
            continue
        targets = {t.get('spid') for t in effect.findall('.//p:spTgt', NS)}
        if len(targets) != 1 or next(iter(targets), None) not in mapping:
            warnings.append(f'Slide {index}: skipped an animation with unsupported targets.')
            continue
        sid = next(iter(targets))
        preset = effect.get('presetID')
        kind = {'1': 'appear', '2': 'fly', '10': 'fade', '23': 'zoom'}.get(preset) if cls in ('entr', 'exit') else None
        rotation = effect.find('.//p:animRot', NS)
        if cls == 'emph' and rotation is not None:
            kind = 'spin'
        node_type = effect.get('nodeType')
        if kind is None or node_type not in ('clickEffect', 'withEffect', 'afterEffect'):
            warnings.append(f'Slide {index}, shape {sid}: unsupported effect {cls}/{preset}/{node_type}; use JSON animations.')
            continue
        durations = [int(n.get('dur'))/1000 for n in effect.findall('.//p:cTn', NS) if n.get('dur', '').isdigit()]
        duration = max(durations, default=0.001 if kind == 'appear' else 0.5)
        cond = effect.find('p:stCondLst/p:cond', NS)
        raw_delay = cond.get('delay', '0') if cond is not None else '0'
        delay = int(raw_delay)/1000 if raw_delay.isdigit() else 0.
        if node_type == 'clickEffect':
            group += 1
            start = delay
        elif node_type == 'afterEffect':
            start = last_end + delay
        else:
            start = last_start + delay
        item = {'element': mapping[sid], 'kind': kind, 'duration': duration,
                'delay': start, 'group': group, 'exit': cls == 'exit'}
        if kind == 'spin':
            item['degrees'] = int(rotation.get('by', '21600000')) / 60000
        if kind == 'fly':
            item['offset'] = [0, height]
            warnings.append(f'Slide {index}, shape {sid}: Fly uses a bottom offset; review JSON offset.')
        if effect.find('.//p:pRg', NS) is not None or effect.find('.//p:charRg', NS) is not None:
            warnings.append(f'Slide {index}, shape {sid}: text animation applies to the whole shape.')
        output.append(item)
        last_start, last_end = start, start + duration
    if slide.find('.//p:cTn[@nodeType="interactiveSeq"]', NS) is not None:
        warnings.append(f'Slide {index}: shape-triggered animations require JSON onClick actions.')
    if any(n.get('repeatCount') or n.get('repeatDur') or n.get('autoRev') == '1' for n in slide.findall('.//p:cTn', NS)):
        warnings.append(f'Slide {index}: repeated/reversed animations are imported as one pass.')
    return output


def prepare_layers(source, destination):
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 20000 or sum(i.file_size for i in entries) > 256*1024*1024:
            raise ValueError('PPTX is too large for the UI importer')
        if any(i.filename.lower().endswith('vbaproject.bin') for i in entries):
            raise ValueError('Macro-enabled files are not imported')
        data = {i.filename: archive.read(i) for i in entries}
    presentation = ET.fromstring(data['ppt/presentation.xml'])
    size = presentation.find('p:sldSz', NS)
    width, height = int(size.get('cx'))/12700, int(size.get('cy'))/12700
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ValueError('Invalid slide size')
    rels, rel_root = relationships(data, 'ppt/presentation.xml')
    order = presentation.find('p:sldIdLst', NS)
    if order is None or not 1 <= len(order) <= 256:
        raise ValueError('UI importer supports 1..256 slides')
    originals = [resolve_part('ppt/presentation.xml', rels[n.get(tag('r:id'))]) for n in order]
    order.clear()
    for node in list(rel_root):
        if node.get('Type', '').endswith('/slide'):
            rel_root.remove(node)
    for name in ('custShowLst', 'sectionLst'):
        for node in presentation.findall('p:'+name, NS):
            presentation.remove(node)
    content_types = ET.fromstring(data['[Content_Types].xml'])
    tasks, slides, warnings = [], [], []

    def add_page(original, part, keep, matte, task):
        if len(tasks) >= 2048:
            raise ValueError('UI import limit: 2048 render pages. Split this presentation.')
        variant = deepcopy(original)
        variant.set('show', '1')
        cs = variant.find('p:cSld', NS)
        tree = cs.find('p:spTree', NS)
        for child in list(tree):
            if child.tag not in (tag('p:nvGrpSpPr'), tag('p:grpSpPr')):
                tree.remove(child)
        if keep is not None:
            tree.append(deepcopy(keep))
        for node in list(variant):
            if node.tag in (tag('p:timing'), tag('p:transition'), tag('p:extLst')):
                variant.remove(node)
        if matte is not None:
            variant.set('showMasterSp', '0')
            for old in cs.findall('p:bg', NS):
                cs.remove(old)
            bg = ET.Element(tag('p:bg'))
            props = ET.SubElement(bg, tag('p:bgPr'))
            fill = ET.SubElement(props, tag('a:solidFill'))
            ET.SubElement(fill, tag('a:srgbClr'), {'val': matte})
            ET.SubElement(props, tag('a:effectLst'))
            cs.insert(0, bg)
        seq = len(tasks)+1
        name = f'ppt/slides/myengine_render_{seq}.xml'
        # Use a fresh basename; all copied slide relationships retain their base directory.
        if name in data:
            raise ValueError('Reserved slide name in presentation')
        data[name] = xml_bytes(variant)
        _, slide_rels = relationships(data, part)
        if slide_rels is not None:
            copied = deepcopy(slide_rels)
            for r in list(copied):
                if r.get('Type', '').endswith(('/notesSlide', '/comments')):
                    copied.remove(r)
            data[f'ppt/slides/_rels/myengine_render_{seq}.xml.rels'] = xml_bytes(copied)
        rid = 'myengineRender'+str(seq)
        ET.SubElement(rel_root, tag('rel:Relationship'), {'Id': rid,
            'Type': NS['r']+'/slide', 'Target': f'slides/myengine_render_{seq}.xml'})
        ET.SubElement(order, tag('p:sldId'), {'id': str(100000+seq), tag('r:id'): rid})
        ET.SubElement(content_types, tag('ct:Override'), {'PartName': '/'+name,
            'ContentType': 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'})
        tasks.append(task)

    for index, part in enumerate(originals, 1):
        original = ET.fromstring(data[part])
        tree = original.find('p:cSld/p:spTree', NS)
        entry = {'id': str(index), 'name': original.find('p:cSld', NS).get('name', f'Slide {index}'),
                 'enabled': original.get('show', '1') not in ('0', 'false'),
                 'background': f'slide_{index}_background.png', 'elements': [], 'animations': [], 'onEnter': []}
        add_page(original, part, None, None, {'type': 'background', 'file': entry['background']})
        mapping = {}
        for shape in tree:
            if shape.tag in (tag('p:nvGrpSpPr'), tag('p:grpSpPr')):
                continue
            if shape.tag not in {tag('p:'+k) for k in ('sp', 'pic', 'grpSp', 'graphicFrame', 'cxnSp')}:
                warnings.append(f'Slide {index}: unsupported shape container {shape.tag.rsplit("}",1)[-1]}')
                continue
            props = shape.find('.//p:cNvPr', NS)
            sid = props.get('id')
            meta, inline = metadata(shape)
            if shape.tag == tag('p:grpSp') and any(metadata(child)[0] for child in shape.findall('.//p:sp', NS)):
                warnings.append(f'Slide {index}, group {sid}: child JSON is not interactive; ungroup the buttons.')
            if 'slide' in meta:
                if not isinstance(meta['slide'], dict):
                    raise ValueError('slide metadata must be an object')
                entry.update({k: v for k, v in meta['slide'].items() if k in ('id', 'enabled', 'modal', 'onEnter')})
                continue
            xfrm = inherited_xfrm(data, part, shape)
            if xfrm is None:
                warnings.append(f'Slide {index}, shape {sid}: cannot resolve geometry; skipped.')
                continue
            off, ext = xfrm.find('a:off', NS), xfrm.find('a:ext', NS)
            rect = [int(off.get('x'))/12700, int(off.get('y'))/12700,
                    max(1., int(ext.get('cx'))/12700), max(1., int(ext.get('cy'))/12700)]
            item = {'id': sid, 'name': props.get('name', sid), 'rect': rect,
                    'rotation': int(xfrm.get('rot', '0'))/60000,
                    'enabled': props.get('hidden', '0') not in ('1', 'true'),
                    'onClick': [], 'animations': [], 'image': f'slide_{index}_shape_{sid}.png'}
            item.update({k: v for k, v in meta.items() if k in ('id','enabled','onClick','animations','frames','fps','color','opacity')})
            if shape.find('.//a:videoFile', NS) is not None or shape.find('.//a:audioFile', NS) is not None:
                warnings.append(f'Slide {index}, shape {sid}: media is exported as a static poster.')
            layer = deepcopy(shape)
            lp = layer.find('.//p:cNvPr', NS)
            lp.attrib.pop('hidden', None)
            lx = shape_xfrm(layer)
            if lx is None:
                sp = layer.find('p:spPr', NS)
                if sp is None:
                    raise ValueError('Cannot set placeholder transform')
                lx = deepcopy(xfrm)
                sp.insert(0, lx)
            else:
                # Explicit geometry is needed when inherited placeholder settings are absent.
                for key in ('off','ext'):
                    if lx.find('a:'+key, NS) is None:
                        lx.append(deepcopy(xfrm.find('a:'+key, NS)))
            lx.set('rot', '0')
            if inline:
                for t in layer.findall('p:txBody//a:t', NS):
                    t.text = ''
            mapping[sid] = str(item['id'])
            for matte, kind in (('000000','black'), ('FFFFFF','white')):
                add_page(original, part, layer, matte, {'type': kind, 'element': item})
            entry['elements'].append(item)
        entry['animations'] = animations(original, mapping, width, height, warnings, index)
        if original.find('p:transition', NS) is not None:
            warnings.append(f'Slide {index}: slide transition is not imported.')
        slides.append(entry)
    data['ppt/presentation.xml'] = xml_bytes(presentation)
    data['ppt/_rels/presentation.xml.rels'] = xml_bytes(rel_root)
    data['[Content_Types].xml'] = xml_bytes(content_types)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in data.items():
            archive.writestr(name, content)
    return {'format': 1, 'kind': 'MyEngine.UI', 'width': width, 'height': height,
            'startSlide': str(slides[0]['id']), 'slides': slides, 'warnings': warnings,
            'importer': 'LibreOffice'}, tasks
