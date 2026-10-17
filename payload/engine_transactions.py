"""Donation URLs and async checkout backend adapter. No merchant secrets in games.
A paid state is accepted only from the configured HTTPS server, never from a
browser return/click. The server must verify the provider payment/webhook.
"""
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
import json,re,time,uuid
from engine_ui_media import https_url,open_url

STATES=('idle','creating','pending','succeeded','canceled','failed','unknown')

def settings(value=None):
    v=value or {};out={k:str(v.get(k,'')).strip() for k in ('donationUrl','checkoutApi')}
    for key,value in out.items():
        if value:https_url(value)
    if out['checkoutApi']:
        from urllib.parse import urlsplit
        p=urlsplit(out['checkoutApi'])
        if p.query or p.fragment:raise ValueError('Checkout API must be a base URL without query/fragment')
        out['checkoutApi']=out['checkoutApi'].rstrip('/')
    return out

def load_settings(root):
    p=Path(root)/'payments.json'
    return settings(json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else None)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Checkout API redirects are not allowed')

def request_json(url,body=None,token=None):
    https_url(url);headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    if body is not None:headers['Content-Type']='application/json'
    request=Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with build_opener(HTTPSHandler(),NoRedirect()).open(request,timeout=10) as response:
        raw=response.read(65537)
    if len(raw)>65536:raise ValueError('Checkout response too large')
    data=json.loads(raw)
    if not isinstance(data,dict):raise ValueError('Checkout response must be an object')
    return data

class Transactions:
    def __init__(self,root):
        self.config=load_settings(root);self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='payments')
        self.records={};self.closed=False;self.last_donation=-100.
    def donate(self):
        url=self.config['donationUrl']
        if not url:raise ValueError('Set the donation URL in UI → Donations / transactions')
        if time.monotonic()-self.last_donation<1:return False
        self.last_donation=time.monotonic();open_url(url);return True
    def start(self,product,key='donation'):
        if self.closed:raise RuntimeError('Payments are closed')
        if not isinstance(product,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',product):raise ValueError('Product ID: letters, numbers, dot, dash, underscore')
        if not isinstance(key,str) or not 1<=len(key)<=100:raise ValueError('Invalid transaction key')
        api=self.config['checkoutApi']
        if not api:raise ValueError('Configure your checkout server URL first; use Open donation for a simple donation link')
        if key in self.records:return False # Explicit reset required before another purchase.
        if len(self.records)>=32:raise ValueError('Transaction limit: 32 per session')
        nonce=uuid.uuid4().hex
        future=self.pool.submit(request_json,api+'/checkout',{'product':product,'requestId':nonce})
        self.records[key]={'state':'creating','product':product,'requestId':nonce,'future':future,'next':0.,'error':'','id':None,'token':None,'created':time.monotonic()}
        return True
    def state(self,key='donation'):return self.records.get(key,{}).get('state','idle')
    def paid_once(self,key='donation'):
        record=self.records.get(key)
        if not record or record['state']!='succeeded' or record.get('consumed'):return False
        record['consumed']=True;return True
    def error(self,key='donation'):return self.records.get(key,{}).get('error','')
    def reset(self,key='donation'):
        record=self.records.get(key)
        if record and record['state'] in ('creating','pending','unknown'):raise ValueError('Cannot reset a pending/unknown transaction; resolve it on the server first')
        self.records.pop(key,None)
    def update(self):
        if self.closed:return
        now=time.monotonic();api=self.config['checkoutApi']
        for r in self.records.values():
            f=r.get('future')
            if f is not None and f.done():
                r['future']=None
                try:
                    result=f.result()
                    if result.get('product')!=r['product']:raise ValueError('Checkout returned a different product')
                    if r['state']=='creating':
                        ident=result['id'];token=result['pollToken'];url=https_url(result['checkoutUrl'])
                        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',ident):raise ValueError('Invalid checkout ID')
                        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9._~-]{16,2048}',token):raise ValueError('Invalid polling token')
                        r.update(id=ident,token=token,state='pending',next=now+2);open_url(url)
                    else:
                        if result.get('id')!=r['id'] or result.get('status') not in ('pending','succeeded','canceled','failed'):raise ValueError('Invalid transaction status response')
                        r['state']=result['status'];r['next']=now+2;r['error']=''
                except Exception as ex:
                    r['error']=str(ex)
                    if r['state']=='creating':r['state']='unknown' # POST may have reached the server; never retry a charge.
                    else:r['next']=now+5
            if r['state']=='pending' and r.get('future') is None and now>=r['next']:
                if now-r['created']>1800:r['state']='unknown';r['error']='Status polling timed out; check the backend transaction';continue
                r['future']=self.pool.submit(request_json,api+'/transactions/'+quote(r['id'],safe=''),None,r['token'])
    def close(self):
        self.closed=True
        for r in self.records.values():
            if r.get('future'):r['future'].cancel()
        self.pool.shutdown(wait=False,cancel_futures=True)

def for_world(world):
    if getattr(world,'editor_mode',False) or not getattr(world,'scripts_allowed',True):raise RuntimeError('Payments run only in Play with scripts enabled')
    core=getattr(world,'core',world);root=Path(world.root).resolve();current=getattr(core,'_transactions',None)
    if current is None or getattr(core,'_transactions_root',None)!=root:
        if current:current.close()
        core._transactions=Transactions(root);core._transactions_root=root
    return core._transactions
