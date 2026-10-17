"""Catalog migration, editor draft, generated website, and runtime routing."""
from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import zipfile
import engine_commerce as c
from engine_transactions import Transactions,PaymentConfigurationError,settings


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.value=c.normalize({**c.DEFAULTS,'gameName':'Test Game','receiver':'41001234567890',
            'supportUrl':'mailto:test@example.invalid','siteUrl':'https://example.invalid/store/',
            'products':[
                {'productId':'game','productTitle':'Игра','description':'Базовая игра','amount':'100','activationText':'Выдать игру вручную.'},
                {'productId':'dlc1','productTitle':'Ледяной мир <script>test</script>','description':'Новая территория','amount':'49,90','activationText':'Выдать дополнение.'},
                {'productId':'deluxe','productTitle':'Deluxe','description':'Издание Deluxe','amount':'10','activationText':'Выдать Deluxe.'}]})
    def test_old_config_migrates_to_one_item_without_losing_developer_settings(self):
        dev=c.create_developer('author','1234','+79000000000')
        old={**c.DEFAULTS,'developerAccess':dev,'productId':'expansion','productTitle':'Дополнение','amount':'15.50'}
        new=c.normalize(old)
        self.assertEqual(new['format'],2);self.assertEqual(len(new['products']),1)
        self.assertEqual(new['products'][0]['productId'],'expansion');self.assertEqual(new['products'][0]['amount'],'15.50')
        self.assertEqual(new['developerAccess'],dev);self.assertEqual(c.normalize(new),new)
    def test_catalog_validation_and_stable_payment_codes(self):
        reverse=c.normalize({**self.value,'products':list(reversed(self.value['products']))})
        self.assertEqual({p['productId']:p['paymentCode'] for p in reverse['products']},{p['productId']:p['paymentCode'] for p in self.value['products']})
        self.assertEqual(reverse['productId'],'deluxe')
        for items in [[],{},[{}]*101,[self.value['products'][0]]*2,[None]]:
            with self.subTest(items=type(items).__name__),self.assertRaises(ValueError):c.normalize({**self.value,'products':items})
        for key,value in [('productId','bad/id'),('amount','0'),('amount','1.001'),('activationText','')]:
            items=deepcopy(self.value['products']);items[1][key]=value
            with self.assertRaises(ValueError):c.normalize({**self.value,'products':items})
    def test_draft_add_copy_edit_delete_and_failed_edit_preserves_items(self):
        draft=c.CatalogDraft(self.value['products']);copied=draft.add(1)
        self.assertEqual(draft.products[copied]['amount'],'49.90');self.assertNotEqual(draft.products[copied]['productId'],'dlc1')
        before=deepcopy(draft.products)
        with self.assertRaises(ValueError):draft.update(copied,{**draft.products[copied],'productId':'game'})
        self.assertEqual(draft.products,before)
        draft.update(copied,{**draft.products[copied],'productId':'dlc2','amount':'22.25'})
        self.assertEqual(draft.products[copied]['amount'],'22.25')
        while len(draft.products)>1:draft.remove(len(draft.products)-1)
        with self.assertRaises(ValueError):draft.remove(0)
        self.assertEqual(draft.products[0]['productId'],'game')
    def test_save_reload_export_import_and_browser_catalog(self):
        c.save(self.root,self.value);self.assertEqual(c.load(self.root),self.value)
        archive=c.export_zip(self.value,self.root/'catalog.zip')
        imported=c.import_settings(archive);self.assertEqual(imported['products'],self.value['products'])
        with zipfile.ZipFile(archive) as z:
            page=z.read('index.html').decode();z.extractall(self.root/'site')
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.links=[];self.scripts=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if 'data-catalog-product' in attrs:self.links.append(attrs)
                if tag=='script':self.scripts.append(attrs)
        parser=Parser();parser.feed(page)
        self.assertEqual([a['data-catalog-product'] for a in parser.links],['game','dlc1','deluxe'])
        self.assertEqual(len(parser.scripts),4);self.assertIn('&lt;script&gt;test&lt;/script&gt;',page)
        self.assertNotIn('{{',page)
        if shutil.which('node'):
            subprocess.run(['node','scripts/build-static.mjs'],cwd=self.root/'site',check=True,capture_output=True)
            script=Path(__file__).with_name('site_catalog_r17.cjs')
            completed=subprocess.run(['node',str(script),str(self.root/'site')],check=True,capture_output=True,text=True)
            self.assertIn('catalog checks passed',completed.stdout)
    def test_multiple_runtime_buttons_share_site_without_sharing_order(self):
        (self.root/'payments.json').write_text(json.dumps({'checkoutApi':'https://example.invalid/api'}))
        connected=c.connect(self.root,self.value)
        self.assertEqual(connected['checkoutApi'],'https://example.invalid/api')
        self.assertEqual(connected['siteProducts'],['game','dlc1','deluxe'])
        pay=Transactions(self.root);self.addCleanup(pay.close)
        with patch('engine_transactions.open_url') as browser,patch('engine_transactions.request_json') as network:
            for item in self.value['products']:
                ident=item['productId'];self.assertTrue(pay.start(ident,ident));self.assertEqual(pay.state(ident),'manual');self.assertFalse(pay.paid_once(ident))
            queries=[parse_qs(urlsplit(call.args[0]).query) for call in browser.call_args_list]
            self.assertEqual([q['product'][0] for q in queries],['game','dlc1','deluxe'])
            self.assertEqual(len({q['requestId'][0] for q in queries}),3)
            self.assertTrue(all(urlsplit(call.args[0]).path=='/store/' for call in browser.call_args_list))
            with self.assertRaises(PaymentConfigurationError):pay.start('game','dlc1')
            with self.assertRaises(PaymentConfigurationError):pay.start('unknown','new')
            network.assert_not_called();self.assertEqual(browser.call_count,3)
    def test_runtime_legacy_catalog_and_catalog_update(self):
        self.assertEqual(settings({'siteProduct':'legacy'})['siteProducts'],['legacy'])
        c.connect(self.root,self.value)
        changed={**self.value,'products':self.value['products'][:2]}
        c.connect(self.root,changed)
        self.assertEqual(json.loads((self.root/'payments.json').read_text())['siteProducts'],['game','dlc1'])
        with self.assertRaises(ValueError):settings({'siteProduct':'one','siteProducts':['two']})

if __name__=='__main__':unittest.main()
