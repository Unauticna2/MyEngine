"""Registered-player OTP queue and owner password: no carrier calls in tests."""
from concurrent.futures import ThreadPoolExecutor
import io,json,secrets
from pathlib import Path
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from tests.test_identity_r20 import IdentityFixture,server

class GatewayTests(IdentityFixture):
    def setUp(self):
        super().setUp();self.token=secrets.token_urlsafe(32);self.key=Fernet.generate_key().decode()
        self.gateway=server.PhoneGateway(self.db,server.digest(self.token),self.key,now=lambda:self.clock[0])
        self.service.provider=self.gateway
        self.gateway.claim(self.token)  # Online heartbeat, no SMS.
    def queued(self):
        r=self.create();result=self.service.send(r['id'],self.web(r),{'phone':self.phone})
        self.assertEqual(result['status'],'queued');return r
    def test_job_contains_only_generated_code_and_is_claimed_once(self):
        r=self.queued();a=self.gateway.claim(self.token)['job'];b=self.gateway.claim(self.token)['job']
        self.assertIsNone(b);self.assertRegex(a['code'],r'^[0-9]{6}$');self.assertEqual(a['phone'],self.phone)
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'pending')
        with self.db.transaction() as tx:row=tx.one('SELECT * FROM sms_jobs WHERE id=?',(a['id'],))
        self.assertEqual(row['otp_cipher'],'');self.assertNotEqual(row['otp_hash'],server.digest(a['code']))
    def test_claim_race_has_only_one_winner(self):
        self.queued()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.gateway.claim(self.token),range(2)))
        self.assertEqual(sum(x['job'] is not None for x in results),1)
    def test_sms_sent_result_does_not_verify_player(self):
        r=self.queued();job=self.gateway.claim(self.token)['job']
        self.gateway.acknowledge(self.token,job['id'],{'claimToken':job['claimToken'],'status':'sent'})
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'pending')
        wrong='000000' if job['code']!='000000' else '999999'
        self.problem(400,self.service.check,r['id'],self.web(r),{'code':wrong})
        self.service.check(r['id'],self.web(r),{'code':job['code']})
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'verified')
        self.assertFalse(self.gateway.check('GQ-'+job['id'],job['code'],self.phone))
    def test_wrong_gateway_and_claim_tokens_never_read_or_ack(self):
        r=self.queued()
        for token in ('',r['pollToken'],self.web(r),'x'*43):self.problem(403,self.gateway.claim,token)
        job=self.gateway.claim(self.token)['job']
        self.problem(403,self.gateway.acknowledge,self.token,job['id'],{'claimToken':'x'*43,'status':'sent'})
    def test_five_wrong_codes_then_right_code_stays_denied(self):
        r=self.queued();job=self.gateway.claim(self.token)['job'];wrong='000000' if job['code']!='000000' else '999999'
        for _ in range(5):self.problem(400,self.service.check,r['id'],self.web(r),{'code':wrong})
        self.problem(429,self.service.check,r['id'],self.web(r),{'code':job['code']})
    def test_offline_phone_does_not_enqueue_and_owner_can_still_use_password(self):
        self.clock[0]+=91;r=self.create()
        self.problem(503,self.service.send,r['id'],self.web(r),{'phone':self.phone})
        with self.db.transaction() as tx:self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM sms_jobs')['n'],0)
    def test_cancel_old_code_on_resend(self):
        r=self.queued();old=self.gateway.claim(self.token)['job'];self.clock[0]+=61;self.gateway.claim(self.token)
        self.service.send(r['id'],self.web(r),{'phone':self.phone});new=self.gateway.claim(self.token)['job']
        self.assertNotEqual(old['id'],new['id']);self.assertFalse(self.gateway.check('GQ-'+old['id'],old['code'],self.phone))
        self.service.check(r['id'],self.web(r),{'code':new['code']})
    def test_revocation_stops_queued_and_claimed_jobs(self):
        self.queued()
        with self.db.transaction() as tx:tx.execute('UPDATE players SET active=0')
        self.assertIsNone(self.gateway.claim(self.token)['job'])
        self.db.grant('test',self.phone,'deluxe',self.cert['certificateId']);self.clock[0]+=61
        r=self.queued();job=self.gateway.claim(self.token)['job']
        with self.db.transaction() as tx:tx.execute('UPDATE certificates SET active=0')
        self.problem(403,self.service.check,r['id'],self.web(r),{'code':job['code']})
    def test_expired_failed_and_wrong_phone_codes_fail(self):
        r=self.queued();job=self.gateway.claim(self.token)['job']
        self.assertFalse(self.gateway.check('GQ-'+job['id'],job['code'],'+12025550999'))
        self.gateway.acknowledge(self.token,job['id'],{'claimToken':job['claimToken'],'status':'failed'})
        self.problem(400,self.service.check,r['id'],self.web(r),{'code':job['code']})
        self.clock[0]+=301;self.assertFalse(self.gateway.check('GQ-'+job['id'],job['code'],self.phone))
    def test_dispatch_uncertainty_can_be_verified_but_not_resent(self):
        r=self.queued();job=self.gateway.claim(self.token)['job']
        self.gateway.acknowledge(self.token,job['id'],{'claimToken':job['claimToken'],'status':'unknown'})
        self.assertIsNone(self.gateway.claim(self.token)['job'])
        self.service.check(r['id'],self.web(r),{'code':job['code']})
    def test_disabled_gateway_cannot_claim_more_jobs(self):
        self.queued();self.service.enabled=False
        self.problem(503,self.service.gateway,self.token)
    def test_wsgi_phone_gateway_route_and_no_arbitrary_send_endpoint(self):
        self.queued();app=server.Application(self.service)
        def post(path,token,data={}):
            raw=json.dumps(data).encode();status=[]
            body=b''.join(app({'PATH_INFO':path,'REQUEST_METHOD':'POST','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_AUTHORIZATION':'Bearer '+token},lambda s,h:status.append(s)))
            return int(status[0].split()[0]),json.loads(body)
        code,result=post('/api/gateway/claim',self.token);self.assertEqual(code,200);self.assertIn('code',result['job'])
        self.assertEqual(post('/api/gateway/send',self.token,{'phone':'+12025550999','text':'not allowed'})[0],404)

class OwnerTests(IdentityFixture):
    def setUp(self):
        super().setUp();self.password='Only-owner-test-password-21'
        self.service.owner={'player':'test','phone':self.phone,'hash':server.password_hash(self.password)}
    def password_session(self):
        r=self.create();self.assertEqual(self.service.send(r['id'],self.web(r),{'phone':self.phone}),{'status':'owner_password'});return r
    def test_matching_owner_number_requires_password_without_sms(self):
        r=self.password_session();self.assertEqual(self.provider.sent,[])
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'pending')
        self.problem(403,self.service.owner_password,r['id'],self.web(r),{'password':'wrong-password-123'})
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'pending')
        self.service.owner_password(r['id'],self.web(r),{'password':self.password})
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'verified');self.assertEqual(self.provider.sent,[])
    def test_owner_without_sms_provider_and_no_phone_online(self):
        self.service.enabled=False;self.service.provider=None;r=self.password_session()
        self.service.owner_password(r['id'],self.web(r),{'password':self.password})
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'verified')
    def test_number_match_for_other_player_does_not_enable_owner_login(self):
        self.db.grant('stranger',self.phone,'deluxe','CERT-other')
        r=self.create(playerId='stranger',certificateId='CERT-other')
        self.problem(403,self.service.send,r['id'],self.web(r),{'phone':self.phone})
        self.problem(403,self.service.owner_password,r['id'],self.web(r),{'password':self.password})
        self.assertEqual(self.provider.sent,[])
    def test_wrong_number_or_unregistered_certificate_stays_denied(self):
        r=self.create();self.problem(403,self.service.send,r['id'],self.web(r),{'phone':'+12025550999'})
        self.problem(403,self.service.owner_password,r['id'],self.web(r),{'password':self.password})
        self.problem(403,lambda:self.create(certificateId='invented'))
    def test_global_password_limit_survives_new_sessions_and_wrong_attempts(self):
        a=self.password_session()
        for _ in range(5):self.problem(403,self.service.owner_password,a['id'],self.web(a),{'password':'wrong-password-123'})
        b=self.password_session();self.problem(429,self.service.owner_password,b['id'],self.web(b),{'password':self.password})
        self.assertEqual(self.service.status(b['id'],b['pollToken'])['status'],'pending')
    def test_password_hash_is_salted_and_does_not_contain_plain_password(self):
        a=server.password_hash(self.password);b=server.password_hash(self.password)
        self.assertNotEqual(a,b);self.assertNotIn(self.password,a);self.assertTrue(server.password_matches(self.password,a))
        self.assertFalse(server.password_matches(self.password.upper(),a));self.assertFalse(server.password_matches(self.password,'scrypt$999999999999$8$1$bad$bad'))
    def test_owner_revocation_expiry_and_browser_token_required(self):
        r=self.password_session();self.problem(403,self.service.owner_password,r['id'],r['pollToken'],{'password':self.password})
        self.clock[0]+=601;self.problem(403,self.service.owner_password,r['id'],self.web(r),{'password':self.password})
        with self.db.transaction() as tx:tx.execute('UPDATE players SET active=0')
        self.problem(403,self.service.status,r['id'],r['pollToken'])
    def test_server_export_does_not_package_private_setup_files(self):
        from engine_identity_ui import export_server
        import zipfile
        root=Path(self.tmp.name)/'template';root.mkdir()
        (root/'identity_server.py').write_text('# source')
        (root/'private-config').mkdir();(root/'private-config/phone-token.txt').write_text('secret')
        (root/'.env').write_text('secret');(root/'registry.db').write_text('secret')
        target=Path(self.tmp.name)/'server.zip'
        with patch('engine_identity_ui.TEMPLATE',root):export_server(target)
        with zipfile.ZipFile(target) as z:self.assertEqual(z.namelist(),['identity_server.py'])

if __name__=='__main__':unittest.main()
