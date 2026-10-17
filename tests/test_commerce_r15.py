"""Commerce integration tests: no browser or real money transfers."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
import json
import re
import subprocess
import shutil
import unittest
import zipfile
import engine_commerce as commerce
from engine_transactions import Transactions, settings
from engine_build import copy_project


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = commerce.normalize({**commerce.DEFAULTS,'receiver':'41001234567890',
            'supportUrl':'mailto:tester@example.invalid','siteUrl':'https://example.invalid/shop/',
            'gameName':'Игра <script>alert(1)</script>', 'productTitle':'Gold & Ice',
            'amount':'12,50','productId':'gold'})

    def test_round_trip_and_runtime_settings_preserve_existing_api(self):
        (self.root/'payments.json').write_text(json.dumps({'checkoutApi':'https://example.invalid/api','donationUrl':'https://example.invalid/tip'}))
        commerce.save(self.root,self.config)
        self.assertEqual(commerce.load(self.root),self.config)
        linked=commerce.connect(self.root,self.config,connect_donation=False)
        self.assertEqual(linked['checkoutApi'],'https://example.invalid/api')
        self.assertEqual(linked['donationUrl'],'https://example.invalid/tip')
        self.assertEqual(linked['checkoutMode'],'site')
        self.assertEqual(linked['siteProduct'],'gold')
        self.assertNotIn('developerAccess',linked)

    def test_static_start_uses_product_and_request_id_without_server_or_paid_state(self):
        commerce.connect(self.root,self.config)
        pay=Transactions(self.root);self.addCleanup(pay.close)
        with patch('engine_transactions.open_url') as browser,patch('engine_transactions.request_json') as network:
            self.assertTrue(pay.start('gold','buy'))
            self.assertFalse(pay.start('gold','buy'))
            self.assertEqual(pay.state('buy'),'manual');self.assertFalse(pay.paid_once('buy'))
            for _ in range(3):pay.update()
            network.assert_not_called();browser.assert_called_once()
            query=parse_qs(urlsplit(browser.call_args.args[0]).query)
            self.assertEqual(query['product'],['gold']);self.assertEqual(query['requestId'],[pay.request_id('buy')])
            self.assertRegex(pay.request_id('buy'),r'^[a-f0-9]{32}$')
            with self.assertRaises(ValueError):pay.start('other','other')
            pay.reset('buy');self.assertEqual(pay.state('buy'),'idle')

    def test_generate_safe_custom_site_and_render_build(self):
        target=commerce.export_zip(self.config,self.root/'site.zip')
        with zipfile.ZipFile(target) as z:
            names=z.namelist();page=z.read('index.html').decode();config=z.read('config.js').decode()
            self.assertIn('Игра &lt;script&gt;alert(1)&lt;/script&gt;',page)
            self.assertNotIn('<script>alert(1)</script>',page)
            self.assertIn('12.5',page);self.assertNotIn('10 ₽',page)
            self.assertNotIn('UNAUTICNA',page);self.assertNotIn('MyEngine Deluxe',page)
            self.assertIn('"amount": "12.50"',config)
            self.assertFalse(any('preset' in name or 'commerce.json' in name for name in names))
            self.assertEqual(commerce.import_settings(target)['productId'],'gold')
            z.extractall(self.root/'site')
        if shutil.which('node'):
            subprocess.run(['node','scripts/build-static.mjs'],cwd=self.root/'site',check=True,capture_output=True)
            self.assertEqual({p.name for p in (self.root/'site/dist').iterdir()},set(commerce.PUBLIC_FILES)|{'config.js','index.html'})

    def test_config_import_is_data_only_and_size_bounded(self):
        p=self.root/'config.js';p.write_text('window.MYENGINE_CONFIG = Object.freeze('+json.dumps(self.config)+');')
        self.assertEqual(commerce.import_settings(p),self.config)
        p.write_text('window.MYENGINE_CONFIG = Object.freeze('+json.dumps(self.config)+');alert(1)')
        with self.assertRaises(ValueError):commerce.import_settings(p)
        with zipfile.ZipFile(self.root/'ambiguous.zip','w') as z:
            z.writestr('a/config.js','{}');z.writestr('b/config.js','{}')
        with self.assertRaises(ValueError):commerce.import_settings(self.root/'ambiguous.zip')

    def test_invalid_settings_and_failed_export_do_not_overwrite_output(self):
        for key,value in [('amount','NaN'),('amount','1.001'),('amount','-1'),('amount','0'),
                          ('receiver','not-a-wallet'),('productId','../x'),('supportUrl','javascript:alert(1)'),
                          ('siteUrl','http://example.invalid'),('siteUrl','https://example.invalid/?amount=0')]:
            candidate={**self.config,key:value}
            if key in commerce.PRODUCT_FIELDS:candidate['products']=[{**self.config['products'][0],key:value}]
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):commerce.normalize(candidate)
        p=self.root/'site.zip';p.write_bytes(b'original')
        with self.assertRaises(ValueError):commerce.export_zip({**self.config,'receiver':''},p)
        self.assertEqual(p.read_bytes(),b'original')
        with self.assertRaises(ValueError):commerce.connect(self.root,{**self.config,'siteUrl':''})
        self.assertFalse((self.root/'payments.json').exists())

    def test_developer_hash_matches_browser_and_certificate_is_free(self):
        developer=commerce.create_developer('author','1234','8 (900) 000-00-00')
        self.assertNotIn('phone',developer);self.assertNotIn('last4',developer)
        if not shutil.which('node'):self.skipTest('Node unavailable')
        core=commerce.TEMPLATE/'developer-core.js'
        script="""const api=require(process.argv[1]);const s=JSON.parse(process.argv[2]);
        (async()=>{const cert=await api.issue(s,'author','1234','+7 9000000000',{gameName:'Demo',productId:'gold',productTitle:'Gold'});
        if(cert.payment.status!=='not_required'||cert.productId!=='gold'||cert.payment.amount!==0||cert.verification.bankVerified)process.exit(1);
        if(await api.matches(s,'author','0000','+79000000000'))process.exit(2);})();"""
        subprocess.run(['node','-e',script,str(core),json.dumps(developer)],check=True,capture_output=True)

    def test_player_export_excludes_author_settings_and_templates(self):
        commerce.save(self.root,self.config);commerce.connect(self.root,self.config)
        (self.root/'templates/payment-site').mkdir(parents=True)
        (self.root/'templates/payment-site/myengine-preset.json').write_text('{}')
        (self.root/'assets/templates').mkdir(parents=True)
        (self.root/'assets/templates/keep.txt').write_text('user asset')
        out=self.root/'Builds/Data';out.mkdir(parents=True)
        copy_project(self.root,out,lambda x:None)
        self.assertTrue((out/'payments.json').exists());self.assertTrue((out/'assets/templates/keep.txt').exists())
        self.assertFalse((out/'.myengine').exists());self.assertFalse((out/'templates/payment-site').exists())

    def test_old_api_only_projects_keep_their_mode(self):
        self.assertEqual(settings({'checkoutApi':'https://example.invalid/api'})['checkoutMode'],'api')
        self.assertEqual(commerce.normalize()['developerAccess'],{'enabled':False})

if __name__=='__main__':unittest.main()
