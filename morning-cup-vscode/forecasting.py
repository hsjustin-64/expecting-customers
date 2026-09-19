import logging, math, os
from pathlib import Path
import numpy as np
import pandas as pd
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parent/'data'/'matplotlib'))
from prophet import Prophet
from stan_compat import configure_stan
from domain import now, num
from areas import enrich, FEATURES
configure_stan()

OPTIONAL=['temp','rain','pop','female']+['age_'+a for a in ['10','20','30','40','50','60','70']]
LABELS={'temp':'영업시간 평균 기온','rain':'영업시간 강수량','pop':'주변 인구 이력 기반 추정','target_gender':'주고객 성별 구성 추정','target_age':'주고객 연령 구성 추정'}

def validate_csv(df):
    if not {'ds','y'}<=set(df): raise ValueError('CSV 필수 열은 ds(날짜), y(방문객 수 또는 결제 건수)입니다. 메뉴별 CSV는 사용할 수 없습니다.')
    if len(df)>3000 or len(df)==0: raise ValueError('1~3000일의 기록을 입력하세요.')
    df=df.copy();df['ds']=pd.to_datetime(df.ds,format='%Y-%m-%d',errors='coerce')
    if df.ds.isna().any() or (df.ds>=pd.Timestamp(now().date())).any(): raise ValueError('날짜는 어제까지의 YYYY-MM-DD로 입력하세요.')
    if df.ds.duplicated().any(): raise ValueError('하루당 한 행만 등록하세요. 날짜가 중복됩니다.')
    df['y']=[num(v,0,1000000) for v in df.y]
    if (df.y%1!=0).any(): raise ValueError('방문객·결제 건수는 정수입니다.')
    for c,default in [('valid',1),('is_closed',0)]:
        if c not in df:df[c]=default
        if not df[c].isin([0,1]).all():raise ValueError(c+'는 0 또는 1입니다.')
    for c in OPTIONAL:
        if c in df:
            bounds=(-60,60) if c=='temp' else ((0,10000000) if c=='pop' else ((0,1000) if c=='rain' else (0,100)))
            df[c]=[num(v,*bounds) if pd.notna(v) else np.nan for v in df[c]]
    return df[['ds','y','valid','is_closed']+[c for c in OPTIONAL if c in df]].sort_values('ds')

def frame(rows):
    df=pd.DataFrame(rows)
    if df.empty:return pd.DataFrame(columns=['ds','y'])
    df['ds']=pd.to_datetime(df.ds)
    return df[(df.get('valid',1)==1)&(df.get('is_closed',0)==0)].copy()

def baseline(df,target):
    same=df[(df.ds.dt.dayofweek==target.weekday()) & (df.ds>=target-pd.Timedelta(days=28))]
    return (float(same.y.mean()),'최근 4주 동일 요일 평균') if len(same) else (float(df.tail(14).y.mean()),'최근 14개 유효 영업일 평균')

def predict_rows(rows,profile,weather=None,target=None):
    target=pd.Timestamp(target or (now().date()+pd.Timedelta(days=1)))
    df=frame(rows);df=df[df.ds<target]
    notes=[];regs=[];used=[];future={}
    base=None;comparison='비교 기록 없음'
    if len(df):base,comparison=baseline(df,target)
    if target.weekday() in profile['closed_days']:
        y=lo=hi=0.;method='예정 휴무'
    elif df.empty:
        return dict(target=str(target.date()),method='판단 보류',label='매장 기록이 필요합니다',notes=['유효한 매장 기록이 없어 예측과 과거 평균을 계산할 수 없습니다.'],used=[],y=None,lower=None,upper=None,change=None,baseline=None,days=0,comparison=comparison)
    else:
        y=base;lo=hi=None;method=comparison
        if len(df)>=42:
            train,af,status=enrich(df,target.date(),profile['area'])
            future.update(af);regs.extend(af)
            notes.extend(s['label']+': '+s['reason'] for s in status if not s['used'])
            if weather and weather.get('status')=='ok' and weather.get('target')==str(target.date()):
                for c in ['temp','rain']:
                    if c in train and train[c].notna().all():future[c]=weather[c];regs.append(c)
                    else:notes.append(LABELS[c]+': 과거 이력이 없어 모델 미반영')
            else:notes.append('내일 날씨 예보 미반영 · 확보된 기록으로 계산')
            # Demographic marginals stay separate. Tomorrow uses past matching weekdays,
            # never the current snapshot or future observed population.
            candidates=['pop']
            if profile['gender'] in ['male','female'] and 'female' in train:
                train['target_gender']=train.female if profile['gender']=='female' else 100-train.female
                candidates.append('target_gender')
            cols=['age_'+a for a in profile['ages']]
            if cols and all(c in train for c in cols):
                train['target_age']=train[cols].sum(axis=1,min_count=len(cols));candidates.append('target_age')
            for c in candidates:
                if c not in train or not train[c].notna().all():continue
                same=train[train.ds.dt.dayofweek==target.weekday()].tail(4)
                if len(same)>=3:future[c]=float(same[c].mean());regs.append(c)
            if not any(c in regs for c in candidates):notes.append('인구 이력 부족 · 실시간 인구는 현재 상권 안내에만 사용')
            regs=[c for c in regs if train[c].nunique()>1 and math.isfinite(float(future[c]))]
            try:
                model=Prophet(weekly_seasonality=True,daily_seasonality=False,yearly_seasonality=False,interval_width=.8,uncertainty_samples=300)
                model.add_country_holidays(country_name='KR')
                for c in regs:model.add_regressor(c,prior_scale=2)
                model.fit(train[['ds','y']+regs],seed=2026)
                result=model.predict(pd.DataFrame([{'ds':target,**{c:future[c] for c in regs}}])).iloc[0]
                y,lo,hi=[max(0,float(result[k])) for k in ['yhat','yhat_lower','yhat_upper']]
                if not all(math.isfinite(v) for v in [y,lo,hi]):raise ValueError('Nonfinite forecast')
                method='Prophet';used=[LABELS.get(c,FEATURES.get(c,c)) for c in regs]
            except Exception:
                logging.getLogger(__name__).warning('Prophet failed; providing historical baseline',exc_info=False)
                y=base;lo=hi=None;notes.append('모델 계산 실패 · 과거 평균을 제공합니다')
        else:notes.append('42개 유효 영업일 미만 · 예측 대신 과거 평균을 제공합니다')
    change=(y/base-1)*100 if base and method in ['Prophet','예정 휴무'] else None
    label=('증가 예상' if change>10 else '감소 예상' if change< -10 else '평소 수준 예상') if change is not None else ('과거 기록 참고' if method!='예정 휴무' else '예정 휴무')
    if lo is not None and base and lo<base*.9 and hi>base*1.1:notes.insert(0,'변동 가능성이 큽니다 · 예상 방향은 유지합니다')
    return dict(target=str(target.date()),y=round(y,1),lower=round(lo,1) if lo is not None else None,upper=round(hi,1) if hi is not None else None,change=round(change,1) if change is not None else None,baseline=round(base,1) if base is not None else None,comparison=comparison,method=method,label=label,used=['요일·한국 공휴일']+used if method=='Prophet' else [],notes=notes,days=len(df))

def evaluate(rows,profile):
    df=frame(rows);out=[]
    for day in df.ds.tail(7):
        train=df[df.ds<day-pd.Timedelta(days=1)]
        if len(train)<42:continue
        # Calendar-only evaluation: no historical issued forecasts are assumed.
        subset=train[['ds','y']].assign(valid=1,is_closed=0)
        p={**profile,'area':{**profile['area'],'confirmed':False},'ages':[],'gender':'unknown'}
        pred=predict_rows(subset.to_dict('records'),p,target=day)
        if pred['method']!='Prophet':continue
        actual=float(df[df.ds==day].y.iloc[0]);b,_=baseline(train,day)
        out.append(dict(date=str(day.date()),actual=actual,predicted=pred['y'],baseline=round(b,1),inside=pred['lower']<=actual<=pred['upper']))
    return dict(rows=out,mae=round(float(np.mean([abs(x['actual']-x['predicted']) for x in out])),2) if out else None,baseline_mae=round(float(np.mean([abs(x['actual']-x['baseline']) for x in out])),2) if out else None,note='달력 기반 순차 검증입니다. 날씨·인구·상권 효과와 실제 매장 정확도를 입증하는 결과가 아닙니다.')
