"""Bounded background decoding; OpenGL uploads stay on the render thread."""
from collections import deque
from time import perf_counter
from engine_assets import load_texture

class UIAssets:
    def __init__(self,world):
        self.world=world;self.resources=world.resources;self.pool=self.resources.cache.pool
        self.queue=deque();self.known=set();self.pending={};self.handles={};self.failed={};self.closed=False
    def request(self,names,*,priority=False):
        names=list(dict.fromkeys(names))
        if priority:
            desired=set(names);queued=set(self.queue)
            self.queue=deque([n for n in names if n in queued]+[n for n in self.queue if n not in desired])
        for name in reversed(names) if priority else names:
            if name in self.known:continue
            self.known.add(name)
            if priority:self.queue.appendleft(name)
            else:self.queue.append(name)
    def ready(self,names):
        return all(n in self.handles or n in self.failed for n in names)
    def progress(self,names):
        return sum(n in self.handles or n in self.failed for n in names)/max(1,len(names))
    def fail(self,name,error):
        self.failed[name]=str(error);self.world.log('UI IMAGE ERROR:',name,error)
    def pump(self):
        if self.closed:return
        start=perf_counter();uploaded=0
        for name,future in list(self.pending.items()):
            if not future.done():continue  # Never wait in a frame/click handler.
            del self.pending[name]
            try:self.handles[name]=self.resources.texture(name,decoded=future)
            except Exception as ex:self.fail(name,ex)
            uploaded+=1
            if uploaded>=1 or perf_counter()-start>=.004:break
        while self.queue and len(self.pending)<4:
            name=self.queue.popleft()
            try:
                path=self.resources.path(name)
                if self.resources.cache.key('texture',path) in self.resources.cache.entries:
                    self.handles[name]=self.resources.texture(name)
                else:self.pending[name]=self.pool.submit(load_texture,path)
            except Exception as ex:self.fail(name,ex)
            if perf_counter()-start>=.004:break
    def close(self):
        self.closed=True;self.queue.clear()
        for future in self.pending.values():future.cancel()
        self.pending.clear();self.handles.clear()
