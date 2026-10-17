"""Local, unsigned license activation. Never a bank/payment confirmation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from engine_scene import atomic_json

MAX_CERTIFICATE = 65536
MAX_STORE = 524288


def identifier(value, label, limit=100):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,'+str(limit)+'}', value):
        raise ValueError('Некорректное поле '+label)
    return value


def transaction_key(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 100 or any(ord(c) < 32 for c in value):
        raise ValueError('Некорректный ключ операции key')
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Повторяющееся поле JSON: '+key)
        result[key] = value
    return result


def read_json(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Файл слишком большой')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Некорректное число JSON')))
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Файл должен содержать JSON в UTF-8') from error


def _date(value, label):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Некорректная дата '+label)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Некорректная дата '+label) from error
    if parsed.tzinfo is None:
        raise ValueError('В дате '+label+' нужен часовой пояс')
    return parsed


def validate_certificate(value, product, player_id=''):
    """Validate structure/selection, not issuer identity or payment claims."""
    identifier(product, 'product')
    if player_id:
        identifier(player_id, 'playerId', 32)
    if not isinstance(value, dict) or value.get('schema') != 'myengine-license/v1':
        raise ValueError('Нужен сертификат myengine-license/v1 в формате JSON')
    if value.get('productId') != product:
        raise ValueError('Сертификат другого товара. Ожидается: '+product)
    if value.get('licenseStatus') != 'issued':
        raise ValueError('Сертификат не выдан или отозван')
    if value.get('grantType') not in ('developer', 'purchase', 'manual'):
        raise ValueError('Неизвестный тип сертификата')
    if value.get('signature') is not None:
        raise ValueError('Для этого подписанного сертификата нужен соответствующий проверяющий модуль')
    ident = identifier(value.get('certificateId'), 'certificateId', 128)
    player = identifier(value.get('playerId'), 'playerId', 32)
    if player_id and player != player_id:
        raise ValueError('Сертификат другого игрока. Ожидается: '+player_id)
    issued = _date(value.get('issuedAt'), 'issuedAt')
    expires = value.get('expiresAt')
    if expires is not None:
        expiry = _date(expires, 'expiresAt')
        if expiry <= issued or expiry <= datetime.now(timezone.utc):
            raise ValueError('Срок действия сертификата истёк')
    payment = value.get('payment')
    if not isinstance(payment, dict) or not isinstance(payment.get('status'), str):
        raise ValueError('Отсутствует описание payment')
    if value['grantType'] == 'developer' and payment['status'] != 'not_required':
        raise ValueError('Сертификат разработчика должен иметь payment.status=not_required')
    # Persist only bounded, inert fields. No provider/user-supplied verification
    # flags or monetary claims are trusted or promoted to transaction success.
    result = {'schema': 'myengine-license/v1', 'certificateId': ident,
              'productId': product, 'playerId': player, 'issuedAt': value['issuedAt'],
              'grantType': value['grantType'], 'licenseStatus': 'issued', 'signature': None,
              'payment': {'status': 'not_required' if value['grantType'] == 'developer' else 'unverified'}}
    for name in ('product', 'edition'):
        text = value.get(name, product)
        if not isinstance(text, str) or not 1 <= len(text) <= 200 or any(ord(c) < 32 for c in text):
            raise ValueError('Некорректное поле '+name)
        result[name] = text
    if expires is not None:
        result['expiresAt'] = expires
    return result


def read_certificate(path, product, player_id=''):
    return validate_certificate(read_json(path, MAX_CERTIFICATE), product, player_id)


class CertificateStore:
    def __init__(self, root):
        # Per local installation; never packaged into Data or the project ZIP.
        scope = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode('utf-8')).hexdigest()
        base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local/share'))
        self.path = base/'MyEngine2/Certificates'/f'{scope}.json'
        self.entries = {}; self.load_error = ''
        if self.path.exists():
            try:
                data = read_json(self.path, MAX_STORE)
                if not isinstance(data, dict) or data.get('format') != 1 or not isinstance(data.get('grants'), dict) or len(data['grants']) > 100:
                    raise ValueError('Неверный формат хранилища активаций')
                for key, cert in data['grants'].items():
                    transaction_key(key)
                    if not isinstance(cert, dict):
                        raise ValueError('Неверная запись активации')
                    # One expired/invalid grant must not discard unrelated products.
                    try:
                        self.entries[key] = validate_certificate(cert, cert.get('productId'))
                    except ValueError:
                        continue
            except (OSError, ValueError, TypeError) as error:
                self.entries = {}; self.load_error = str(error)

    def has(self, key, products, product=None):
        certificate = self.entries.get(key)
        if not certificate or certificate['productId'] not in products:
            return False
        if product is not None and product != certificate['productId']:
            return False
        expires = certificate.get('expiresAt')
        return expires is None or _date(expires, 'expiresAt') > datetime.now(timezone.utc)

    def activate(self, key, certificate):
        transaction_key(key)
        certificate = validate_certificate(certificate, certificate.get('productId'))
        old = self.entries.get(key)
        if old and old['productId'] != certificate['productId']:
            raise ValueError('Этот key уже связан с другим товаром. Укажи отдельный key.')
        if not old and len(self.entries) >= 100:
            raise ValueError('Достигнут предел: 100 локальных активаций')
        updated = {**self.entries, key: certificate}
        atomic_json(self.path, {'format': 1, 'grants': updated})
        self.entries = updated  # An unwritable store must not grant transient access.

