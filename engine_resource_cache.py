"""Render-thread LRU. A world pins resources; scene switches retain unpinned entries."""
from collections import OrderedDict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

@dataclass
class Entry:
    value: object
    size: int
    dispose: object
    refs: int = 0

class ResourceCache:
    def __init__(self,budget=512*1024*1024):
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix="asset-decode");self.entries=OrderedDict();self.budget=budget;self.bytes=0;self.hits=0;self.misses=0
    def key(self,kind,path,extra=()):
        st=path.stat();return (kind,str(path),st.st_mtime_ns,st.st_size,*extra)
    def get(self,key,loader,size=lambda v:0,dispose=lambda v:None):
        entry=self.entries.get(key)
        if entry is None:
            value=loader();entry=Entry(value,size(value),dispose);self.entries[key]=entry;self.bytes+=entry.size;self.misses+=1
        else:self.hits+=1
        entry.refs+=1;self.entries.move_to_end(key);self.trim();return entry.value
    def release(self,key):
        e=self.entries[key];e.refs-=1
        if e.refs<0:raise RuntimeError('Resource cache lease imbalance')
        self.trim()
    def trim(self):
        for key in list(self.entries):
            if self.bytes<=self.budget:break
            if not self.entries[key].refs:self.remove(key)
    def remove(self,key):
        entry=self.entries.pop(key);self.bytes-=entry.size;entry.dispose(entry.value)
    def close(self):
        for key in list(self.entries):self.remove(key)
        self.pool.shutdown(wait=True,cancel_futures=True)

def shared(core):
    cache=getattr(core,'resource_cache',None)
    if cache is None:cache=core.resource_cache=ResourceCache()
    return cache
