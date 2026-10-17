"""Registration boundaries; mail is drafted locally and SMS is a test fake."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch
from cryptography.fernet import Fernet
from tests.test_identity_r20 import IdentityFixture, server, certificate, PlayerIdentity, ImmediatePool
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('registration_tests',ROOT/'templates/player-identity/registration.py')
registration=importlib.util.module_from_spec(spec)
audit_spec=importlib.util.spec_from_file_location('security_audit_tests',ROOT/'templates/player-identity/security_audit.py')
audit=importlib.util.module_from_spec(audit_spec)
with patch.dict(sys.modules,{'identity_server':server}):audit_spec.loader.exec_module(audit)
with patch.dict(sys.modules,{'identity_server':server,'security_audit':audit}):spec.loader.exec_module(registration)
class RegistrationTests(IdentityFixture):
    def setUp(self):
        super().setUp();self.password='Owner-password-for-r23-tests'
        self.service.owner={'player':'owner','phone':'+12025550999','hash':server.password_hash(self.password)}
        self.reg=registration.Registration(self.service);self.service.registration=self.reg
        self.owner=self.reg.login({'phone':self.service.owner['phone'],'password':self.password},'admin')['token']
        self.newcert={**certificate(),'playerId':'new-player','certificateId':'new-cert','grantType':'purchase','payment':{'status':'unverified'}}
        self.data={'certificate':dict(self.newcert),'phone':'+12025550666','email':'player@example.org','note':'Let me in'}
    def mode(self,mode='approval',**extra):return self.reg.save_settings(self.owner,{'mode':mode,'products':['deluxe'],'notify':False,'recipient':'',**extra})
    def submit(self):return self.reg.submit(self.data,'applicant')
    def has_player(self):
        with self.db.transaction() as tx:return tx.one('SELECT * FROM players WHERE id=?',('new-player',))
    def test_default_closed_migration_preserves_existing_players(self):
        self.assertEqual(self.reg.public_config()['mode'],'closed');self.problem(403,self.submit)
        registration.Registration(self.service)
        self.assertEqual(self.create()['playerId'],'test')
    def test_approval_requires_admin_and_is_idempotent(self):
        self.mode();r=self.submit();self.assertIsNone(self.has_player());self.assertEqual(self.provider.sent,[])
        self.problem(403,self.reg.decide,r['token'],r['id'],'approve')
        for _ in range(2):self.assertEqual(self.reg.decide(self.owner,r['id'],'approve')['status'],'approved')
        self.assertEqual(self.has_player()['phone'],self.data['phone']);self.assertEqual(self.reg.status(r['id'],r['token'])['status'],'approved')
    def test_rejection_and_expiry_never_grant(self):
        self.mode();r=self.submit();self.reg.decide(self.owner,r['id'],'reject');self.problem(409,self.reg.decide,self.owner,r['id'],'approve');self.assertIsNone(self.has_player())
        self.data['certificate']['certificateId']='other-cert';r=self.submit();self.clock[0]+=604801
        self.owner=self.reg.login({'phone':self.service.owner['phone'],'password':self.password},'admin')['token']
        self.problem(409,self.reg.decide,self.owner,r['id'],'approve');self.assertIsNone(self.has_player())
    def test_public_cannot_claim_owner_or_paid_product(self):
        self.mode('automatic')
        for field,value in [('playerId','owner'),('productId','paid-secret')]:
            self.data['certificate']={**self.newcert,field:value};self.problem(403,self.submit)
        self.data['certificate']=self.newcert;self.data['phone']=self.service.owner['phone'];self.problem(403,self.submit);self.assertEqual(self.provider.sent,[])
    def test_automatic_requires_sms_before_grant(self):
        self.mode('automatic');r=self.submit();self.assertIsNone(self.has_player())
        self.problem(400,self.reg.check,r['id'],r['token'],{'code':'000000'});self.assertIsNone(self.has_player())
        self.reg.check(r['id'],r['token'],{'code':'123456'});self.assertIsNotNone(self.has_player())
    def test_five_failed_codes_lock_out_correct_code(self):
        self.mode('automatic');r=self.submit()
        for _ in range(5):self.problem(400,self.reg.check,r['id'],r['token'],{'code':'000000'})
        self.problem(429,self.reg.check,r['id'],r['token'],{'code':'123456'});self.assertIsNone(self.has_player())
    def test_policy_change_prevents_grant(self):
        self.mode('automatic');r=self.submit();self.mode('closed')
        self.problem(403,self.reg.check,r['id'],r['token'],{'code':'123456'});self.assertIsNone(self.has_player())
    def test_phone_gateway_uses_unchanged_android_protocol(self):
        gateway=server.PhoneGateway(self.db,server.digest('t'*43),Fernet.generate_key().decode(),now=lambda:self.clock[0]);self.service.provider=gateway
        gateway.claim('t'*43);self.mode('automatic');r=self.submit();job=gateway.claim('t'*43)['job']
        self.assertEqual(job['phone'],self.data['phone']);self.assertIsNone(gateway.claim('t'*43)['job'])
        self.reg.check(r['id'],r['token'],{'code':job['code']});self.assertIsNotNone(self.has_player())
    def test_offline_gateway_leaves_no_registration(self):
        self.service.provider=server.PhoneGateway(self.db,server.digest('t'*43),Fernet.generate_key().decode(),now=lambda:self.clock[0]);self.mode('automatic')
        self.problem(503,self.submit);self.assertIsNone(self.has_player())
        with self.db.transaction() as tx:self.assertEqual(tx.one('SELECT COUNT(*) n FROM registration_requests')['n'],0)
    def test_conflicting_concurrent_grant_rolls_back_player(self):
        self.mode();r=self.submit();self.db.grant('someone-else','+12025550777','deluxe','new-cert')
        self.problem(409,self.reg.decide,self.owner,r['id'],'approve');self.assertIsNone(self.has_player())
    def test_revoked_player_cannot_reregister(self):
        self.db.grant('new-player',self.data['phone'],'deluxe','blocked-cert')
        with self.db.transaction() as tx:tx.execute("UPDATE players SET active=0 WHERE id='new-player'")
        self.mode();self.problem(409,self.submit)
    def test_manual_email_draft_is_not_delivery_or_access(self):
        from urllib.parse import urlsplit,parse_qs,unquote
        self.mode(recipient='author+game@example.org');r=self.submit();draft=r['emailDraft']
        parsed=urlsplit(draft['href']);query=parse_qs(parsed.query)
        self.assertEqual(parsed.scheme,'mailto');self.assertEqual(unquote(parsed.path),'author+game@example.org')
        self.assertEqual(set(query),{'subject','body'});self.assertTrue(query['subject'][0].startswith('#verify'))
        self.assertEqual(query['body'][0],draft['body']);self.assertIn(r['id'],draft['body'])
        self.assertNotIn(r['token'],draft['body']);self.assertNotIn(self.owner,draft['body'])
        self.assertEqual(r['status'],'pending');self.assertIsNone(self.has_player());self.assertEqual(self.provider.sent,[])
        self.assertEqual(len(self.reg.overview(self.owner)['requests']),1)
        self.problem(404,self.reg.route,'POST','/api/moderation/'+r['id']+'/retry-mail',self.owner,{},'x')
    def test_existing_notification_setting_cannot_send_any_email(self):
        self.mode()
        with self.db.transaction() as tx:tx.execute("UPDATE registration_settings SET notify=1,recipient='' WHERE id=1")
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No mail network calls')):
            registration.Registration(self.service);r=self.submit()
        self.assertEqual(r['emailDraft']['to'],'alekandrza14@gmail.com');self.assertIsNone(self.has_player())
    def test_mail_header_injection_rejected_and_body_encoded(self):
        for recipient in ('a@example.org\r\nBcc: bad@example.org','a@example.org?bcc=bad@example.org'):
            with self.assertRaises(server.Problem):self.mode(recipient=recipient)
        self.mode();self.data['note']='Вопрос & bcc=other@example.org? #verify\nВторая строка'
        r=self.submit()
        from urllib.parse import urlsplit,parse_qs
        query=parse_qs(urlsplit(r['emailDraft']['href']).query)
        self.assertEqual(set(query),{'subject','body'});self.assertIn(self.data['note'],query['body'][0])
    def test_admin_auth_and_expiry(self):
        self.problem(403,self.reg.login,{'phone':self.service.owner['phone'],'password':'incorrect-password'},'bad')
        self.problem(403,self.reg.save_settings,'x'*43,{'mode':'closed'})
        self.clock[0]+=3601;self.problem(403,self.reg.overview,self.owner)
    def test_wsgi_metadata_and_static_routes(self):
        self.mode();app=server.Application(self.service)
        def call(path,body=None):
            raw=json.dumps(body).encode() if body else b'';status=[]
            output=b''.join(app({'PATH_INFO':path,'REQUEST_METHOD':'POST' if body else 'GET','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)},lambda s,h:status.append(s)))
            return int(status[0].split()[0]),output
        for path in ('/register','/register.js','/moderation','/moderation.js'):self.assertEqual(call(path)[0],200)
        status,raw=call('/api/sessions',{**{k:self.newcert[k] for k in ('playerId','productId','certificateId')},'clientNonce':'nonce'})
        self.assertEqual(status,403);self.assertEqual(json.loads(raw)['registrationUrl'],'https://players.example/register')
        self.assertEqual(call('/api/registrations',self.data)[0],200)
    def test_expiry_rejected(self):
        self.mode();self.data['certificate']['expiresAt']='2020-01-01T00:00:00Z';self.problem(400,self.submit)
    def test_duplicates_and_rate_limit(self):
        self.mode();self.submit();self.problem(409,self.submit)
        for n in range(3):self.data['certificate']['certificateId']='new-'+str(n);self.submit()
        self.data['certificate']['certificateId']='too-many';self.problem(429,self.submit)
class RegistrationClientTests(IdentityFixture):
    def test_same_server_registration_only_no_access_grant(self):
        from engine_player_identity import RegistrationRequired
        for origin,expected in [('https://players.example/register',True),('https://evil.example/register',False),('https://players.example/verify',False)]:
            client=PlayerIdentity(Path(self.tmp.name),'https://players.example',lambda *a:(_ for _ in ()).throw(RegistrationRequired('register',origin)),log=lambda x:None)
            client.pool.shutdown();client.pool=ImmediatePool()
            with patch('engine_player_identity.open_url') as opened:
                client.start(self.cert,'purchase');client.update();self.assertEqual(opened.called,expected)
                if expected:self.assertIn('#certificate=',opened.call_args[0][0])
                self.assertFalse(client.has_access('purchase'))
            client.close()
