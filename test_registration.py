"""No network, real credentials, or SMS. Run: python -m unittest -v"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import register_certificate as app


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'registry.sqlite'
        with sqlite3.connect(self.database) as connection:
            connection.execute('CREATE TABLE players(id TEXT PRIMARY KEY,phone TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)')
            connection.execute('CREATE TABLE certificates(id TEXT PRIMARY KEY,player TEXT NOT NULL,product TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)')
        self.url = 'postgresql://test:example@db.example.test/registry'
        self.phone = '+12025550123'
        self.value = {'schema': 'myengine-license/v1', 'licenseStatus': 'issued',
                      'grantType': 'developer', 'signature': None, 'payment': {'status': 'not_required'},
                      'issuedAt': '2026-01-01T00:00:00Z', 'playerId': 'owner',
                      'productId': 'deluxe', 'certificateId': 'DEV-example'}
        self.cert = {k: self.value[k] for k in ('playerId', 'productId', 'certificateId')}
        self.options = []

    @contextmanager
    def connect(self, url, **options):
        self.options.append(options)
        connection = sqlite3.connect(self.database)
        class Adapter:
            def execute(self, sql, args):
                return connection.execute(sql.replace('%s', '?'), args)
        try:
            with connection:
                yield Adapter()
        finally:
            connection.close()

    def rows(self, table):
        with sqlite3.connect(self.database) as connection:
            return connection.execute('SELECT * FROM ' + table).fetchall()

    def read(self, value):
        path = self.root / 'certificate.json'
        path.write_text(json.dumps(value), encoding='utf-8-sig')
        return app.read_certificate(path)

    def grant(self, **changes):
        return app.register(self.connect, self.url, {**self.cert, **changes}, self.phone)

    def test_issued_certificate_then_committed_registration(self):
        self.assertEqual(self.read(self.value), self.cert)
        self.assertEqual(self.grant(), self.cert)
        self.assertEqual(self.rows('players'), [('owner', self.phone, 1)])
        self.assertEqual(self.rows('certificates'), [('DEV-example', 'owner', 'deluxe', 1)])
        self.assertEqual(self.options[0]['sslmode'], 'require')

    def test_retry_same_certificate_does_not_duplicate(self):
        self.grant()
        self.grant()
        self.assertEqual(len(self.rows('players')), 1)
        self.assertEqual(len(self.rows('certificates')), 1)

    def test_phone_reassignment_is_rejected(self):
        self.grant()
        with self.assertRaisesRegex(ValueError, 'другим телефоном'):
            app.register(self.connect, self.url, self.cert, '+12025550999')
        self.assertEqual(self.rows('players'), [('owner', self.phone, 1)])

    def test_certificate_conflict_rolls_back_new_player(self):
        self.grant()
        with self.assertRaisesRegex(ValueError, 'другому игроку'):
            self.grant(playerId='another')
        self.assertEqual(self.rows('players'), [('owner', self.phone, 1)])
        self.assertEqual(self.rows('certificates'), [('DEV-example', 'owner', 'deluxe', 1)])

    def test_conflict_rolls_back_reactivation(self):
        self.grant()
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE players SET active=0 WHERE id='owner'")
        with self.assertRaises(ValueError):
            self.grant(productId='another')
        self.assertEqual(self.rows('players'), [('owner', self.phone, 0)])

    def test_author_can_explicitly_register_revoked_binding_again(self):
        self.grant()
        with sqlite3.connect(self.database) as connection:
            connection.execute('UPDATE players SET active=0')
            connection.execute('UPDATE certificates SET active=0')
        self.grant()
        self.assertEqual(self.rows('players')[0][2], 1)
        self.assertEqual(self.rows('certificates')[0][3], 1)

    def test_missing_schema_not_created(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute('DROP TABLE certificates')
        with self.assertRaises(sqlite3.OperationalError):
            self.grant()
        self.assertEqual(self.rows('players'), [])

    def test_unissued_expired_signed_and_non_certificate_files_rejected(self):
        for change in ({'schema': 'other'}, {'licenseStatus': 'revoked'},
                       {'signature': 'unknown'}, {'playerId': 'bad id'},
                       {'payment': {'status': 'succeeded'}}, {'expiresAt': '2026-01-02T00:00:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.read({**self.value, **change})

    def test_duplicate_fields_rejected(self):
        path = self.root / 'certificate.json'
        path.write_text('{"playerId":"owner","playerId":"other"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'повторяется'):
            app.read_certificate(path)

    def test_bad_url_and_ssl_override_rejected_before_connect(self):
        for url in ('https://myengine.onrender.com', 'postgres://user@host/db',
                    self.url + '?sslmode=disable', self.url + '?host=other', self.url + '#secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.register(self.connect, url, self.cert, self.phone)
        self.assertEqual(self.options, [])

    def test_stronger_tls_choice_preserved(self):
        app.register(self.connect, self.url + '?sslmode=verify-full', self.cert, self.phone)
        self.assertEqual(self.options[0]['sslmode'], 'verify-full')

    def test_connection_error_does_not_echo_credentials(self):
        error = RuntimeError('connection failed postgres://user:VERY_SECRET@db.example/database')
        self.assertNotIn('VERY_SECRET', app.friendly_error(error))


if __name__ == '__main__':
    unittest.main()
