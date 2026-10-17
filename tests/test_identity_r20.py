"""No real SMS: exercise the server, client and generated entry gate together."""
from concurrent.futures import Future
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

from engine_blueprints import generated_source
from engine_certificates import CertificateStore
from engine_player_identity import PlayerIdentity
from engine_transactions import Transactions,settings
from engine_ui_blueprints import click_graph
from tests.test_certificates_r19 import certificate

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('identity_server_tests',ROOT/'templates/player-identity/identity_server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

class Provider:
    def __init__(self):self.sent=[];self.checked=[];self.fail=False
    def send(self,number):
        self.sent.append(number)
        if self.fail:raise server.Problem(502,'Unavailable')
        return 'VE'+'0'*32
    def check(self,sid,code,number):
        self.checked.append((sid,code,number))
        return code=='123456'

class ImmediatePool:
    def submit(self,fn,*args):
        f=Future()
        try:f.set_result(fn(*args))
        except Exception as error:f.set_exception(error)
        return f
    def shutdown(self,**kwargs):pass

class IdentityFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=server.Database(str(Path(self.tmp.name)/'registry.sqlite'));self.db.initialize()
        self.provider=Provider();self.clock=[int(time.time())]
        self.service=server.IdentityService(self.db,self.provider,'https://players.example',enabled=True,now=lambda:self.clock[0])
        self.cert=certificate();self.phone='+12025550123'
        self.db.grant('test',self.phone,'deluxe',self.cert['certificateId'])
    def create(self,**changes):
        return self.service.create({**{k:self.cert[k] for k in ('playerId','productId','certificateId')},'clientNonce':'a'*32,**changes},'test-remote')
    def web(self,result):return result['verificationUrl'].split('#')[1].split('.')[1]
    def problem(self,status,fn,*args):
        with self.assertRaises(server.Problem) as caught:fn(*args)
        self.assertEqual(caught.exception.status,status)
    def verified(self):
        r=self.create();self.service.send(r['id'],self.web(r),{'phone':self.phone})
        self.service.check(r['id'],self.web(r),{'code':'123456'});return r

class ServerTests(IdentityFixture):
    def test_unknown_player_and_wrong_certificate_never_send_sms(self):
        for change in ({'playerId':'stranger'},{'productId':'other'},{'certificateId':'invented'}):
            self.problem(403,lambda:self.create(**change))
        self.assertEqual(self.provider.sent,[])
    def test_phone_then_otp_then_exact_registered_binding(self):
        r=self.create();self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'pending')
        self.problem(403,self.service.send,r['id'],self.web(r),{'phone':'+12025550999'})
        self.assertEqual(self.provider.sent,[])
        self.service.send(r['id'],self.web(r),{'phone':self.phone})
        self.problem(400,self.service.check,r['id'],self.web(r),{'code':'000000'})
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'pending')
        self.service.check(r['id'],self.web(r),{'code':'123456'})
        status=self.service.status(r['id'],r['pollToken'])
        self.assertEqual(status['status'],'verified');self.assertEqual(status['playerId'],'test')
        self.assertEqual(status['certificateId'],self.cert['certificateId']);self.assertNotIn('phone',status)
    def test_token_roles_and_sessions_cannot_be_swapped(self):
        a=self.create();b=self.create()
        self.problem(403,self.service.status,a['id'],self.web(a))
        self.problem(403,self.service.send,a['id'],a['pollToken'],{'phone':self.phone})
        self.problem(403,self.service.status,a['id'],b['pollToken'])
    def test_five_bad_codes_are_counted_across_requests(self):
        r=self.create();self.service.send(r['id'],self.web(r),{'phone':self.phone})
        for _ in range(5):self.problem(400,self.service.check,r['id'],self.web(r),{'code':'000000'})
        self.problem(429,self.service.check,r['id'],self.web(r),{'code':'123456'})
        self.assertEqual(len(self.provider.checked),5)
    def test_failed_send_is_still_rate_limited(self):
        r=self.create();self.provider.fail=True
        self.problem(502,self.service.send,r['id'],self.web(r),{'phone':self.phone})
        self.problem(429,self.service.send,r['id'],self.web(r),{'phone':self.phone})
        self.assertEqual(len(self.provider.sent),1)
    def test_wrong_phone_attempt_limit_survives_rollback(self):
        r=self.create()
        for _ in range(8):self.problem(403,self.service.send,r['id'],self.web(r),{'phone':'+12025550999'})
        self.problem(429,self.service.send,r['id'],self.web(r),{'phone':self.phone})
        self.assertEqual(self.provider.sent,[])
    def test_revocation_applies_to_already_verified_session(self):
        r=self.verified()
        with self.db.transaction() as tx:tx.execute('UPDATE certificates SET active=0 WHERE id=?',(self.cert['certificateId'],))
        self.problem(403,self.service.status,r['id'],r['pollToken'])
    def test_expiry_and_no_otp_replay(self):
        r=self.verified()
        self.problem(400,self.service.check,r['id'],self.web(r),{'code':'123456'})
        self.clock[0]+=43201
        self.assertEqual(self.service.status(r['id'],r['pollToken'])['status'],'expired')
        self.problem(400,self.service.send,r['id'],self.web(r),{'phone':self.phone})
    def test_no_silent_phone_or_certificate_reassignment(self):
        with self.assertRaises(ValueError):self.db.grant('test','+12025550999','deluxe','another')
        with self.assertRaises(ValueError):self.db.grant('another',self.phone,'deluxe',self.cert['certificateId'])
    def test_twilio_approved_response_must_match_phone_and_service(self):
        adapter=server.TwilioVerify('AC'+'0'*32,'secret','VA'+'1'*32)
        good={'status':'approved','to':self.phone,'service_sid':adapter.service}
        for change,expected in [({},True),({'status':'pending'},False),({'to':'+12025550999'},False),({'service_sid':'VA'+'2'*32},False)]:
            with patch.object(adapter,'call',return_value={**good,**change}):self.assertEqual(adapter.check('VE'+'0'*32,'123456',self.phone),expected)
    def test_sms_disabled_and_wsgi_boundaries(self):
        app=server.Application(self.service)
        def call(path,method='GET',data=None,token=''):
            raw=json.dumps(data).encode() if data is not None else b'';response=[]
            body=b''.join(app({'PATH_INFO':path,'REQUEST_METHOD':method,'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),
                'wsgi.input':io.BytesIO(raw),'HTTP_AUTHORIZATION':'Bearer '+token},lambda status,headers:response.extend([status,dict(headers)])))
            return response,body
        response,body=call('/verify');self.assertEqual(response[0],'200 OK');self.assertIn('frame-ancestors',response[1]['Content-Security-Policy'])
        self.assertEqual(call('/../manage.py')[0][0],'404 Not Found')
        self.assertEqual(call('/api/sessions','POST',{'x':'a'*4096})[0][0],'413 Payload Too Large')
        self.service.enabled=False;self.problem(503,self.create)
        self.assertEqual(self.provider.sent,[])

class ClientTests(IdentityFixture):
    def setUp(self):
        super().setUp()
        env=patch.dict(os.environ,{'LOCALAPPDATA':str(Path(self.tmp.name)/'appdata')});env.start();self.addCleanup(env.stop)
        self.root=Path(self.tmp.name)/'game';self.root.mkdir()
        self.open=patch('engine_player_identity.open_url');self.opened=self.open.start();self.addCleanup(self.open.stop)
    def client(self):
        def request(url,body=None,token=None):
            if body is not None:return self.service.create(body,'client')
            return self.service.status(url.rsplit('/',1)[1],token)
        client=PlayerIdentity(self.root,'https://players.example',request,lambda x:None)
        client.pool.shutdown();client.pool=ImmediatePool();self.addCleanup(client.close);return client
    def poll(self,client):
        for record in client.sessions.values():record['next']=0
        client.update();client.update()
    def authorize(self,client):
        client.start(self.cert,'purchase');client.update()
        url=self.opened.call_args.args[0];sid,web=url.split('#')[1].split('.')
        self.service.send(sid,web,{'phone':self.phone});self.service.check(sid,web,{'code':'123456'})
        self.poll(client)
    def test_actual_server_flow_and_restart_require_online_recheck(self):
        client=self.client();self.authorize(client);self.assertTrue(client.has_access('purchase'))
        saved=json.loads(client.path.read_text());self.assertNotIn('verificationUrl',saved['sessions']['purchase'])
        saved['sessions']['purchase'].update(state='verified',freshUntil=1e12,expiresAt=1e12)
        client.path.write_text(json.dumps(saved))
        restored=self.client();self.assertFalse(restored.has_access('purchase'))
        self.poll(restored);self.assertTrue(restored.has_access('purchase'))
        with self.db.transaction() as tx:tx.execute('UPDATE players SET active=0')
        self.poll(restored);self.assertFalse(restored.has_access('purchase'))
    def test_network_failure_and_binding_mismatch_fail_closed(self):
        client=self.client();self.authorize(client)
        client.request=Mock(side_effect=OSError('offline'));self.poll(client);self.assertFalse(client.has_access('purchase'))
        client.request=lambda *a:{**self.service.status(client.sessions['purchase']['id'],client.sessions['purchase']['pollToken']),'productId':'other'}
        self.poll(client);self.assertFalse(client.has_access('purchase'))
    def test_stale_proof_cannot_open_gate(self):
        client=self.client();self.authorize(client)
        with patch('engine_player_identity.time.monotonic',return_value=time.monotonic()+31):self.assertFalse(client.has_access('purchase'))
        client.close();self.assertFalse(client.has_access('purchase'))
    def test_local_certificate_and_payment_status_do_not_bypass_required_sms(self):
        CertificateStore(self.root).activate('purchase',self.cert)
        (self.root/'payments.json').write_text(json.dumps({'identityRequired':True}))
        pay=Transactions(self.root);self.addCleanup(pay.close)
        pay.records['purchase']={'state':'succeeded','product':'deluxe'}
        self.assertFalse(pay.has_access('purchase'))
        with self.assertRaises(ValueError):pay.activate_certificate(self.cert,'deluxe','purchase')
        with self.assertRaises(ValueError):pay.import_certificate('deluxe','purchase')
    def test_invalid_server_response_never_opens_another_origin(self):
        client=self.client();original=client.request
        client.request=lambda *args:{**original(*args),'verificationUrl':'https://other.example/verify#secret'}
        client.start(self.cert,'purchase');client.update()
        self.opened.assert_not_called();self.assertFalse(client.has_access('purchase'));self.assertTrue(client.failures)
    def test_create_disk_failure_can_be_retried_and_never_grants(self):
        client=self.client();client.start(self.cert,'purchase')
        with patch('engine_player_identity.atomic_json',side_effect=OSError('disk full')):client.update()
        self.assertEqual(client.sessions['purchase']['state'],'error');self.assertFalse(client.has_access('purchase'))
        self.assertTrue(client.start(self.cert,'purchase'));client.update();self.opened.assert_called_once()
    def test_generated_gate_opens_picker_first_and_scene_only_after_proof(self):
        graph=click_graph('1','2','PlayerGate');scope={};exec(generated_source(graph)[0],scope)
        pay=NS(player_verified=Mock(return_value=False),import_certificate=Mock())
        obj=NS(world=NS(transactions=pay,load_scene=Mock()))
        scope['_bp_ui_click'](obj,'1','2');pay.import_certificate.assert_called_once_with('deluxe','purchase','');obj.world.load_scene.assert_not_called()
        pay.player_verified.return_value=True;scope['_bp_ui_click'](obj,'1','2')
        obj.world.load_scene.assert_called_once_with('scenes/main.json');self.assertEqual(pay.import_certificate.call_count,1)
    def test_settings_reject_insecure_origin(self):
        for url in ('http://example.com','https://example.com/api','https://example.com/?secret=1','https://user:pass@example.com'):
            with self.assertRaises(ValueError):settings({'identityApi':url})

if __name__=='__main__':unittest.main()
