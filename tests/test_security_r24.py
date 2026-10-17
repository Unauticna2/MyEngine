"""Audit privacy, certificate uniqueness and server authority. No external services."""
from concurrent.futures import ThreadPoolExecutor
import io,json
from unittest.mock import patch
from tests.test_identity_r20 import IdentityFixture,server,certificate
from tests.test_registration_r23 import registration,audit

class SecurityTests(IdentityFixture):
    def setUp(self):
        super().setUp();self.password='Owner-security-test-password'
        self.service.owner={'player':'test','phone':self.phone,'hash':server.password_hash(self.password)}
        self.reg=registration.Registration(self.service);self.service.registration=self.reg;self.security=self.service.security
        self.app=server.Application(self.service)
    def http(self,path,data=None,token='',address='192.0.2.10',ua='Mozilla/5.0 (Windows NT 10.0) Chrome/140.0.0.0',extra=None):
        raw=json.dumps(data).encode() if data is not None else b'';output=[]
        env={'PATH_INFO':path,'REQUEST_METHOD':'POST' if data is not None else 'GET','REMOTE_ADDR':address,'HTTP_USER_AGENT':ua,'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_AUTHORIZATION':'Bearer '+token}
        env.update(extra or {})
        response=b''.join(self.app(env,lambda s,h:output.append(s)))
        return int(output[0].split()[0]),json.loads(response)
    def login(self,address='192.0.2.10',device='a'*32,password=None):
        return self.http('/api/moderation/login',{'phone':self.phone,'password':password or self.password,'device':{'id':device,'name':'My PC'}},address=address)
    def pin_owner(self):
        r=self.create();self.service.send(r['id'],self.web(r),{'phone':self.phone});self.service.owner_password(r['id'],self.web(r),{'password':self.password});return r
    def test_owner_login_pins_only_after_password(self):
        r=self.create();self.service.send(r['id'],self.web(r),{'phone':self.phone})
        self.problem(403,self.service.owner_password,r['id'],self.web(r),{'password':'wrong-long-password'})
        with self.db.transaction() as tx:self.assertEqual(self.security.binding(tx)['certificate'],'')
        self.service.owner_password(r['id'],self.web(r),{'password':self.password})
        with self.db.transaction() as tx:self.assertEqual(self.security.binding(tx)['certificate'],self.cert['certificateId'])
        self.db.grant('test',self.phone,'deluxe','different-developer')
        self.problem(403,lambda:self.create(certificateId='different-developer'))
    def test_parallel_owner_certificates_have_only_one_winner(self):
        self.db.grant('test',self.phone,'deluxe','second')
        def pin(cid):
            try:
                with self.db.transaction() as tx:self.security.pin(tx,'test','deluxe',cid)
                return True
            except server.Problem:return False
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(pin,[self.cert['certificateId'],'second']))
        self.assertEqual(results.count(True),1)
    def test_legacy_verified_session_is_pinned_on_authorized_poll(self):
        r=self.create()
        with self.db.transaction() as tx:tx.execute("UPDATE sessions SET state='verified',expires=? WHERE id=?",(self.clock[0]+100,r['id']))
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'verified')
        with self.db.transaction() as tx:self.assertEqual(self.security.binding(tx)['certificate'],self.cert['certificateId'])
    def test_replacement_requires_owner_password_and_ends_old_sessions(self):
        r=self.pin_owner();token=self.login()[1]['token'];self.db.grant('test',self.phone,'deluxe','replacement')
        data={'certificateId':'replacement','productId':'deluxe','previousCertificateId':self.cert['certificateId'],'password':'wrong-password'}
        self.problem(403,self.security.replace_binding,token,data)
        data['password']=self.password;self.security.replace_binding(token,data)
        with self.db.transaction() as tx:self.assertEqual(tx.session(r['id'])['state'],'expired')
        self.problem(403,self.service.status,r['id'],r['pollToken'])
        self.problem(409,self.security.replace_binding,token,data)
    def test_nonowner_developer_claim_rejected_even_registered(self):
        self.db.grant('other','+12025550666','deluxe','other-cert')
        payload={'playerId':'other','certificateId':'other-cert','productId':'deluxe','clientNonce':'x','grantType':'developer'}
        status,result=self.http('/api/sessions',payload);self.assertEqual(status,403)
        with self.db.transaction() as tx:
            event=tx.one('SELECT * FROM security_events ORDER BY created DESC LIMIT 1')
            self.assertIn('developer_claim',json.loads(event['flags']));self.assertEqual(event['role'],'unverified')
    def test_public_developer_registration_rejected_and_audited(self):
        token=self.login()[1]['token'];self.reg.save_settings(token,{'mode':'approval','products':[],'recipient':'author@example.org'})
        data={'certificate':{**certificate(),'playerId':'intruder'},'phone':'+12025550777'}
        status,result=self.http('/api/registrations',data);self.assertEqual(status,403)
        events=self.security.overview(token)['events'];self.assertTrue(any('developer_claim_blocked' in e['flags'] for e in events))
    def test_journal_private_and_records_changes_without_secrets(self):
        self.assertEqual(self.http('/api/moderation/security')[0],403)
        first=self.login()[1];self.clock[0]+=1
        second=self.login(address='198.51.100.5',device='b'*32)[1]
        result=self.security.overview(second['token']);event=result['events'][0]
        self.assertIn('different_ip',event['flags']);self.assertIn('different_device',event['flags']);self.assertEqual(event['role'],'owner')
        encoded=json.dumps(result);self.assertNotIn(self.password,encoded);self.assertNotIn(first['token'],encoded);self.assertNotIn(second['token'],encoded);self.assertNotIn('b'*32,encoded)
        self.assertEqual(event['metadata']['deviceName'],'My PC');self.assertEqual(event['metadata']['os'],'Windows')
    def test_failed_login_does_not_poison_success_baseline(self):
        token=self.login()[1]['token'];self.clock[0]+=1
        self.assertEqual(self.login(address='198.51.100.5',device='b'*32,password='wrong-password-long')[0],403);self.clock[0]+=1
        self.login();event=self.security.overview(token)['events'][0]
        self.assertNotIn('different_ip',event['flags']);self.assertNotIn('different_device',event['flags'])
    def test_forwarded_ip_is_explicitly_untrusted_and_no_country_inference(self):
        status,result=self.http('/api/moderation/login',{'phone':self.phone,'password':self.password},extra={'HTTP_X_FORWARDED_FOR':'203.0.113.45, 10.0.0.1'})
        e=self.security.overview(result['token'])['events'][0]
        self.assertEqual(e['metadata']['peer'],'192.0.2.10');self.assertEqual(e['metadata']['ip'],'203.0.113.45');self.assertIn('ip_unverified',e['flags']);self.assertNotIn('country',e['metadata'])
    def test_unavailable_payment_is_unverified_claim_not_fraud_or_paid(self):
        token=self.login()[1]['token'];self.reg.save_settings(token,{'mode':'approval','products':[]})
        cert={**certificate(),'playerId':'new','certificateId':'new-cert','grantType':'purchase','payment':{'status':'paid'}}
        data={'certificate':cert,'phone':'+12025550777','paymentAvailability':'unavailable'}
        status,r=self.http('/api/registrations',data);self.assertEqual(status,200)
        pending=self.reg.overview(token)['requests'][0]
        self.assertFalse(pending['paymentVerified']);self.assertIn('payment_unavailable_reported',pending['flags']);self.assertNotIn('fraud',pending['flags'])
        self.problem(400,self.reg.decide,token,r['id'],'approve',{'accessReason':'purchase_reviewed'})
        self.reg.decide(token,r['id'],'approve',{'accessReason':'purchase_reviewed','paymentReference':'manually-checked-123'})
        with self.db.transaction() as tx:c=tx.one('SELECT * FROM registration_claims WHERE request_id=?',(r['id'],))
        self.assertEqual(c['decision_reason'],'purchase_reviewed')
    def test_journal_pagination_and_retention(self):
        token=self.login()[1]['token'];meta=audit.context({'REMOTE_ADDR':'192.0.2.10'},{})
        for _ in range(101):self.security.event('guest','unverified','player','session_request','denied',meta)
        first=self.security.overview(token);self.assertEqual(len(first['events']),100)
        second=self.security.overview(token,(first['next']['created'],first['next']['id']))
        self.assertFalse({e['id'] for e in first['events']}&{e['id'] for e in second['events']})
        self.clock[0]+=2592001;token=self.login()[1]['token'];self.assertEqual(len(self.security.overview(token)['events']),1)
    def test_logout_others_keeps_current_session(self):
        first=self.login()[1]['token'];second=self.login()[1]['token']
        self.assertEqual(self.http('/api/moderation/logout-others',{},second)[0],200)
        self.problem(403,self.reg.overview,first);self.reg.overview(second)
    def test_browser_confirmation_event_has_bound_player_and_role(self):
        r=self.create();self.service.send(r['id'],self.web(r),{'phone':self.phone})
        status,_=self.http('/api/sessions/'+r['id']+'/owner-password',{'password':self.password,'device':{'name':'Desktop','id':'c'*32}},self.web(r));self.assertEqual(status,200)
        with self.db.transaction() as tx:e=tx.one("SELECT * FROM security_events WHERE action='player_login'")
        self.assertEqual(e['actor'],'test');self.assertEqual(e['role'],'owner');self.assertEqual(e['result'],'verified')

    def test_expired_legacy_session_cannot_pin_certificate(self):
        r=self.create()
        with self.db.transaction() as tx:tx.execute("UPDATE sessions SET state='verified',expires=0 WHERE id=?",(r['id'],))
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'expired')
        with self.db.transaction() as tx:self.assertEqual(self.security.binding(tx)['certificate'],'')
    def test_audit_failure_is_visible_without_leaking_credentials(self):
        with patch.object(self.security,'event',side_effect=RuntimeError('test failure')),patch('builtins.print'):
            status,r=self.login()
        self.assertEqual(status,200);self.assertFalse(self.security.overview(r['token'])['auditHealthy'])

    def test_invalid_admin_token_is_not_reported_as_journal_failure(self):
        status,_=self.http('/api/moderation/logout-others',{},'x'*43)
        self.assertEqual(status,403);self.assertFalse(self.security.audit_failed)
