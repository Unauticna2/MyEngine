"""Donation URLs and async checkout backend adapter. No merchant secrets in games.
A paid state is accepted only from the configured HTTPS server, never from a
browser return/click. The server must verify the provider payment/webhook.
"""
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.parse import quote,urlsplit,urlunsplit,urlencode
from concurrent.futures import ThreadPoolExecutor
import json,re,time,uuid
from engine_ui_media import https_url,open_url

STATES=('idle','creating','pending','succeeded','canceled','failed','unknown','manual')

class PaymentConfigurationError(ValueError):
    """Recoverable author setup issue: abort this action, keep the UI script alive."""

def settings(value=None):
    v={} if value is None else value
    if not isinstance(v,dict):raise ValueError('payments.json must be an object')
    out={k:str(v.get(k,'')).strip() for k in ('donationUrl','checkoutApi','checkoutSite','identityApi')}
    for key,value in out.items():
        if value:https_url(value)
    if out['checkoutApi']:
        p=urlsplit(out['checkoutApi'])
        if p.query or p.fragment:raise ValueError('Checkout API must be a base URL without query/fragment')
        out['checkoutApi']=out['checkoutApi'].rstrip('/')
    out['checkoutMode']=v.get('checkoutMode','site' if out['checkoutSite'] else 'api')
    out['identityRequired']=v.get('identityRequired',False)
    if type(out['identityRequired']) is not bool:raise ValueError('identityRequired must be a boolean')
    if out['identityApi']:
        p=urlsplit(out['identityApi'])
        if p.path not in ('','/') or p.query or p.fragment:raise ValueError('Identity API must be an HTTPS origin without path/query/fragment')
        out['identityApi']=out['identityApi'].rstrip('/')
    if out['checkoutMode'] not in ('api','site'):raise ValueError('Checkout mode must be api or site')
    out['siteProduct']=v.get('siteProduct','deluxe')
    if not isinstance(out['siteProduct'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',out['siteProduct']):raise ValueError('Invalid website product ID')
    products=v.get('siteProducts',[out['siteProduct']])
    if not isinstance(products,list) or not 1<=len(products)<=100 or any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',p) for p in products):raise ValueError('Invalid website catalog IDs')
    if len(set(products))!=len(products) or out['siteProduct'] not in products:raise ValueError('Website catalog requires unique IDs including its default product')
    out['siteProducts']=list(products)
    if out['checkoutSite']:
        p=urlsplit(out['checkoutSite'])
        if p.query or p.fragment:raise ValueError('Checkout site URL must not contain query/fragment')
    return out

def load_settings(root):
    p=Path(root)/'payments.json'
    try:return settings(json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else None)
    except (OSError,ValueError,TypeError) as ex:
        raise PaymentConfigurationError('Не удалось прочитать настройки оплаты: '+str(p)+' — '+str(ex)) from ex

def setup_message(root):
    return ('Платёжный сайт не подключён. Stop → Assets / extensions → Коммерция / генератор сайта → '
            'Сайт и кнопки: вставь HTTPS-адрес опубликованного сайта и нажми «Сохранить и подключить сайт к кнопкам», затем Play. '
            'Экспорт ZIP сам по себе сайт не публикует. Настройки проекта: '+str(Path(root)/'payments.json'))

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
        self.root=Path(root).resolve();self.config=load_settings(self.root);self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='payments')
        self.records={};self.closed=False;self.last_donation=-100.
        self._certificates=None;self._certificate_dialog=None;self._certificate_notice=None
        self._certificate_target=None;self.certificate_status='idle';self.certificate_error='';self.log=print
        self._identity=None
    @property
    def identity(self):
        api=self.config['identityApi']
        if not api:raise PaymentConfigurationError('Укажи адрес сервера проверки игроков в «Коммерция → Проверка игрока / SMS».')
        if self._identity is None or self._identity.api!=api:
            if self._identity:self._identity.close()
            from engine_player_identity import PlayerIdentity,identity_request
            self._identity=PlayerIdentity(self.root,api,identity_request,self.log)
        return self._identity
    def player_verified(self,key='purchase'):
        # Legacy Blueprint gate: R25 also allows the explicit voluntary-donation mode.
        return self.unlock_all or self.identity_verified(key)
    @property
    def unlock_all(self):
        from engine_access import unlock_all
        return unlock_all(self.root)
    def identity_verified(self,key='purchase'):
        if not self.config['identityApi']:return False
        identity=self.identity
        if not identity.has_access(key):return False
        saved=identity.sessions[key];record=self.records.get(key)
        return saved['productId'] in self.config['siteProducts'] and (not record or record['product']==saved['productId'])
    @property
    def certificates(self):
        if self._certificates is None:
            from engine_certificates import CertificateStore
            self._certificates=CertificateStore(self.root)
            if self._certificates.load_error:self.log('CERTIFICATE STORE: '+self._certificates.load_error)
        return self._certificates
    def has_access(self,key='donation'):
        if self.unlock_all:return True
        if self.config['identityRequired']:return self.player_verified(key)
        record=self.records.get(key)
        if record and record['state']=='succeeded':return True
        return self.certificates.has(key,self.config['siteProducts'],record['product'] if record else None)
    def _certificate_request(self,product,key,player_id=''):
        from engine_certificates import identifier,transaction_key
        identifier(product,'product');transaction_key(key)
        if player_id:identifier(player_id,'playerId',32)
        if product not in self.config['siteProducts']:
            raise ValueError('Товара '+product+' нет в каталоге payments.json. Подключи актуальный каталог в генераторе сайта.')
        record=self.records.get(key)
        saved=self.certificates.entries.get(key)
        if record and record['product']!=product or saved and saved['productId']!=product:
            raise ValueError('Ключ '+key+' уже связан с другим товаром. Укажи отдельный key.')
    def import_certificate(self,product,key='donation',player_id=''):
        """Open the asynchronous picker. next means opened, never activated/paid."""
        if self.closed:return False
        if self._certificate_dialog is not None or self._certificate_notice is not None:return False
        self.refresh_if_idle()
        if self.config['identityRequired'] and not self.config['identityApi']:
            raise PaymentConfigurationError('SMS-проверка обязательна, но сервер игроков не подключён. Локальный сертификат не откроет доступ.')
        try:self._certificate_request(product,key,player_id)
        except ValueError as ex:raise PaymentConfigurationError(str(ex)) from ex
        from engine_certificate_dialog import CertificateDialog
        self._certificate_target=(product,key,player_id)
        self.certificate_status='selecting';self.certificate_error=''
        self._certificate_dialog=CertificateDialog(product,key,player_id,identity_required=self.config['identityRequired'])
        return True
    def activate_certificate(self,certificate,product,key,player_id=''):
        """Commit a local grant, leaving checkout states and paid_once untouched."""
        if self.closed:raise RuntimeError('Payments are closed')
        if self.config['identityRequired']:raise ValueError('Требуется серверная SMS-проверка. Локальная активация отключена.')
        from engine_certificates import validate_certificate
        self._certificate_request(product,key,player_id)
        clean=validate_certificate(certificate,product,player_id)
        self.certificates.activate(key,clean)
        return clean
    def _update_certificates(self):
        if self._certificate_notice is not None and self._certificate_notice.done.is_set():
            self._certificate_notice=None
        dialog=self._certificate_dialog
        if dialog is None or not dialog.done.is_set():return
        self._certificate_dialog=None
        product,key,player_id=self._certificate_target;self._certificate_target=None
        if dialog.error:
            self.certificate_status='error';self.certificate_error=dialog.error
            self.log('CERTIFICATE: '+dialog.error);return
        if dialog.result is None or dialog.cancelled.is_set():
            self.certificate_status='canceled';return
        from engine_certificate_dialog import CertificateDialog
        try:
            if self.config['identityRequired']:
                self._certificate_request(product,key,player_id)
                from engine_certificates import validate_certificate
                certificate=validate_certificate(dialog.result,product,player_id)
                self.identity.start(certificate,key)
                self.certificate_status='awaiting_sms';self.certificate_error=''
                self.log('PLAYER IDENTITY: проверяем запись игрока; продолжи подтверждение в браузере.')
                return
            certificate=self.activate_certificate(dialog.result,product,key,player_id)
            self.certificate_status='activated';self.certificate_error=''
            message='Доступ активирован: '+certificate['edition']+'\nИгрок: '+certificate['playerId']+'\nАктивация сохранена на этом компьютере.'
            self.log('CERTIFICATE ACTIVATED: '+product+' / '+key)
            self._certificate_notice=CertificateDialog(product,key,message=message)
        except Exception as ex:
            self.certificate_status='error';self.certificate_error=str(ex)
            self.log('CERTIFICATE: '+str(ex))
            self._certificate_notice=CertificateDialog(product,key,message='Не удалось сохранить активацию: '+str(ex),error=True)
    def refresh_if_idle(self):
        # A rejected click creates no record, so fixing settings permits a retry.
        # Keep configuration fixed while a transaction exists, including pending API polls.
        if not self.records:self.config=load_settings(self.root)
    def donate(self):
        self.refresh_if_idle()
        url=self.config['donationUrl']
        if not url:raise PaymentConfigurationError('Ссылка «Открыть донат» не настроена. '+setup_message(self.root))
        if time.monotonic()-self.last_donation<1:return False
        self.last_donation=time.monotonic();open_url(url);return True
    def start(self,product,key='donation'):
        if self.closed:raise RuntimeError('Payments are closed')
        if not isinstance(product,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',product):raise ValueError('Product ID: letters, numbers, dot, dash, underscore')
        if not isinstance(key,str) or not 1<=len(key)<=100:raise ValueError('Invalid transaction key')
        if key in self.records:
            if self.records[key]['product']!=product:raise PaymentConfigurationError('Для разных товаров нужны разные key в Transaction start. Ключ '+key+' уже используется товаром '+self.records[key]['product']+'.')
            return False # Explicit reset required before another purchase.
        if len(self.records)>=32:raise ValueError('Transaction limit: 32 per session')
        self.refresh_if_idle()
        nonce=uuid.uuid4().hex
        if self.config['checkoutMode']=='site':
            if not self.config['checkoutSite']:raise PaymentConfigurationError(setup_message(self.root))
            if product not in self.config['siteProducts']:raise PaymentConfigurationError('В Blueprint задан product='+product+', которого нет в подключённом каталоге. Доступны: '+', '.join('product='+p for p in self.config['siteProducts'])+'. Обнови каталог в генераторе и подключи сайт заново.')
            p=urlsplit(self.config['checkoutSite'])
            url=urlunsplit((p.scheme,p.netloc,p.path,urlencode({'product':product,'requestId':nonce}),'checkout'))
            open_url(url)
            self.records[key]={'state':'manual','product':product,'requestId':nonce,'future':None,
                'error':'Manual confirmation: the website cannot confirm a payment to the game.', 'created':time.monotonic()}
            return True
        api=self.config['checkoutApi']
        if not api:raise PaymentConfigurationError(setup_message(self.root))
        future=self.pool.submit(request_json,api+'/checkout',{'product':product,'requestId':nonce})
        self.records[key]={'state':'creating','product':product,'requestId':nonce,'future':future,'next':0.,'error':'','id':None,'token':None,'created':time.monotonic()}
        return True
    def state(self,key='donation'):return self.records.get(key,{}).get('state','idle')
    def paid_once(self,key='donation'):
        record=self.records.get(key)
        if not record or record['state']!='succeeded' or record.get('consumed'):return False
        record['consumed']=True;return True
    def error(self,key='donation'):return self.records.get(key,{}).get('error','')
    def request_id(self,key='donation'):return self.records.get(key,{}).get('requestId','')
    def reset(self,key='donation'):
        record=self.records.get(key)
        if record and record['state'] in ('creating','pending','unknown'):raise ValueError('Cannot reset a pending/unknown transaction; resolve it on the server first')
        self.records.pop(key,None)
    def update(self):
        if self.closed:return
        self._update_certificates()
        if self.config['identityApi']:
            identity=self.identity;identity.update()
            for key,product in identity.events:
                self.certificate_status='verified';self.certificate_error=''
                self.log('PLAYER VERIFIED: '+key+' / '+product)
            identity.events.clear()
            for key,product,message in identity.failures:
                self.certificate_status='error';self.certificate_error=message
                if self._certificate_notice is None:
                    from engine_certificate_dialog import CertificateDialog
                    self._certificate_notice=CertificateDialog(product,key,message='Проверка игрока: '+message,error=True)
            identity.failures.clear()
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
        if self._identity:self._identity.close()
        for dialog in (self._certificate_dialog,self._certificate_notice):
            if dialog is not None:dialog.close()
        for r in self.records.values():
            if r.get('future'):r['future'].cancel()
        self.pool.shutdown(wait=False,cancel_futures=True)

def for_world(world):
    if getattr(world,'editor_mode',False) or not getattr(world,'scripts_allowed',True):raise RuntimeError('Payments run only in Play with scripts enabled')
    core=getattr(world,'core',world);root=Path(world.root).resolve();current=getattr(core,'_transactions',None)
    if current is None or getattr(core,'_transactions_root',None)!=root:
        if current:current.close()
        core._transactions=Transactions(root);core._transactions_root=root
    core._transactions.log=getattr(world,'log',print)
    return core._transactions
