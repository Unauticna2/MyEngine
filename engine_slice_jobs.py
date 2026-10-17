"""Bounded, persistent background slices. GL and physics commits stay on the owner."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from engine_native4d import slice_layers

class SliceJobs:
    def __init__(self):
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='slice4d')
        self.pending=OrderedDict();self.ready={};self.running=None;self.cache=OrderedDict();self.closed=False;self.cancelled=set()
    def _pump(self):
        if self.running and self.running[2].done():
            uid,key,job,ck=self.running;self.running=None
            try:result=job.result()
            except Exception as ex:result=ex
            if uid not in self.cancelled:self.ready[uid]=(key,result)
            self.cancelled.discard(uid)
            if not isinstance(result,Exception):
                self.cache[ck]=result
                while len(self.cache)>12 or sum(len(m.vertices) for m in self.cache.values() if m)>2_400_000:self.cache.popitem(last=False)
        if self.running is None and self.pending and not self.closed:
            uid,(layers,key)=self.pending.popitem(last=False)
            ck=(tuple(id(l.geometry) for l in layers),key)
            cut,spacing,sw,angles,scale=key
            self.running=(uid,key,self.pool.submit(slice_layers,layers,spacing,sw,angles,scale,cut),ck)
    def get(self,uid,layers,key,current):
        self._pump()
        result=self.ready.pop(uid,None)
        if result and isinstance(result[1],Exception):raise result[1]
        ck=(tuple(id(l.geometry) for l in layers),key)
        if key!=current:
            if ck in self.cache:
                result=(key,self.cache[ck]);self.cache.move_to_end(ck);self.pending.pop(uid,None)
            elif not self.running or self.running[:2]!=(uid,key):self.pending[uid]=(layers,key)
        else:self.pending.pop(uid,None)
        self._pump()
        return result
    def cancel(self,uid):
        self.pending.pop(uid,None);self.ready.pop(uid,None)
        if self.running and self.running[0]==uid:self.cancelled.add(uid)
    def close(self):
        self.closed=True;self.pending.clear();self.ready.clear();self.cache.clear()
        self.pool.shutdown(wait=False,cancel_futures=True)
