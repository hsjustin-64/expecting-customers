import unittest
from datetime import timedelta
import pandas as pd
import numpy as np
from areas import validate_area, enrich, preview, default_area
from engine import now, predict
from tests import WorkflowTests

class AreaTests(unittest.TestCase):
    def setUp(self):
        self.target=now().date()+timedelta(days=1)
        self.dates=pd.date_range(end=now().date()-timedelta(days=1),periods=120)
        self.df=pd.DataFrame({'ds':self.dates,'y':20.0})
        self.a={**default_area(),'type':'university','selected':True,'confirmed':True,'coverage_start':str(self.dates[0].date()),'coverage_end':str(self.target),'periods':[{'feature':'semester','start':str(self.dates[0].date()),'end':str(self.dates[59].date()),'label':'학기'}]}
    def test_boundaries_and_nonsemester(self):
        self.assertEqual(preview(self.a,self.dates[59].date())['values']['semester'],1)
        self.assertEqual(preview(self.a,self.dates[60].date())['values']['semester'],0)
        self.assertIsNone(preview(self.a,self.target+timedelta(days=1))['values']['semester'])
    def test_coverage_not_silently_zero(self):
        self.a['coverage_start']=str(self.dates[1].date())
        _, future, status=enrich(self.df,self.target,self.a)
        self.assertEqual(future,{})
        self.assertFalse(any(s['used'] for s in status))
    def test_unconfirmed_and_constant_excluded(self):
        self.a['confirmed']=False
        self.assertEqual(enrich(self.df,self.target,self.a)[1],{})
        self.a['confirmed']=True
        result,future,status=enrich(self.df,self.target,self.a)
        self.assertEqual(future,{'semester':0})
        self.assertEqual(int(result.semester.sum()),60)
        self.assertEqual(status[0]['active_days'],60)
        self.assertFalse(status[1]['used'])
    def test_overlaps_union_and_duplicate_features(self):
        self.a['periods']*=2
        self.a['periods'].append({**self.a['periods'][0],'feature':'exam_period'})
        result, future, status=enrich(self.df,self.target,self.a)
        self.assertEqual(int(result.semester.sum()),60)
        self.assertNotIn('exam_period',future)
        self.assertIn('중복',status[1]['reason'])
    def test_invalid_dates_and_other_preset(self):
        for changes in [{'type':'unknown'},{'coverage_end':self.a['coverage_start']},{'type':'office'}]:
            with self.assertRaises(ValueError):validate_area({**self.a,**changes})
    def test_sparse_and_baseline_no_context_effect(self):
        _, future, _=enrich(self.df.iloc[:30],self.target,self.a)
        self.assertEqual(future,{})
        self.a['periods'][0]['end']=str(self.dates[3].date())
        self.assertEqual(enrich(self.df,self.target,self.a)[1],{})
    def test_real_prophet_learns_calendar_feature(self):
        # Repeat on/off blocks to avoid confusing the level shift with the trend.
        active=np.array([(n//14)%2 for n in range(120)])
        self.df['semester']=active
        self.df['y']=20+active*20+np.sin(np.arange(120))
        off=predict(self.df,self.target,{'semester':0},['semester'])
        on=predict(self.df,self.target,{'semester':1},['semester'])
        self.assertIn('semester',on[4])
        self.assertGreater(on[0]-off[0],15)
        self.assertLess(on[0]-off[0],25)

class AreaApiTests(WorkflowTests):
    def test_area_save_preserves_sales_and_invalidates_plan(self):
        a={**default_area(),'type':'office','place':'주변 업무지구'}
        web=__import__('app')
        web.save_many({'plan':{'target':'old'},'draft':{'status':'old'}})
        self.assertEqual(self.post('area',a).status_code,200)
        self.assertTrue(web.load('config')['area']['selected'])
        self.assertEqual(len(web.load('sales')),900)
        self.assertIsNone(web.load('plan'))
        self.assertIsNone(web.load('draft'))
        self.assertEqual(self.post('area',{**a,'type':'bad'}).status_code,400)
        self.assertEqual(web.load('config')['area']['type'],'office')

if __name__=='__main__':unittest.main(verbosity=2)
