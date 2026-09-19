import math
from datetime import datetime, timedelta, timezone, date
from areas import PRESETS, validate_area
KST = timezone(timedelta(hours=9))
def now(): return datetime.now(KST)
DISTRICTS = "강남구 강동구 강북구 강서구 관악구 광진구 구로구 금천구 노원구 도봉구 동대문구 동작구 마포구 서대문구 서초구 성동구 성북구 송파구 양천구 영등포구 용산구 은평구 종로구 중구 중랑구".split()
AGES = ['10','20','30','40','50','60','70']

def num(v, lo, hi):
    x=float(v)
    if not math.isfinite(x) or not lo <= x <= hi: raise ValueError('숫자 범위를 확인해 주세요.')
    return x

def validate_profile(p):
    if not isinstance(p,dict): raise ValueError('매장 정보가 올바르지 않습니다.')
    q={}
    for k in ['name','district','dong','address','business','zone','gender','metric']:
        v=p.get(k,'')
        if not isinstance(v,str) or len(v)>200: raise ValueError('입력 길이를 확인해 주세요.')
        q[k]=v.strip()
    if not all(q[k] for k in ['name','dong','zone']): raise ValueError('매장명, 동, 데이터 구역을 입력하세요.')
    if q['district'] not in DISTRICTS: raise ValueError('서울시 자치구를 선택하세요.')
    if q['gender'] not in ['female','male','all','unknown']: raise ValueError('주고객 성별을 확인하세요.')
    if q['metric'] not in ['transactions','visitors']: raise ValueError('기록 단위를 선택하세요.')
    q['ages']=p.get('ages',[])
    if not isinstance(q['ages'],list) or len(set(q['ages']))!=len(q['ages']) or any(a not in AGES for a in q['ages']): raise ValueError('연령대를 확인하세요.')
    q['lat']=num(p.get('lat'),37.4,37.72);q['lon']=num(p.get('lon'),126.75,127.2)
    q['open_hour']=int(num(p.get('open_hour'),0,23));q['close_hour']=int(num(p.get('close_hour'),1,24))
    if q['open_hour']>=q['close_hour']: raise ValueError('마감 시간은 시작 시간 이후여야 합니다. 이번 버전은 당일 영업만 지원합니다.')
    q['closed_days']=p.get('closed_days',[])
    if not isinstance(q['closed_days'],list) or any(type(d) is not int or d not in range(7) for d in q['closed_days']): raise ValueError('휴무 요일 오류')
    if p.get('zone_confirmed') is not True: raise ValueError('매장과 데이터 구역의 연관성을 확인해 주세요.')
    q['zone_confirmed']=True
    q['area']=validate_area(p.get('area',{}))
    return q
