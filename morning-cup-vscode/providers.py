"""Server-side API adapters. Keys and upstream exception URLs never reach clients."""
import json, os, threading, time
from datetime import datetime, timedelta
from urllib.request import urlopen
from urllib.parse import urlencode, quote
from domain import now, KST, num
_CACHE={};_LOCK=threading.Lock()

def fetch_json(url):
    with urlopen(url,timeout=12) as response:
        raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('Response too large')
        return json.loads(raw.decode('utf-8'))

def cached(key,ttl,fn):
    with _LOCK:
        item=_CACHE.get(key)
        if item and time.monotonic()-item[0]<ttl:return item[1].copy()
    result=fn()
    with _LOCK:
        if len(_CACHE)>500:_CACHE.clear()
        _CACHE[key]=(time.monotonic(),result)
    return result.copy()

def parse_population(payload,zone):
    def locate(x):
        if isinstance(x,dict):
            if 'AREA_PPLTN_MIN' in x:return x
            for v in x.values():
                found=locate(v)
                if found:return found
        elif isinstance(x,list):
            for v in x:
                found=locate(v)
                if found:return found
    p=locate(payload)
    if not p:raise ValueError('No population data')
    def ratio(key):
        v=p.get(key)
        return num(v,0,100) if v not in (None,'') else None
    lo=num(p['AREA_PPLTN_MIN'],0,10000000);hi=num(p['AREA_PPLTN_MAX'],lo,10000000)
    stamp=datetime.fromisoformat(p['PPLTN_TIME']).replace(tzinfo=KST)
    if not -300<=(now()-stamp).total_seconds()<=7200:raise ValueError('Stale population data')
    return dict(status='ok',source='seoul',zone=zone,time=stamp.isoformat(),minimum=lo,maximum=hi,congestion=p.get('AREA_CONGEST_LVL','정보 없음'),male=ratio('MALE_PPLTN_RATE'),female=ratio('FEMALE_PPLTN_RATE'),ages={a:((ratio('PPLTN_RATE_0') + ratio('PPLTN_RATE_10')) if ratio('PPLTN_RATE_0') is not None and ratio('PPLTN_RATE_10') is not None else None) if a=='10' else ratio('PPLTN_RATE_'+a) for a in ['10','20','30','40','50','60','70']},change_pct=None)

def population(profile):
    key=os.environ.get('SEOUL_API_KEY','')
    if not key:return dict(status='unavailable',source='seoul',message='서울시 API 키 미설정 · 시연 모드에서는 가상 상권을 확인할 수 있습니다.')
    zone=profile['zone']
    try:
        url='http://openapi.seoul.go.kr:8088/'+quote(key,safe='')+'/json/citydata_ppltn/1/5/'+quote(zone,safe='')
        return cached(('seoul',zone),300,lambda:parse_population(fetch_json(url),zone))
    except Exception:return dict(status='unavailable',source='seoul',message='서울시 인구 조회 실패 · API 키, 제공 구역, 데이터 갱신 상태를 확인하세요.')

def parse_weather(payload,profile,target):
    if str(payload.get('cod'))!='200':raise ValueError('Weather API failed')
    start=datetime.combine(target,datetime.min.time(),KST)+timedelta(hours=profile['open_hour'])
    end=datetime.combine(target,datetime.min.time(),KST)+timedelta(hours=profile['close_hour'])
    entries=[]
    # Precipitation is the preceding 3h accumulation for each forecast timestamp.
    for row in payload.get('list',[]):
        stop=datetime.fromtimestamp(row['dt'],KST);t=stop-timedelta(hours=3)
        hours=max(0,(min(stop,end)-max(t,start)).total_seconds()/3600)
        if hours:
            entries.append((hours,num(row['main']['temp'],-70,70),num(row.get('rain',{}).get('3h',0),0,1000),num(row.get('pop',0),0,1)))
    duration=sum(x[0] for x in entries)
    if duration < (end-start).total_seconds()/3600-.01:raise ValueError('Incomplete tomorrow forecast')
    return dict(status='ok',source='openweathermap',target=str(target),issued_at=now().isoformat(),temp=round(sum(h*t for h,t,_,_ in entries)/duration,2),rain=round(sum(h/3*r for h,_,r,_ in entries),2),pop=max(p for _,_,_,p in entries),note='3시간 예보를 영업시간에 맞춰 집계. 강수확률은 해당 구간 최댓값이며 하루 전체 확률이 아닙니다.')

def weather(profile):
    key=os.environ.get('OPENWEATHER_API_KEY','');target=now().date()+timedelta(days=1)
    if not key:return dict(status='unavailable',source='openweathermap',message='OpenWeatherMap API 키 미설정 · 날씨 없이 계산합니다.')
    try:
        params=urlencode(dict(lat=profile['lat'],lon=profile['lon'],appid=key,units='metric',lang='kr'))
        return cached(('weather',profile['lat'],profile['lon'],profile['open_hour'],profile['close_hour'],str(target)),900,lambda:parse_weather(fetch_json('https://api.openweathermap.org/data/2.5/forecast?'+params),profile,target))
    except Exception:return dict(status='unavailable',source='openweathermap',message='내일 날씨 조회 실패 · 확보된 영업 기록으로 계산합니다.')
