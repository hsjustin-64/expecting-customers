"""Seeded synthetic histories. Never represented as observed Seoul data."""
import math
import numpy as np
import pandas as pd
from domain import now
from areas import default_area
PROFILES={
 'university':('연남 캠퍼스 카페','마포구','서교동','홍대 관광특구',37.555,126.923,'female',['20']),
 'office':('강남 점심 식당','강남구','역삼동','강남역',37.498,127.028,'all',['30','40']),
 'residential':('잠실 동네 카페','송파구','잠실동','잠실 관광특구',37.513,127.102,'female',['30','40','50'])}

def make_sample(kind):
    if kind not in PROFILES: raise ValueError('샘플 매장을 선택하세요.')
    name,gu,dong,zone,lat,lon,gender,ages=PROFILES[kind]
    today=now().date();start=today-pd.Timedelta(days=180)
    area={**default_area(),'type':kind,'selected':True,'confirmed':True,'coverage_start':str(start),'coverage_end':str(today+pd.Timedelta(days=30)),'periods':[]}
    feature={'university':'semester','office':'office_low_attendance','residential':'school_vacation'}[kind]
    for offset in range(0,211,60):
        area['periods'].append({'feature':feature,'start':str(start+pd.Timedelta(days=offset)),'end':str(min(today+pd.Timedelta(days=30),start+pd.Timedelta(days=offset+27))),'label':'시연용 가상 일정'})
    p=dict(name=name,district=gu,dong=dong,address='시연용 가상 매장',zone=zone,lat=lat,lon=lon,gender=gender,ages=ages,business='카페' if kind!='office' else '음식점',metric='transactions',open_hour=9,close_hour=21,closed_days=[],zone_confirmed=True,area=area)
    rng=np.random.default_rng(20260917+list(PROFILES).index(kind));rows=[]
    for i in range(182):
        day=start+pd.Timedelta(days=i);weekend=day.weekday()>4
        temp=19+8*math.sin(i/35)+rng.normal(0,2);rain=max(0,rng.normal(5,4)) if rng.random()<.27 else 0
        pop=18000*(1+(.18 if kind!='office' else -.35)*weekend)+rng.normal(0,1800)
        shares=rng.dirichlet([2,12 if kind=='university' else 5,8,7,4,2,1])*100
        female=float(np.clip(53+7*math.sin(i/9)+rng.normal(0,3),20,80))
        selected=sum(shares[int(a)//10-1] for a in ages)
        active=int(any(x['start']<=str(day)<=x['end'] for x in area['periods']))
        effect={'university':18,'office':-20,'residential':9}[kind]*active
        y=max(0,round(45+.0018*pop+.3*selected+(.18*female if gender=='female' else 0)+effect-.9*rain+.3*(temp-20)+rng.normal(0,10)))
        rows.append(dict(ds=str(day),y=y,valid=1,is_closed=0,temp=round(temp,2),rain=round(rain,2),pop=round(pop),female=round(female,2),**{'age_'+a:round(float(shares[j]),2) for j,a in enumerate(['10','20','30','40','50','60','70'])},source='synthetic'))
    current=rows[-2];future=rows[-1]
    live=dict(status='ok',source='synthetic',zone=zone,time=now().isoformat(),congestion='약간 붐빔',minimum=int(current['pop']*.95),maximum=int(current['pop']*1.05),female=current['female'],male=100-current['female'],ages={a:current['age_'+a] for a in ['10','20','30','40','50','60','70']},change_pct=12.0)
    weather=dict(status='ok',source='synthetic',issued_at=now().isoformat(),target=future['ds'],temp=future['temp'],rain=future['rain'],pop=.7 if future['rain'] else .1)
    return dict(sample_kind=kind,generated_on=str(today),profile=p,mode='demo',history=rows[:180],live=live,weather=weather,forecast=None)
