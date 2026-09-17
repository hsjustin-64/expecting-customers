import unittest
import tempfile
from pathlib import Path
from datetime import timedelta
import pandas as pd
import app as web
from engine import validate_sales, clean, forecast, procurement, now

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=web.DB
        web.DB=Path(self.temp.name)/'test.db'
        self.config,self.rows=web.demo()
        web.save_many({'config':self.config,'sales':self.rows})
        self.client=web.app.test_client()
    def tearDown(self):
        web.DB=self.old
        self.temp.cleanup()
    def post(self,path,body):
        return self.client.post('/api/'+path,json=body,base_url='http://localhost')
    def test_csv_rejects_duplicate_negative_and_future(self):
        for change in ['duplicate','negative','future']:
            rows=[dict(self.rows[0])]
            if change=='duplicate': rows*=2
            if change=='negative': rows[0]['y']=-1
            if change=='future': rows[0]['ds']=str(now().date())
            with self.assertRaises(ValueError): validate_sales(pd.DataFrame(rows),self.config['items'])
    def test_stockout_and_reservations(self):
        rows=[dict(r) for r in self.rows[:5]]
        rows[0]['stockout_minutes']=20
        rows[1]['confirmed_order_qty']=3
        df=validate_sales(pd.DataFrame(rows),self.config['items'])
        out=clean(df)
        self.assertEqual(len(out),4)
        self.assertEqual(out[out.item_id=='egg'].y.iloc[0],rows[1]['y']-3)
    def test_expiry_incoming_pack_and_late_cutoff(self):
        t=now().replace(hour=16,minute=0)
        target=t.date()+timedelta(days=1)
        c=self.config;c['materials']=c['materials'][:1]
        c['materials'][0].update(stock=100,expiry_date=str(t.date()),remaining_today=0,incoming_qty=4,incoming_date=str(target),incoming_expiry=str(target),pack_size=20,lead_time_days=1,cutoff='15:00')
        r=procurement([{'id':'ham','prepare':23}],c,target,t)[0]
        self.assertEqual(r['needed'],46)
        self.assertEqual(r['available'],0)
        self.assertEqual(r['packs'],3)
        self.assertTrue(r['late'])
        self.assertEqual(r['expired'],100)
    def test_inventory_subtracts_today_and_late_incoming(self):
        t=now();target=t.date()+timedelta(days=1)
        c=self.config;c['materials']=c['materials'][:1]
        c['materials'][0].update(stock=50,remaining_today=20,incoming_qty=100,incoming_date=str(target+timedelta(days=1)))
        r=procurement([{'id':'ham','prepare':23}],c,target,t)[0]
        self.assertEqual(r['available'],30)
        self.assertEqual(r['incoming_usable'],0)
        self.assertEqual(r['packs'],1)
    def test_closed_and_future_forecast_issue(self):
        df=validate_sales(pd.DataFrame(self.rows),self.config['items'])
        req={'issued_at':now().isoformat(),'temp_open_mean':24,'rain_open_mm':0,'open_hours':10,'discount_rate':0,'is_closed':True}
        p=forecast(df,self.config,req)
        self.assertTrue(all(r['prepare']==0 for r in p['items']))
        req['issued_at']=(now()+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):forecast(df,self.config,req)
    def test_real_transition_and_upload_is_atomic(self):
        r=self.post('start-real',{})
        self.assertEqual(r.status_code,200)
        self.assertEqual(web.load('sales'),[])
        self.assertTrue(all(m['stock']==0 for m in web.load('config')['materials']))
        csv=pd.DataFrame(self.rows).to_csv(index=False)
        self.assertEqual(self.post('upload',{'csv':csv}).status_code,200)
        self.assertEqual(self.post('upload',{'csv':'ds,item_id,y\ninvalid,ham,3'}).status_code,400)
        self.assertEqual(len(web.load('sales')),900)
    def test_forecast_draft_and_persistence(self):
        req={'issued_at':now().isoformat(),'temp_open_mean':24,'rain_open_mm':0,'open_hours':10,'discount_rate':0,'reservations':{'ham':5}}
        r=self.post('forecast',req)
        self.assertEqual(r.status_code,200,r.json)
        p=r.json
        self.assertTrue(all(i['model']=='Prophet' for i in p['items']))
        self.assertEqual(p['items'][0]['reserved'],5)
        packs={m['id']:2 for m in self.config['materials']}
        self.assertEqual(self.post('draft',{'packs':packs}).status_code,200)
        self.assertEqual(web.load('draft')['orders'][0]['approved_qty'],40)
        r=self.client.get('/api/order.csv',base_url='http://localhost')
        self.assertEqual(r.status_code,200)
        self.assertIn('거래처 미전송',r.data.decode('utf-8-sig'))
    def test_closing_updates_quality_and_invalidates_plan(self):
        ds=self.rows[0]['ds']
        data={'date':ds,'items':[{'id':'ham','left':2,'waste':1,'stockout_minutes':60}],'note':'품절'}
        self.assertEqual(self.post('closing',data).status_code,200)
        self.assertEqual(web.load('sales')[0]['stockout_minutes'],60)
        self.post('closing',data)
        self.assertEqual(len(web.load('closings')),1)
        self.assertIsNone(web.load('plan'))
    def test_foreign_origin_blocked(self):
        r=self.client.post('/api/start-real',json={},base_url='http://localhost',headers={'Origin':'https://example.com'})
        self.assertEqual(r.status_code,403)

if __name__=='__main__':unittest.main(verbosity=2)
