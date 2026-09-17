import tempfile
from pathlib import Path
import unittest
import app as web

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=web.DB
        web.DB=Path(self.tmp.name)/'shop.db';self.c=web.app.test_client()
    def tearDown(self):
        web.DB=self.old;self.tmp.cleanup()
    def test_new_real_store_has_no_sample_data_and_rejects_overwrite(self):
        self.assertTrue(self.c.get('/api/state').json['needs_setup'])
        self.assertEqual(self.c.post('/api/setup',json={'mode':'real','name':'동네 가게','area_type':'residential'}).status_code,200)
        s=self.c.get('/api/state').json
        self.assertEqual(s['config']['name'],'동네 가게')
        self.assertEqual(s['config']['items'],[])
        self.assertEqual(s['sales_count'],0)
        self.assertEqual(s['config']['source'],'real')
        self.assertEqual(self.c.post('/api/setup',json={'mode':'demo'}).status_code,409)
        self.assertEqual(self.c.post('/api/forecast',json={}).status_code,400)
    def test_sample_is_opt_in(self):
        self.assertEqual(self.c.post('/api/setup',json={'mode':'demo'}).status_code,200)
        self.assertEqual(self.c.get('/api/state').json['sales_count'],900)
    def test_invalid_setup_leaves_no_store(self):
        for body in [{'mode':'real','name':'','area_type':'office'},{'mode':'real','name':'test','area_type':'invalid'},{'mode':'other'}]:
            self.assertEqual(self.c.post('/api/setup',json=body).status_code,400)
            self.assertIsNone(web.load('config'))
    def test_personal_menu_to_csv_workflow_and_restart(self):
        self.c.post('/api/setup',json={'mode':'real','name':'내 카페','area_type':'office'})
        c=self.c.get('/api/state').json['config']
        demo,_=web.demo()
        c['items']=[{'id':'my_latte','name':'우리 라떼','price':5000,'buffer':1}]
        c['materials']=[demo['materials'][-2]]
        c['materials'][0].update(stock=0,remaining_today=0,incoming_qty=0)
        c['recipes']={'my_latte':{'milk':180}}
        self.assertEqual(self.c.post('/api/config',json=c).status_code,200)
        response=self.c.get('/api/template');self.assertIn('my_latte',response.data.decode('utf-8-sig'))
        again=web.app.test_client()
        self.assertEqual(again.get('/api/state').json['config']['recipes']['my_latte']['milk'],180)

if __name__=='__main__':unittest.main()
