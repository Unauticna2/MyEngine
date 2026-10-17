"""Async server-verified player sessions. Disk contents never imply verification."""
from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit,quote
import uuid
import json
from urllib.error import HTTPError

from engine_certificates import CertificateStore,read_json,transaction_key,identifier
from engine_scene import atomic_json
from engine_ui_media import https_url,open_url

class RegistrationRequired(ValueError):
    def __init__(self,message,url):super().__init__(message);self.url=url

def identity_request(url,body=None,token=None):
    from engine_transactions import request_json
    try:return request_json(url,body,token)
    except HTTPError as error:
        try:
            raw=error.read(4097)
            result=json.loads(raw) if len(raw)<=4096 else {}
            message=result.get('error') if isinstance(result,dict) else None
        except (ValueError,OSError):message=None;result={}
        if not isinstance(message,str) or len(message)>300:message='Сервер проверки игроков отклонил запрос: '+str(error.code)
        if isinstance(result,dict) and result.get('code')=='registration_required':raise RegistrationRequired(message,result.get('registrationUrl')) from None
        raise ValueError(message) from None


class PlayerIdentity:
    def __init__(self,root,api,request,log=print):
        self.api=api.rstrip('/');self.request=request;self.log=log
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='player-identity')
        self.sessions={};self.closed=False;self.events=[];self.failures=[]
        self.path=CertificateStore(root).path.with_suffix('.identity.json')
        if self.path.exists():
            try:
                data=read_json(self.path,262144)
                if not isinstance(data,dict) or data.get('api')!=self.api or not isinstance(data.get('sessions'),dict) or len(data['sessions'])>32:return
                for key,value in data['sessions'].items():
                    try:
                        transaction_key(key);record=self._saved(value)
                        record.update(state='checking',future=None,next=0.,freshUntil=0.,error='')
                        self.sessions[key]=record
                    except (ValueError,TypeError,KeyError):continue
            except (OSError,ValueError,TypeError):self.log('PLAYER IDENTITY: saved session could not be loaded')
    def _saved(self,value):
        if not isinstance(value,dict):raise ValueError('Invalid identity session')
        out={name:identifier(value[name],name,limit) for name,limit in [('id',128),('playerId',32),('productId',100),('certificateId',128),('clientNonce',128)]}
        token=value.get('pollToken')
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):raise ValueError('Invalid identity token')
        out['pollToken']=token;return out
    def save(self):
        records={key:self._saved(record) for key,record in self.sessions.items() if record.get('id') and record['state']!='expired'}
        atomic_json(self.path,{'format':1,'api':self.api,'sessions':records})
    def has_access(self,key):
        r=self.sessions.get(key)
        return bool(not self.closed and r and r['state']=='verified' and time.time()<r['expiresAt'] and time.monotonic()<r['freshUntil'])
    def start(self,certificate,key):
        if self.closed:return False
        transaction_key(key)
        current=self.sessions.get(key)
        if current and current['productId']!=certificate['productId']:raise ValueError('Identity key already belongs to another product')
        if current and current['state']=='creating':return False
        if current and current['state'] in ('pending','checking') and current.get('verificationUrl') and not current.get('error'):
            open_url(current['verificationUrl']);return False
        if key not in self.sessions and len(self.sessions)>=32:raise ValueError('Identity session limit: 32')
        record={name:certificate[name] for name in ('playerId','productId','certificateId')}
        record['clientNonce']=uuid.uuid4().hex
        future=self.pool.submit(self.request,self.api+'/api/sessions',{**record,'grantType':certificate.get('grantType','unknown')})
        record['registrationCertificate']={k:certificate[k] for k in ('schema','licenseStatus','grantType','signature','issuedAt','expiresAt','playerId','productId','certificateId','payment') if k in certificate}
        record.update(state='creating',future=future,next=0.,freshUntil=0.,error='')
        self.sessions[key]=record;return True
    def _binding(self,record,response):
        if not isinstance(response,dict):raise ValueError('Identity response must be an object')
        for name in ('playerId','productId','certificateId','clientNonce'):
            if response.get(name)!=record[name]:raise ValueError('Identity response does not match the selected certificate')
    def update(self):
        if self.closed:return
        now=time.monotonic()
        for key,record in self.sessions.items():
            future=record.get('future')
            if future is not None and future.done():
                record['future']=None
                creating=record['state']=='creating'
                try:
                    result=future.result();self._binding(record,result)
                    if record['state']=='creating':
                        checked=self._saved(result);url=https_url(result['verificationUrl'])
                        base=urlsplit(self.api);target=urlsplit(url)
                        if (target.scheme,target.netloc)!=(base.scheme,base.netloc) or target.path!='/verify':raise ValueError('Verification page must be on the configured identity server')
                        record.update(checked,state='pending',next=now+2,error='',verificationUrl=url)
                        self.save();open_url(url)
                    else:
                        if result.get('id')!=record['id'] or result.get('status') not in ('pending','verified','expired'):raise ValueError('Invalid identity status')
                        expiry=result.get('expiresAt')
                        if isinstance(expiry,bool) or not isinstance(expiry,(int,float)) or not math.isfinite(expiry) or expiry>time.time()+86400:raise ValueError('Invalid identity expiry')
                        state=result['status'] if expiry>time.time() else 'expired'
                        previous=record['state'];record.update(state=state,expiresAt=expiry,next=now+(15 if state=='verified' else 2),freshUntil=now+30 if state=='verified' else 0,error='')
                        if state=='verified' and previous!='verified':self.events.append((key,record['productId']))
                        if state=='expired':self.save()
                except Exception as error:
                    record.update(state='error' if creating else 'checking',error=str(error),next=now+10,freshUntil=0)
                    if creating:self.failures.append((key,record['productId'],str(error)))
                    if creating and isinstance(error,RegistrationRequired):
                        try:
                            url=https_url(error.url);base=urlsplit(self.api);target=urlsplit(url)
                            if (target.scheme,target.netloc)!=(base.scheme,base.netloc) or target.path!='/register' or target.query or target.fragment:raise ValueError('Registration page must be on the configured identity server')
                            url+='#certificate='+quote(json.dumps(record.pop('registrationCertificate',{}),separators=(',',':')),safe='')
                            open_url(url)
                            record['error']='Открыта регистрация. После регистрации / одобрения вернитесь в игру и выберите тот же сертификат.'
                        except Exception as redirect_error:record['error']=str(redirect_error)
                    self.log('PLAYER IDENTITY: '+record['error'])
            if record['state'] in ('pending','checking','verified') and record.get('future') is None and now>=record['next']:
                record['future']=self.pool.submit(self.request,self.api+'/api/sessions/'+record['id'],None,record['pollToken'])
    def close(self):
        self.closed=True
        for record in self.sessions.values():
            if record.get('future'):record['future'].cancel()
        self.pool.shutdown(wait=False,cancel_futures=True)
