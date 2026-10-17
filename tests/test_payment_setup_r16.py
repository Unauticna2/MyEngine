"""Reproduce R15 missing checkout crash through a real generated UI callback."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from engine_runtime import ScriptBinding, World
from engine_blueprints import generated_source
from engine_ui_blueprints import click_graph
from engine_transactions import PaymentConfigurationError, load_settings, settings


class MinimalWorld:
    transactions=World.transactions


class PaymentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.logs=[];self.bindings=[]
        self.world=MinimalWorld()
        self.world.root=self.root;self.world.ui=None;self.world.scripts_allowed=True
        self.world.editor_mode=False;self.world.log=self.logs.append
        self.entity=NS(id=7,name='UIController 7',world=self.world,script_trusted=True)
        self.addCleanup(self.close)
    def close(self):
        if getattr(self.world,'_transactions',None):self.world._transactions.close()
        for binding in self.bindings:sys.modules.pop(binding.module_name,None)
    def binding(self,action='TransactionStart'):
        graph=click_graph('1','buy',action)
        if action=='TransactionStart':graph['nodes'][1]['params'].update(product='deluxe',key='purchase')
        graph['nodes'].append({'id':'3','type':'Print','params':{'text':'checkout requested'}})
        graph['links'].append(['2','next','3','in'])
        path=self.root/f'button{len(self.bindings)}.py'
        path.write_text(generated_source(graph)[0],encoding='utf-8')
        binding=ScriptBinding(self.entity,path);self.bindings.append(binding)
        self.assertTrue(binding.reload());return binding
    def click(self,binding):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):binding.call('on_ui_click','1','buy')
        return output.getvalue()
    def configure(self,**updates):
        value={'checkoutMode':'site','checkoutSite':'https://example.invalid/shop/','siteProduct':'deluxe',**updates}
        (self.root/'payments.json').write_text(json.dumps(value),encoding='utf-8')
    def test_missing_setup_keeps_controller_and_aborts_next_nodes(self):
        binding=self.binding()
        with patch('engine_transactions.open_url') as browser,patch('engine_transactions.request_json') as request:
            for _ in range(2):
                output=self.click(binding)
                self.assertTrue(binding.enabled);self.assertIn('PAYMENT NOT READY',output)
                self.assertNotIn('SCRIPT DISABLED',output);self.assertIn('payments.json',output)
            browser.assert_not_called();request.assert_not_called()
        self.assertEqual(self.logs,[]);self.assertEqual(self.world.transactions.state('purchase'),'idle')
        self.assertFalse(self.world.transactions.paid_once('purchase'))
    def test_same_old_script_can_retry_after_configuration(self):
        binding=self.binding();self.click(binding);self.configure()
        with patch('engine_transactions.open_url') as browser:
            self.click(binding);browser.assert_called_once()
        self.assertTrue(binding.enabled);self.assertEqual(self.logs,['checkout requested'])
        self.assertEqual(self.world.transactions.state('purchase'),'manual')
    def test_missing_donation_is_recoverable_too(self):
        binding=self.binding('DonationOpen');self.click(binding)
        self.assertTrue(binding.enabled);self.assertEqual(self.logs,[])
        self.configure(donationUrl='https://example.invalid/tip')
        with patch('engine_transactions.open_url') as browser:
            self.click(binding);browser.assert_called_once_with('https://example.invalid/tip')
    def test_malformed_settings_are_reported_without_disabling_controller(self):
        (self.root/'payments.json').write_text('{broken json',encoding='utf-8')
        binding=self.binding();output=self.click(binding)
        self.assertIn('Не удалось прочитать',output);self.assertTrue(binding.enabled);self.assertEqual(self.logs,[])
        self.configure()
        with patch('engine_transactions.open_url') as browser:self.click(binding);browser.assert_called_once()
    def test_product_mismatch_does_not_disable_or_open_site(self):
        self.configure(siteProduct='gold');binding=self.binding()
        with patch('engine_transactions.open_url') as browser:
            output=self.click(binding);browser.assert_not_called()
        self.assertTrue(binding.enabled);self.assertIn('product=gold',output);self.assertEqual(self.logs,[])
    def test_unrelated_programming_errors_still_disable_script(self):
        binding=self.binding()
        binding.instance.on_ui_click=lambda *args:(_ for _ in ()).throw(ValueError('programming error'))
        with contextlib.redirect_stderr(io.StringIO()):output=self.click(binding)
        self.assertFalse(binding.enabled);self.assertIn('SCRIPT DISABLED',output)
    def test_existing_transaction_keeps_its_configuration(self):
        self.configure();pay=self.world.transactions
        with patch('engine_transactions.open_url') as browser:
            pay.start('deluxe','one')
            self.configure(checkoutSite='https://other.invalid/')
            pay.start('deluxe','two')
            self.assertTrue(all(call.args[0].startswith('https://example.invalid/') for call in browser.call_args_list))
    def test_site_only_configuration_chooses_site_mode(self):
        self.assertEqual(settings({'checkoutSite':'https://example.invalid'})['checkoutMode'],'site')
        self.assertEqual(settings({'checkoutApi':'https://example.invalid/api'})['checkoutMode'],'api')
        (self.root/'payments.json').write_text('[]')
        with self.assertRaises(PaymentConfigurationError):load_settings(self.root)

if __name__=='__main__':unittest.main()
