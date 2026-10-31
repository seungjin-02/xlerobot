"""Non-destructive map export and persistent, map-scoped mobile routes."""
import io
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import zipfile


def valid_name(name):
    return isinstance(name,str) and name.endswith('.yaml') and len(name.encode('utf8'))<=255 and len(name)>5 and not name.startswith('.') and '..' not in name and '/' not in name and '\\' not in name and name.isprintable()

class MapLibrary:
    def __init__(self, maps, metadata):
        self.maps=Path(maps).resolve();self.metadata=Path(metadata);self.lock=threading.RLock()
    def resolve(self,name):
        if not valid_name(name):raise ValueError('Invalid map name')
        p=(self.maps/name).resolve()
        if p.parent!=self.maps or not p.is_file():raise ValueError('Map not found')
        return p
    def read(self):
        with self.lock:
            if not self.metadata.exists():return {'version':1,'maps':{}}
            return json.loads(self.metadata.read_text(encoding='utf-8'))
    def save(self,name,label,route):
        self.resolve(name)
        if not isinstance(label,str) or len(label)>100:raise ValueError('Invalid label')
        if not isinstance(route,list) or len(route)>100:raise ValueError('Invalid route')
        points=[]
        for p in route:
            if not isinstance(p,dict) or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) or abs(p[k])>10000 for k in ('x','y','yaw')):raise ValueError('Invalid waypoint')
            points.append({k:p[k] for k in ('x','y','yaw')})
        with self.lock:
            data=self.read();data['maps'][name]={'label':label,'route':points}
            self.metadata.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=self.metadata.parent,prefix='.library-')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:
                    json.dump(data,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
                os.replace(tmp,self.metadata)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        return data['maps'][name]
    def export(self,name):
        import yaml
        p=self.resolve(name);document=yaml.safe_load(p.read_text(encoding='utf-8'))
        if not isinstance(document,dict) or not isinstance(document.get('image'),str):raise ValueError('Invalid map YAML')
        image=(p.parent/document['image']).resolve()
        if image.parent!=self.maps or not image.is_file() or image.suffix.lower() not in ('.pgm','.png'):raise ValueError('Invalid map image')
        files=[image];pb=p.with_suffix('.pbstream')
        if pb.exists():
            if pb.resolve().parent!=self.maps:raise ValueError('Invalid map state')
            files.append(pb)
        if sum(f.stat().st_size for f in files)>64*1024*1024:raise ValueError('Map export exceeds 64 MiB')
        document['image']=image.name
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(p.name,yaml.safe_dump(document,allow_unicode=True))
            for f in files:archive.write(f,f.name)
            meta=self.read()['maps'].get(name)
            if meta is not None:archive.writestr('mobile-route.json',json.dumps(meta,ensure_ascii=False,allow_nan=False))
        return buf.getvalue()
