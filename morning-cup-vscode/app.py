import csv, io, json, os, secrets, sqlite3, threading
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlsplit
import pandas as pd
from flask import Flask, request, jsonify, session, redirect, Response, abort
from env_config import load_dotenv
ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
from domain import now, validate_profile, DISTRICTS, AGES
from areas import PRESETS, FEATURES
from samples import make_sample, PROFILES
from forecasting import validate_csv, predict_rows, evaluate
from providers import population, weather

app=Flask(__name__,static_folder='static')
app.config.update(MAX_CONTENT_LENGTH=4*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax')
PUBLIC=os.getenv('PUBLIC_DEMO')=='1'
if PUBLIC and len(os.getenv('SECRET_KEY',''))<32:raise RuntimeError('Public deployment requires SECRET_KEY (32+ characters)')
app.secret_key=os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['SESSION_COOKIE_SECURE']=PUBLIC
DB=Path(os.getenv('DATA_DIR',str(ROOT/'data')))/'demand-v2.db'
FIT_LOCK=threading.Lock()

def connection():
    DB.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB,timeout=20)
    con.execute('CREATE TABLE IF NOT EXISTS stores (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated TEXT NOT NULL)')
    return con

def ident():
    if not PUBLIC:return 'local'
    if 'store_id' not in session:session['store_id']=secrets.token_hex(16)
    return session['store_id']

def load():
    with connection() as con:
        row=con.execute('SELECT payload FROM stores WHERE id=?',(ident(),)).fetchone()
    return json.loads(row[0]) if row else None

def save(s):
    with connection() as con:
        con.execute('INSERT OR REPLACE INTO stores VALUES (?,?,?)',(ident(),json.dumps(s,ensure_ascii=False,allow_nan=False),now().isoformat()))
        if PUBLIC:con.execute('DELETE FROM stores WHERE updated < ?',((now()-timedelta(days=7)).isoformat(),))

def required():
    s=load()
    if not s:raise ValueError('먼저 매장을 설정하세요.')
    return s

@app.before_request
def guard():
    host=request.host.split(':')[0]
    if not PUBLIC and host not in ['localhost','127.0.0.1','[']:abort(403)
    origin=request.headers.get('Origin')
    if request.method in ['POST','PUT','DELETE'] and origin:
        allowed=origin==request.host_url.rstrip('/')
        # Public requests arrive behind a TLS proxy, but host must still match.
        if PUBLIC:allowed=urlsplit(origin).scheme=='https' and urlsplit(origin).netloc==request.host
        elif os.getenv('MORNING_LIVE_SERVER')=='1':allowed=allowed or origin in ['http://localhost:5500','http://127.0.0.1:5500']
        if not allowed:abort(403)

@app.after_request
def headers(r):
    r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff'
    origin=request.headers.get('Origin')
    if not PUBLIC and os.getenv('MORNING_LIVE_SERVER')=='1' and origin in ['http://localhost:5500','http://127.0.0.1:5500']:
        r.headers['Access-Control-Allow-Origin']=origin;r.headers['Vary']='Origin'
        r.headers['Access-Control-Allow-Headers']='Content-Type';r.headers['Access-Control-Allow-Methods']='GET,POST,OPTIONS'
    return r

@app.errorhandler(ValueError)
def invalid(e):return jsonify(error=str(e)),400
@app.errorhandler(413)
def large(e):return jsonify(error='CSV 크기는 4MB 이하로 제한합니다.'),413
@app.errorhandler(500)
def server_error(e):return jsonify(error='서버 처리에 실패했습니다. 다시 시도하거나 실행 창을 확인하세요.'),500

@app.get('/')
def root():return redirect('/static/index.html')
@app.get('/health')
def health():return jsonify(status='ok')
@app.get('/api/state')
def state():
    s=load()
    if s:
        result={k:v for k,v in s.items() if k not in ['history','snapshots']}
        result.update(history=s['history'][-28:],count=len(s['history']),history_start=s['history'][0]['ds'] if s['history'] else None,history_end=s['history'][-1]['ds'] if s['history'] else None)
    else:result=dict(needs_setup=True)
    result.update(presets=PRESETS,features=FEATURES,districts=DISTRICTS,ages=AGES,public_demo=PUBLIC,tomorrow=str(now().date()+timedelta(days=1)),api_status=dict(seoul=bool(os.getenv('SEOUL_API_KEY')),weather=bool(os.getenv('OPENWEATHER_API_KEY'))))
    return jsonify(result)

@app.post('/api/setup')
def setup():
    if load():raise ValueError('이미 매장이 있습니다. 설정 화면에서 수정하거나 시연 모드를 전환하세요.')
    body=request.get_json() or {}
    if body.get('mode')=='demo':s=make_sample(body.get('kind','university'))
    else:s=dict(mode='real',profile=validate_profile(body),history=[],live=None,weather=None,forecast=None)
    save(s);return jsonify(ok=True)

@app.post('/api/demo')
def demo():
    s=load()
    if s and s['mode']=='real':raise ValueError('실제 매장 기록은 시연 데이터로 덮어쓰지 않습니다. 새 브라우저 세션 또는 별도 폴더에서 체험하세요.')
    save(make_sample((request.get_json() or {}).get('kind','university')));return jsonify(ok=True)

@app.post('/api/profile')
def profile():
    s=required();p=validate_profile(request.get_json())
    if s['history'] and p['metric']!=s['profile']['metric']:raise ValueError('기록이 있는 상태에서는 방문객/결제 단위를 변경할 수 없습니다.')
    changed=any(p[k]!=s['profile'][k] for k in ['zone','lat','lon','open_hour','close_hour'])
    if changed and s['mode']=='real':
        s['live']=None;s['weather']=None;s['snapshots']=[]
        for row in s['history']:
            for c in ['temp','rain','pop','female']+['age_'+a for a in AGES]:row.pop(c,None)
    s['profile']=p;s['forecast']=None;s.pop('evaluation',None);save(s);return jsonify(ok=True)

@app.get('/api/template')
def template():
    return Response('\ufeffds,y,valid,is_closed\r\n',mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=demand-template.csv'})

@app.get('/api/export')
def export():
    s=required();df=pd.DataFrame(s['history'])
    if not df.empty:df['source']='synthetic' if s['mode']=='demo' else 'user'
    return Response('\ufeff'+df.to_csv(index=False),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename='+('synthetic-demo.csv' if s['mode']=='demo' else 'my-store.csv')})

@app.post('/api/upload')
def upload():
    s=required()
    if s['mode']=='demo':raise ValueError('시연 매장에는 실제 기록을 업로드하지 않습니다. 내 매장으로 시작하세요.')
    file=request.files.get('file')
    if not file:raise ValueError('CSV 파일을 선택하세요.')
    try:
        raw=pd.read_csv(io.StringIO(file.read().decode('utf-8-sig')))
        if 'source' in raw and raw.source.astype(str).eq('synthetic').any():raise ValueError('가상 데이터는 실제 매장 기록으로 업로드할 수 없습니다.')
        df=validate_csv(raw)
    except (UnicodeError,pd.errors.ParserError,pd.errors.EmptyDataError):raise ValueError('UTF-8 CSV 파일인지 확인하세요.')
    # The provider history can also be supplied as optional daily columns.
    s['history']=json.loads(df.assign(ds=df.ds.dt.strftime('%Y-%m-%d')).to_json(orient='records',force_ascii=False))
    s['forecast']=None;s.pop('evaluation',None);save(s);return jsonify(ok=True,count=len(df))

@app.post('/api/refresh')
def refresh():
    s=required()
    if s['mode']=='demo':return jsonify(ok=True,message='시연 모드의 인구·날씨는 가상 데이터입니다. 실제 API를 호출하지 않습니다.')
    s['live']=population(s['profile']);s['weather']=weather(s['profile']);s['forecast']=None
    snap=s.get('snapshots',[])
    live=s['live']
    if live.get('status')=='ok':
        prior=[x for x in snap if x['zone']==live['zone'] and 45*60<=(__import__('datetime').datetime.fromisoformat(live['time'])-__import__('datetime').datetime.fromisoformat(x['time'])).total_seconds()<=75*60]
        if prior:
            old=(prior[-1]['minimum']+prior[-1]['maximum'])/2
            if old:live['change_pct']=round(((live['minimum']+live['maximum'])/2/old-1)*100,1)
        if not snap or snap[-1]['time']!=live['time']:snap.append(live.copy())
    s['snapshots']=snap[-10000:]
    archive=s.get('weather_archive',{})
    if s['weather'].get('status')=='ok':archive[s['weather']['target']]=s['weather']
    s['weather_archive']=dict(sorted(archive.items())[-400:])
    save(s);return jsonify(ok=True)

def enriched_history(s):
    rows=[dict(x) for x in s['history']]
    if s['mode']=='demo':return rows
    from datetime import datetime
    grouped={}
    for snap in s.get('snapshots',[]):
        stamp=datetime.fromisoformat(snap['time'])
        if snap['zone']==s['profile']['zone'] and s['profile']['open_hour']<=stamp.hour<s['profile']['close_hour']:
            # One sample per hour avoids refresh frequency weighting.
            grouped.setdefault(str(stamp.date()),{})[stamp.hour]=snap
    for row in rows:
        w=s.get('weather_archive',{}).get(row['ds'])
        if w:
            row.setdefault('temp',w['temp']);row.setdefault('rain',w['rain'])
        hourly=grouped.get(row['ds'],{})
        if len(hourly)>=max(3,(s['profile']['close_hour']-s['profile']['open_hour'])*.75):
            values=list(hourly.values())
            candidates={'pop':[(x['minimum']+x['maximum'])/2 for x in values],
                        'female':[x['female'] for x in values]}
            candidates.update({'age_'+a:[x['ages'][a] for x in values] for a in AGES})
            for key,items in candidates.items():
                if all(v is not None for v in items):row.setdefault(key,sum(items)/len(items))
    return rows

@app.post('/api/forecast')
def forecast():
    s=required()
    if not FIT_LOCK.acquire(blocking=False):return jsonify(error='다른 예측을 계산 중입니다. 잠시 후 다시 눌러주세요.'),429
    try:s['forecast']=predict_rows(enriched_history(s),s['profile'],s.get('weather'))
    finally:FIT_LOCK.release()
    save(s);return jsonify(s['forecast'])

@app.post('/api/evaluate')
def evaluation():
    s=required()
    if not FIT_LOCK.acquire(blocking=False):return jsonify(error='예측 계산 중입니다. 잠시 후 다시 시도하세요.'),429
    try:s['evaluation']=evaluate(s['history'],s['profile'])
    finally:FIT_LOCK.release()
    save(s);return jsonify(s['evaluation'])

@app.post('/api/leave-demo')
def leave_demo():
    s=required()
    if s['mode']!='demo':raise ValueError('실제 기록은 삭제하지 않습니다.')
    with connection() as con:con.execute('DELETE FROM stores WHERE id=?',(ident(),))
    return jsonify(ok=True)

if __name__=='__main__':
    from waitress import serve
    serve(app,host='0.0.0.0' if PUBLIC else '127.0.0.1',port=int(os.getenv('PORT','8765')),threads=4)
