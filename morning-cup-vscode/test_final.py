import io, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
import pandas as pd
import app as server
from samples import make_sample
from domain import validate_profile, now
from forecasting import predict_rows, validate_csv
from providers import parse_population, parse_weather

class FinalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=Path(self.tmp.name)/'test.db'
  self.public=server.PUBLIC;server.PUBLIC=False;self.c=server.app.test_client();self.s=make_sample('university')
 def tearDown(self):server.DB=self.old;server.PUBLIC=self.public;self.tmp.cleanup()
 def test_three_samples_actual_prophet(self):
  for k in ['university','office','residential']:
   s=make_sample(k);validate_profile(s['profile']);p=predict_rows(s['history'],s['profile'],s['weather'])
   self.assertEqual(p['method'],'Prophet');self.assertGreaterEqual(p['y'],0)
   self.assertTrue(any('연령' in c for c in p['used']));self.assertEqual(len(s['history']),180)
 def test_low_data_and_missing_api(self):
  p=predict_rows(self.s['history'][-3:],self.s['profile'])
  self.assertNotEqual(p['method'],'판단 보류');self.assertIsNone(p['change']);self.assertIsNone(p['lower'])
  p=predict_rows([],self.s['profile']);self.assertEqual(p['method'],'판단 보류')
 def test_model_error_falls_back(self):
  with patch('forecasting.Prophet',side_effect=RuntimeError('test')):
   p=predict_rows(self.s['history'],self.s['profile'])
  self.assertIsNotNone(p['y']);self.assertNotEqual(p['method'],'판단 보류')
 def test_bad_csv(self):
  for df in [pd.DataFrame({'ds':['2020-01-01']*2,'y':[1,2]}),pd.DataFrame({'ds':['2020-01-01'],'y':[-1]}),pd.DataFrame({'ds':[str(now().date())],'y':[2]}),pd.DataFrame({'ds':['2020-01-01'],'y':[float('inf')]})]:
   with self.assertRaises(ValueError):validate_csv(df)
 def test_setup_upload_atomic(self):
  p=self.s['profile'];self.assertEqual(self.c.post('/api/setup',json=p).status_code,200)
  good=b'ds,y,valid,is_closed\n2025-01-01,20,1,0\n'
  self.assertEqual(self.c.post('/api/upload',data={'file':(io.BytesIO(good),'a.csv')}).status_code,200)
  bad=b'ds,y\n2025-01-01,-3\n'
  self.assertEqual(self.c.post('/api/upload',data={'file':(io.BytesIO(bad),'a.csv')}).status_code,400)
  self.assertEqual(self.c.get('/api/state').json['count'],1)
  self.assertEqual(self.c.post('/api/demo',json={'kind':'office'}).status_code,400)
 def test_demo_provenance_and_leave(self):
  self.c.post('/api/setup',json={'mode':'demo','kind':'university'})
  with self.c.get('/api/export') as response:self.assertIn(b'synthetic',response.data)
  with patch('app.population',side_effect=AssertionError('no real API in demo')):
   self.assertEqual(self.c.post('/api/refresh',json={}).status_code,200)
  self.assertEqual(self.c.post('/api/leave-demo',json={}).status_code,200)
  self.assertTrue(self.c.get('/api/state').json['needs_setup'])
 def test_public_session_isolation(self):
  server.PUBLIC=True
  a=server.app.test_client();b=server.app.test_client()
  a.post('/api/setup',json={'mode':'demo','kind':'office'})
  self.assertTrue(b.get('/api/state').json['needs_setup'])
  self.assertEqual(a.get('/api/state').json['profile']['name'],'강남 점심 식당')
 def test_cors_and_static(self):
  with patch.dict(os.environ,{'MORNING_LIVE_SERVER':'1'}):
   res=self.c.options('/api/forecast',headers={'Origin':'http://127.0.0.1:5500'})
   self.assertEqual(res.headers['Access-Control-Allow-Origin'],'http://127.0.0.1:5500')
   self.assertEqual(self.c.post('/api/setup',json={},headers={'Origin':'https://evil.example'}).status_code,403)
  for f in ['index.html','style.css','app.js']:
   with self.c.get('/static/'+f) as res:self.assertEqual(res.status_code,200)
 def test_population_parser(self):
  p={'AREA_PPLTN_MIN':'100','AREA_PPLTN_MAX':'200','AREA_CONGEST_LVL':'보통','PPLTN_TIME':now().strftime('%Y-%m-%d %H:%M'),'FEMALE_PPLTN_RATE':'55','MALE_PPLTN_RATE':'45','PPLTN_RATE_20':'30'}
  res=parse_population({'citydata_ppltn':[p]},'홍대 관광특구');self.assertEqual(res['female'],55);self.assertIsNone(res['ages']['30'])
  p['PPLTN_TIME']='2020-01-01 00:00'
  with self.assertRaises(ValueError):parse_population({'citydata_ppltn':[p]},'x')
 def test_weather_parser_kst(self):
  day=now().date()+timedelta(days=1);start=now().replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
  payload={'cod':'200','list':[{'dt':int((start+timedelta(hours=h)).timestamp()),'main':{'temp':20},'rain':{'3h':3},'pop':.4} for h in range(0,24,3)]}
  w=parse_weather(payload,self.s['profile'],day);self.assertEqual(w['rain'],12);self.assertEqual(w['temp'],20)
  with self.assertRaises(ValueError):parse_weather({'cod':'200','list':[]},self.s['profile'],day)
 def test_missing_keys_are_not_mocked(self):
  self.c.post('/api/setup',json=self.s['profile'])
  with patch.dict(os.environ,{'SEOUL_API_KEY':'','OPENWEATHER_API_KEY':''}):self.c.post('/api/refresh',json={})
  s=self.c.get('/api/state').json;self.assertEqual(s['live']['status'],'unavailable');self.assertNotEqual(s['live']['source'],'synthetic')
 def test_closed_day(self):
  p=self.s['profile'];p['closed_days']=[(now().date()+timedelta(days=1)).weekday()]
  self.assertEqual(predict_rows([],p)['y'],0)

class RegressionTests(unittest.TestCase):
 def test_wide_interval_keeps_direction(self):
  s=make_sample('university')
  with patch('forecasting.Prophet') as ctor:
   ctor.return_value.predict.return_value=pd.DataFrame([{'yhat':150,'yhat_lower':1,'yhat_upper':400}])
   p=predict_rows(s['history'],s['profile'],s['weather'])
  self.assertEqual(p['method'],'Prophet');self.assertEqual(p['label'],'증가 예상')
  self.assertIn('변동 가능성',p['notes'][0])
 def test_joint_demographics_not_invented(self):
  s=make_sample('university')
  with patch('forecasting.Prophet') as ctor:
   ctor.return_value.predict.return_value=pd.DataFrame([{'yhat':100,'yhat_lower':80,'yhat_upper':120}])
   predict_rows(s['history'],s['profile'],s['weather'])
   columns=ctor.return_value.fit.call_args.args[0].columns
  self.assertIn('target_age',columns);self.assertIn('target_gender',columns)
  self.assertNotIn('female_age_population',columns)
 def test_population_under_ten_combined(self):
  p={'AREA_PPLTN_MIN':'10','AREA_PPLTN_MAX':'20','PPLTN_TIME':now().strftime('%Y-%m-%d %H:%M'),'PPLTN_RATE_0':'2','PPLTN_RATE_10':'8'}
  self.assertEqual(parse_population({'rows':[p]},'구역')['ages']['10'],10)
 def test_partial_snapshots_not_used(self):
  s=make_sample('office');s['mode']='real';s['history']=[{'ds':'2025-01-01','y':10,'valid':1,'is_closed':0}]
  snap=dict(s['live'],time='2025-01-01T12:00:00+09:00')
  s['snapshots']=[snap]*20
  self.assertNotIn('pop',server.enriched_history(s)[0])

if __name__=='__main__':unittest.main()
