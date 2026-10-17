"""Certificate import uses local grants, never forges succeeded payment records."""
from concurrent.futures import Future
from copy import deepcopy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from engine_blueprints import generated_source
from engine_certificate_dialog import CertificateDialog, OpenFilenameW
from engine_certificates import CertificateStore, MAX_CERTIFICATE, read_certificate, validate_certificate
from engine_runtime import ScriptBinding
from engine_transactions import Transactions
from engine_ui_blueprints import click_graph


def certificate(product='deluxe', player='test'):
    return {'schema': 'myengine-license/v1', 'certificateId': 'DEV-1234567890abcdef',
            'product': 'MyEngine', 'productId': product, 'edition': 'Deluxe',
            'playerId': player, 'issuedAt': '2026-01-01T00:00:00.000Z',
            'grantType': 'developer', 'licenseStatus': 'issued',
            'payment': {'status': 'not_required', 'amount': 0, 'currency': 'RUB'},
            'verification': {'bankVerified': False, 'serverVerified': False}, 'signature': None}


class FakeDialogs:
    def __init__(self, path=None, accepted=True, wait=False):
        self.path=path; self.accepted=accepted; self.wait=wait
        self.entered=threading.Event(); self.release=threading.Event(); self.closed=False; self.messages=[]
    def pick(self, product):
        self.entered.set()
        if self.wait and not self.release.wait(2):raise RuntimeError('Test picker timed out')
        return self.path
    def confirm(self, cert, key):return self.accepted
    def message(self, text, error=False):self.messages.append((text,error))
    def close(self):self.closed=True;self.release.set()


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'game';self.root.mkdir()
        self.patch_env=patch.dict(os.environ, {'LOCALAPPDATA': str(Path(self.temp.name)/'local')})
        self.patch_env.start();self.addCleanup(self.patch_env.stop)
        (self.root/'payments.json').write_text(json.dumps({'checkoutMode':'site','checkoutSite':'https://example.invalid/',
            'siteProduct':'deluxe','siteProducts':['deluxe','cube2']}))
        self.pay=Transactions(self.root);self.addCleanup(self.pay.close);self.pay.log=lambda message:None
        self.path=self.root/'license.json';self.path.write_text(json.dumps(certificate()))

    def test_real_website_certificate_is_importable(self):
        engine=Path(__file__).resolve().parents[1]
        source="""const api=require('./templates/payment-site/developer-core.js');
(async()=>{const s=await api.createSettings('test','1234','+79991234567');
console.log(JSON.stringify(await api.issue(s,'test','1234','+79991234567',
{gameName:'MyEngine',productId:'deluxe',productTitle:'Deluxe'})));})().catch(e=>{console.error(e);process.exit(1)});"""
        result=subprocess.run(['node','-e',source],cwd=engine,capture_output=True,text=True,check=True)
        self.pay.activate_certificate(json.loads(result.stdout),'deluxe','purchase','test')
        self.assertTrue(self.pay.has_access('purchase'))
        self.assertFalse(self.pay.paid_once('purchase'))
        self.assertEqual(self.pay.state('purchase'),'idle')

    def test_manual_checkout_is_preserved_and_activation_survives_restart(self):
        with patch('engine_transactions.open_url'):
            self.pay.start('deluxe','purchase')
        before=deepcopy(self.pay.records['purchase'])
        self.pay.activate_certificate(certificate(),'deluxe','purchase')
        self.assertEqual(self.pay.records['purchase'],before)
        self.assertEqual(self.pay.state('purchase'),'manual')
        self.assertTrue(self.pay.has_access('purchase'));self.assertFalse(self.pay.paid_once('purchase'))
        restarted=Transactions(self.root);self.addCleanup(restarted.close)
        self.assertTrue(restarted.has_access('purchase'));self.assertEqual(restarted.state('purchase'),'idle')
        self.assertFalse(restarted.has_access('cube2'))
        self.assertFalse(CertificateStore(self.root/'other').has('purchase',['deluxe']))

    def test_wrong_product_player_expired_revoked_or_signed_certificates_are_rejected(self):
        bad=[]
        for field,value in [('schema','other'),('productId','cube2'),('playerId','other'),
                            ('licenseStatus','revoked'),('grantType','unknown'),('signature','not-verifiable'),
                            ('expiresAt','2000-01-01T00:00:00Z'),('issuedAt','not-a-date')]:
            item=certificate();item[field]=value;bad.append(item)
        for item in bad:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):self.pay.activate_certificate(item,'deluxe','purchase','test')
        self.assertFalse(self.pay.has_access('purchase'));self.assertFalse(self.pay.certificates.path.exists())

    def test_paid_claim_in_json_never_becomes_server_success(self):
        cert=certificate();cert.update(grantType='purchase',certificateId='LIC-123')
        cert['payment']['status']='succeeded';cert['verification']={'serverVerified':True,'bankVerified':True}
        saved=self.pay.activate_certificate(cert,'deluxe','purchase')
        self.assertEqual(saved['payment']['status'],'unverified');self.assertNotIn('verification',saved)
        self.assertTrue(self.pay.has_access('purchase'));self.assertFalse(self.pay.paid_once('purchase'))
        self.assertNotEqual(self.pay.state('purchase'),'succeeded')

    def test_product_key_collisions_and_catalog_limit(self):
        self.pay.activate_certificate(certificate(),'deluxe','purchase')
        with self.assertRaises(ValueError):self.pay.activate_certificate(certificate('cube2'),'cube2','purchase')
        with self.assertRaises(ValueError):self.pay.activate_certificate(certificate('not-listed'),'not-listed','other')
        self.pay.records['other']={'product':'cube2','state':'manual'}
        with self.assertRaises(ValueError):self.pay.activate_certificate(certificate(),'deluxe','other')
        self.pay.config['siteProducts']=['cube2']
        self.assertFalse(self.pay.has_access('purchase'))

    def test_write_failure_does_not_grant_access(self):
        with patch('engine_certificates.atomic_json',side_effect=OSError('read only')):
            with self.assertRaises(OSError):self.pay.activate_certificate(certificate(),'deluxe','purchase')
        self.assertFalse(self.pay.has_access('purchase'))

    def test_bounded_json_and_corrupt_storage(self):
        for raw in ('{"schema":1,"schema":2}', '[]', '{"payment":NaN}', 'x'*(MAX_CERTIFICATE+1)):
            self.path.write_text(raw)
            with self.assertRaises(ValueError):read_certificate(self.path,'deluxe')
        store=self.pay.certificates;store.path.parent.mkdir(parents=True,exist_ok=True);store.path.write_text('{broken')
        loaded=CertificateStore(self.root)
        self.assertFalse(loaded.has('purchase',['deluxe']));self.assertTrue(loaded.load_error)

    def test_generated_ui_callback_opens_picker_without_blocking_or_auto_grant(self):
        backend=FakeDialogs(str(self.path),wait=True)
        graph=click_graph('1','load','CertificateImport')
        path=self.root/'button.py';path.write_text(generated_source(graph)[0])
        world=NS(transactions=self.pay,scripts_allowed=True,ui=None)
        binding=ScriptBinding(NS(id=1,name='UIController',world=world,script_trusted=True),path)
        self.addCleanup(lambda:sys.modules.pop(binding.module_name,None))
        self.assertTrue(binding.reload())
        with patch('engine_certificate_dialog.WindowsDialogs',return_value=backend):
            binding.call('on_ui_click','1','load')
            dialog=self.pay._certificate_dialog
            self.assertTrue(backend.entered.wait(1));self.assertFalse(dialog.done.is_set())
            self.assertFalse(self.pay.has_access('purchase'))
            self.assertFalse(self.pay.import_certificate('deluxe','purchase'))
            backend.release.set();self.assertTrue(dialog.done.wait(1))
            self.assertFalse(self.pay.has_access('purchase'))  # Only the owner update can apply it.
            self.pay.update()
            self.assertTrue(self.pay.has_access('purchase'));self.assertTrue(binding.enabled)
            self.assertEqual(self.pay.certificate_status,'activated')
            self.assertFalse(self.pay.paid_once('purchase'))
            self.assertTrue(self.pay._certificate_notice.done.wait(1))

    def test_cancel_and_bad_file_leave_access_unchanged(self):
        for path,accepted,status in [(None,True,'canceled'),(str(self.path),False,'canceled'),(str(self.root/'missing.json'),True,'error')]:
            with self.subTest(status=status):
                backend=FakeDialogs(path,accepted)
                with patch('engine_certificate_dialog.WindowsDialogs',return_value=backend):
                    self.assertTrue(self.pay.import_certificate('deluxe','purchase'))
                    self.assertTrue(self.pay._certificate_dialog.done.wait(1));self.pay.update()
                self.assertEqual(self.pay.certificate_status,status)
                self.assertFalse(self.pay.has_access('purchase'))
        self.assertFalse(self.pay.certificates.path.exists())

    def test_close_while_picker_is_open_cannot_activate(self):
        backend=FakeDialogs(str(self.path),wait=True)
        with patch('engine_certificate_dialog.WindowsDialogs',return_value=backend):
            self.pay.import_certificate('deluxe','purchase');dialog=self.pay._certificate_dialog
            self.assertTrue(backend.entered.wait(1));self.pay.close()
            self.assertTrue(dialog.done.wait(1));self.pay.update()
        self.assertTrue(backend.closed);self.assertFalse(self.pay.has_access('purchase'))

    def test_server_success_still_unlocks_and_access_node_does_not_consume_it(self):
        self.pay.records['purchase']={'product':'deluxe','state':'succeeded'}
        graph={'format':1,'nodes':[{'id':'1','type':'Update'},{'id':'2','type':'TransactionHasAccess','params':{'key':'purchase'}},
            {'id':'3','type':'SetVisible'}], 'links':[['1','next','3','in'],['2','value','3','visible']]}
        scope={};exec(generated_source(graph)[0],scope)
        obj=NS(entity=NS(visible=False),world=NS(transactions=self.pay))
        scope['_bp_update'](obj,.01);self.assertTrue(obj.entity.visible)
        self.assertTrue(self.pay.paid_once('purchase'));self.assertFalse(self.pay.paid_once('purchase'))

    def test_windows_x64_file_dialog_abi(self):
        if ctypes.sizeof(ctypes.c_void_p)==8:
            self.assertEqual(ctypes.sizeof(OpenFilenameW),152)
            self.assertEqual(OpenFilenameW.lpstrFile.offset,48)
            self.assertEqual(OpenFilenameW.Flags.offset,96)


if __name__=='__main__':unittest.main()
