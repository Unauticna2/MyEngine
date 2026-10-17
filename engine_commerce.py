"""Project commerce settings and an offline YooMoney/Render site generator."""
from pathlib import Path
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import hashlib
import html
import json
import os
import re
import secrets
import tempfile
import zipfile
from engine_scene import atomic_json

TEMPLATE = Path(__file__).resolve().parent / 'templates/payment-site'
PUBLIC_FILES = ('styles.css', 'favicon.svg', 'app.js', 'developer-core.js', 'developer.js')
EXTRA_FILES = ('scripts/build-static.mjs', 'tools/setup-developer.html', 'tools/setup-developer.js')
DEFAULTS = dict(format=1, gameName='Моя игра', productId='deluxe', productTitle='Deluxe',
    description='Дополнение к игре.', sellerName='', amount='10.00', receiver='',
    supportUrl='', activationText='Активация вручную после проверки перевода. Передай поддержке ID игрока и номер операции ЮMoney.',
    paymentsEnabled=True, siteUrl='', developerAccess={'enabled': False})


def text_field(value, key, limit, required=False):
    result = value.get(key, DEFAULTS.get(key, ''))
    if not isinstance(result, str): raise ValueError(f'{key}: требуется текст')
    result = result.strip()
    if len(result) > limit or any(ord(c) < 32 and c not in '\n\t' for c in result):
        raise ValueError(f'{key}: слишком длинный текст или служебные символы')
    if required and not result: raise ValueError(f'Заполни поле {key}')
    return result


def https_address(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or re.search(r'\s', value):
        raise ValueError('Нужен адрес https:// без логина, пароля и пробелов')
    _ = p.port
    return value


def developer_settings(value):
    if not isinstance(value, dict): raise ValueError('Неверные настройки разработчика')
    if value.get('enabled') is not True: return {'enabled': False}
    patterns = {'playerId': r'[A-Za-z0-9_.-]{1,32}', 'salt': r'[a-f0-9]{32}', 'fingerprintSha256': r'[a-f0-9]{64}'}
    for key, pattern in patterns.items():
        if not isinstance(value.get(key), str) or not re.fullmatch(pattern, value[key]):
            raise ValueError('Неверные настройки разработчика: ' + key)
    return {'enabled': True, **{key: value[key] for key in patterns}}


def create_developer(player_id, last4, phone):
    player_id = player_id.strip(); last4 = last4.strip(); phone = phone.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', player_id): raise ValueError('ID разработчика: 1–32 латинских символа, цифры, . _ -')
    if not re.fullmatch(r'[0-9]{4}', last4): raise ValueError('Введи ровно последние 4 цифры карты')
    if not re.fullmatch(r'\+?[0-9\s().-]+', phone): raise ValueError('Неверный телефон')
    phone = re.sub(r'[^0-9]', '', phone)
    if len(phone) == 11 and phone.startswith('8'): phone = '7' + phone[1:]
    if not re.fullmatch(r'[1-9][0-9]{7,14}', phone): raise ValueError('Укажи телефон с кодом страны')
    salt = secrets.token_hex(16)
    fingerprint = hashlib.sha256('\n'.join(('myengine-developer-v1', salt, player_id, last4, phone)).encode()).hexdigest()
    return dict(enabled=True, playerId=player_id, salt=salt, fingerprintSha256=fingerprint)


PRODUCT_FIELDS = ('productId','productTitle','description','amount','activationText')
MAX_PRODUCTS = 100


def normalize_product(value):
    if not isinstance(value, dict): raise ValueError('Товар должен быть объектом')
    v = value
    out = {}
    for key, limit in [('productTitle',100),('productId',100),('description',500),('activationText',2000)]:
        out[key] = text_field(v, key, limit, key != 'description')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', out['productId']): raise ValueError('ID товара: латинские буквы, цифры, . _ -')
    try:
        raw = str(v.get('amount','10.00')).strip().replace(',', '.')
        if not re.fullmatch(r'[0-9]{1,7}(?:\.[0-9]{1,2})?', raw): raise ValueError()
        amount = Decimal(raw)
        if not Decimal('0.01') <= amount <= Decimal('1000000'): raise ValueError()
    except (ValueError, InvalidOperation): raise ValueError('Цена: от 0,01 до 1 000 000 рублей, не больше двух знаков после запятой') from None
    out['amount'] = f'{amount:.2f}'
    # Stable short code identifies the product inside YooMoney's 64-character label.
    out['paymentCode'] = hashlib.sha256(out['productId'].encode()).hexdigest()[:10]
    return out


def normalize(value=None, *, publish=False):
    v = DEFAULTS if value is None else value
    if not isinstance(v, dict): raise ValueError('Коммерческие настройки должны быть объектом')
    if v.get('format', 1) not in (1,2): raise ValueError('Неизвестный формат коммерческих настроек')
    out = {'format': 2}
    for key, limit in [('gameName',80),('sellerName',100),('receiver',24),('supportUrl',500),('siteUrl',1000)]:
        out[key] = text_field(v, key, limit, key == 'gameName')
    raw_products = v.get('products') if 'products' in v else [v]
    if not isinstance(raw_products, list) or not 1 <= len(raw_products) <= MAX_PRODUCTS:
        raise ValueError(f'В каталоге должно быть от 1 до {MAX_PRODUCTS} товаров')
    products = [normalize_product(item) for item in raw_products]
    if len({item['productId'] for item in products}) != len(products): raise ValueError('ID каждого товара должен быть уникальным')
    if len({item['paymentCode'] for item in products}) != len(products): raise ValueError('Совпали короткие коды товаров. Измени один из ID')
    out['products'] = products
    # Legacy aliases always reflect the first/default product, not separate editable values.
    out.update({key:products[0][key] for key in PRODUCT_FIELDS})
    if out['receiver'] and not re.fullmatch(r'4100[0-9]{7,16}', out['receiver']): raise ValueError('Неверный номер кошелька ЮMoney')
    support = out['supportUrl']
    if support:
        if support.startswith('mailto:'):
            if not re.fullmatch(r'mailto:[^\s@?&#]+@[^\s@?&#]+\.[^\s@?&#]+', support): raise ValueError('Неверный email поддержки')
        else: https_address(support)
    if out['siteUrl']:
        https_address(out['siteUrl'])
        parts = urlsplit(out['siteUrl'])
        if parts.query or parts.fragment: raise ValueError('Адрес сайта должен быть без ?параметров и #фрагмента')
    if type(v.get('paymentsEnabled',True)) is not bool: raise ValueError('paymentsEnabled должен быть true или false')
    out['paymentsEnabled'] = v.get('paymentsEnabled', True)
    out['developerAccess'] = developer_settings(v.get('developerAccess', {'enabled':False}))
    if publish and (not out['receiver'] or not support): raise ValueError('Перед экспортом укажи кошелёк ЮMoney и контакт поддержки')
    return out


def load(root):
    path = Path(root) / '.myengine/commerce.json'
    return normalize(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else None)

class CatalogDraft:
    """Editor catalog with validation before each change; no disk writes."""
    def __init__(self, products):
        self.products = normalize({'products':products})['products']
    def update(self, index, value):
        candidate = normalize_product(value)
        if any(i!=index and p['productId']==candidate['productId'] for i,p in enumerate(self.products)):
            raise ValueError('Такой ID товара уже есть в каталоге')
        items = list(self.products); items[index] = candidate
        self.products = normalize({'products':items})['products']
    def add(self, copy_index=None):
        if len(self.products)>=MAX_PRODUCTS: raise ValueError(f'Максимум {MAX_PRODUCTS} товаров')
        used={p['productId'] for p in self.products};n=1
        while 'product_'+str(n) in used:n+=1
        item = dict(self.products[copy_index]) if copy_index is not None else dict(DEFAULTS)
        item['productId']='product_'+str(n)
        item['productTitle']=('Копия: '+item['productTitle'])[:100] if copy_index is not None else 'Новый товар'
        self.products.append(normalize_product(item));return len(self.products)-1
    def remove(self, index):
        if len(self.products)==1: raise ValueError('В каталоге должен остаться хотя бы один товар')
        del self.products[index];return min(index,len(self.products)-1)


def save(root, value):
    value = normalize(value)
    atomic_json(Path(root) / '.myengine/commerce.json', value)
    return value


def import_settings(path):
    """Read only JSON from a known config wrapper. Never execute imported JS."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            matches = [i for i in archive.infolist() if Path(i.filename).name == 'config.js' and 'dist' not in Path(i.filename).parts]
            if len(matches) != 1: raise ValueError('В архиве должен быть один исходный config.js')
            if matches[0].file_size > 1024*1024: raise ValueError('Слишком большой config.js')
            raw = archive.read(matches[0]).decode('utf-8-sig')
    else:
        if path.stat().st_size > 1024*1024: raise ValueError('Слишком большой файл настроек')
        raw = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.json': data = json.loads(raw)
    else:
        match = re.fullmatch(r'\s*(?:/\*[\s\S]*?\*/\s*)?window\.MYENGINE_CONFIG\s*=\s*Object\.freeze\(\s*(\{[\s\S]*\})\s*\);?\s*', raw)
        if not match: raise ValueError('Ожидается config.js с JSON внутри Object.freeze; исполняемый код не импортируется')
        data = json.loads(match[1])
    if not isinstance(data, dict): raise ValueError('Ожидается объект настроек')
    if 'gameName' not in data: data = {**DEFAULTS, 'gameName':'MyEngine', 'productTitle':'Deluxe', **data}
    return normalize(data)


def public_config(value):
    return {key:value[key] for key in ('format','gameName','sellerName','productId','productTitle','description','amount','receiver','supportUrl','activationText','paymentsEnabled','developerAccess','products')}


def generate_files(value):
    value = normalize(value, publish=True)
    config = json.dumps(public_config(value), ensure_ascii=True, indent=2).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    tokens = dict(GAME=value['gameName'], TITLE=value['productTitle'], PRODUCT=value['productId'],
        DESCRIPTION=value['description'], SELLER=value['sellerName'], AMOUNT=value['amount'],
        PRICE=value['amount'].rstrip('0').rstrip('.') if '.' in value['amount'] else value['amount'])
    template = (TEMPLATE/'index.html').read_text(encoding='utf-8')
    catalog = []
    for item in value['products']:
        ident = html.escape(item['productId'], quote=True)
        title = html.escape(item['productTitle'], quote=True)
        description = html.escape(item['description'], quote=True)
        price = item['amount'].rstrip('0').rstrip('.')
        catalog.append(f'<a class="catalog-card" data-catalog-product="{ident}" href="?product={ident}#checkout"><span class="catalog-id">{ident}</span><h3>{title}</h3><p>{description}</p><strong>{price} ₽ <span aria-hidden="true">↗</span></strong></a>')
    tokens['COUNT'] = str(len(value['products']))
    rendered = re.sub(r'\{\{([A-Z]+)\}\}', lambda m: ''.join(catalog) if m[1]=='CATALOG' else html.escape(tokens[m[1]], quote=True), template)
    files = {'index.html':rendered.encode(), 'config.js':('window.MYENGINE_CONFIG = Object.freeze('+config+');\n').encode()}
    for name in PUBLIC_FILES + EXTRA_FILES: files[name] = (TEMPLATE/name).read_bytes()
    files['render.yaml'] = ('''services:
  - type: web
    name: myengine-payment-site
    runtime: static
    buildCommand: node scripts/build-static.mjs
    staticPublishPath: ./dist
    autoDeployTrigger: commit
    envVars:
      - key: SKIP_INSTALL_DEPS
        value: "true"
''').encode()
    catalog_info = '\n'.join(f"{p['productId']} — {p['productTitle']} — {p['amount']} RUB — код {p['paymentCode']}" for p in value['products'])
    files['README.txt'] = (f'''Сайт: {value['gameName']}
Каталог:
{catalog_info}

1. Загрузи содержимое архива в репозиторий GitHub.
2. Render → New → Static Site → выбери этот репозиторий.
   Build Command: node scripts/build-static.mjs
   Publish Directory: dist
   Root Directory пустой, если файлы в корне репозитория.
3. В MyEngine → Коммерция / генератор сайта вставь полученный HTTPS-адрес
   и нажми «Сохранить и подключить сайт к кнопкам».
4. Для кнопки UI Blueprint выбери «Создать транзакцию», product={value['productId']}.
   key — любое уникальное имя, например deluxe_order. В Play откроется сайт.

Один адрес сайта обслуживает весь каталог. На странице игрок может выбрать товар.
Для каждой игровой кнопки укажи свой product и отдельный key.
Прямая ссылка: ?product=ID_товара#checkout. Неизвестный ID блокирует оплату.
После изменения каталога повторно экспортируй сайт, обнови репозиторий и
нажми «Подключить сайт к кнопкам», чтобы обновить список ID в игре.
Сумма и получатель задаются config.js, параметры ссылки их не меняют.
Из игры метка ME-<код товара>-<requestId> связывает перевод с запросом.
Без игры: MP-<код товара>-<ID игрока>-<случайная часть>.
Коды товаров перечислены выше и не меняются при перестановке каталога.
ID игрока остаётся в инструкции после возврата: передай его поддержке
вместе с меткой и номером операции, если метка содержит requestId.

Обычная активация ручная. Возврат с ЮMoney не подтверждает платёж.
Transaction start получает состояние manual; Transaction paid once не срабатывает.
Автоматическая проверка подключается отдельно через checkoutApi (TRANSACTIONS_R12.txt).
Адрес статического сайта нельзя записывать в checkoutApi.

Сертификат разработчика: бесплатная локальная выдача, payment.status=not_required.
Это JSON без подписи, не банковская квитанция.
В MyEngine R19 его можно загрузить через кнопку «Загрузить сертификат» / CertificateImport.
Укажи тот же product и key, что у покупки. Доступ проверяется TransactionHasAccess,
а succeeded и TransactionPaidOnce остаются только для серверного подтверждения оплаты.
Настройки доступны в генераторе; tools/setup-developer.html также работает локально.
В Render публикуется только dist, вспомогательные файлы в него не входят.
Для изменения товара/цены снова экспортируй сайт и обнови репозиторий.

Документация:
https://render.com/docs/static-sites
https://render.com/docs/blueprint-spec
https://yoomoney.ru/docs/payment-buttons/using-api/forms
''').encode()
    return files


def export_zip(value, destination):
    destination = Path(destination)
    if destination.suffix.lower() != '.zip': raise ValueError('Экспортируй в файл .zip')
    files = generate_files(value)  # Validate everything before touching the destination.
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.payment-site-', suffix='.zip', dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items(): archive.writestr(name, content)
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return destination


def connect(root, value, *, connect_donation=True):
    """Keep existing API configuration; make static mode explicit."""
    from engine_transactions import settings
    value = normalize(value, publish=True)
    if not value['siteUrl']: raise ValueError('Сначала опубликуй сайт и укажи его HTTPS-адрес')
    path = Path(root)/'payments.json'
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    data = settings({**data, 'checkoutMode':'site', 'checkoutSite':value['siteUrl'], 'siteProduct':value['productId'], 'siteProducts':[p['productId'] for p in value['products']]})
    if connect_donation: data['donationUrl'] = value['siteUrl']
    atomic_json(path, data)
    return data
