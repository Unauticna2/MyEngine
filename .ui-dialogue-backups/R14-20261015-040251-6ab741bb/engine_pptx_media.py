"""Extract embedded video from the exact PowerPoint snapshot; never fetch URLs."""
from pathlib import Path,PurePosixPath
from urllib.parse import unquote
import hashlib,posixpath,shutil,xml.etree.ElementTree as ET,zipfile
from engine_ui_media import youtube_url

P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS={'p':P,'a':A,'r':R}
VIDEO_EXT={'.mp4','.m4v','.wmv','.avi','.mov','.mpeg','.mpg','.webm'}

def rels(archive,part):
    name=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
    if name not in archive.namelist():return {}
    return {n.get('Id'):n.attrib for n in ET.fromstring(archive.read(name))}

def resolve(part,target):
    path=posixpath.normpath(posixpath.join(posixpath.dirname(part),unquote(target)))
    if path.startswith(('../','/')) or '\\' in path or ':' in path:raise ValueError('Invalid PPTX media path')
    return path

def enrich_media(snapshot,document,stage):
    stage=Path(stage).resolve();warnings=document.setdefault('warnings',[])
    with zipfile.ZipFile(snapshot) as z:
        files=z.infolist()
        if len(files)>20000 or sum(i.file_size for i in files)>2*1024**3:raise ValueError('PPTX limit: 2 GiB uncompressed')
        presentation=ET.fromstring(z.read('ppt/presentation.xml'));pr=rels(z,'ppt/presentation.xml')
        for sn,entry in zip(presentation.find('p:sldIdLst',NS),document['slides']):
            part=resolve('ppt/presentation.xml',pr[sn.get('{'+R+'}id')]['Target']);tree=ET.fromstring(z.read(part));rs=rels(z,part)
            by_id={str(e.get('sourceShapeId',e['id'])):e for e in entry['elements']}
            for shape in tree.find('p:cSld/p:spTree',NS):
                prop=shape.find('.//p:cNvPr',NS)
                if prop is None or prop.get('id') not in by_id:continue
                element=by_id[prop.get('id')];candidates=[];links=[]
                for node in shape.iter():
                    tag=node.tag.rsplit('}',1)[-1]
                    if tag in ('videoFile','media'):
                        for attr in ('embed','link'):
                            if node.get('{'+R+'}'+attr) in rs:candidates.append(rs[node.get('{'+R+'}'+attr)])
                    elif tag in ('hlinkClick','hlinkHover') and node.get('{'+R+'}id') in rs:links.append(rs[node.get('{'+R+'}id')])
                found=False
                for rel in candidates:
                    if rel.get('TargetMode')=='External':continue
                    name=resolve(part,rel['Target']);ext=PurePosixPath(name).suffix.lower()
                    if ext not in VIDEO_EXT:continue
                    info=z.getinfo(name)
                    if info.file_size>1024**3:raise ValueError('Embedded video limit: 1 GiB per clip')
                    dest='media/'+hashlib.sha256(name.encode()).hexdigest()[:16]+ext;target=stage/dest
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if not target.exists():
                        with z.open(name) as source,target.open('wb') as out:shutil.copyfileobj(source,out,1024*1024)
                    element.setdefault('video',{'kind':'file','source':dest,'autoplay':False,'loop':False,'volume':1.})
                    found=True;break
                if not found:
                    for rel in candidates+links:
                        if rel.get('TargetMode')!='External':continue
                        try:url=youtube_url(rel['Target'])
                        except ValueError:continue
                        element.setdefault('video',{'kind':'youtube','source':url});found=True;break
                if candidates and not found:warnings.append(f"Slide {entry['id']}, {element['id']}: linked/unsupported video was kept as a poster. Embed an MP4 in PowerPoint, or use a YouTube hyperlink.")
