import io
import os
import json
import sqlite3
import csv
import secrets
from pathlib import Path
from datetime import timedelta, date, datetime
import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, send_from_directory, Response, session, has_request_context, redirect
from engine import now, number, validate_sales, forecast, backtest
from areas import default_area, validate_area, PRESETS, FEATURES, preview

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'shop.db'
app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['LIVE_SERVER'] = os.environ.get('MORNING_LIVE_SERVER') == '1'
LIVE_ORIGINS = {'http://127.0.0.1:5500', 'http://localhost:5500'}

def connection():
    path = DB
    if app.config.get('PUBLIC_DEMO') and has_request_context():
        ident = session.get('demo_id')
        if not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
            ident = secrets.token_hex(16)
            session['demo_id'] = ident
        path = Path(app.config['DEMO_DATA_DIR']) / (ident + '.db')
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    return con

def load(key, default=None):
    with connection() as con:
        row = con.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

def save_many(values):
    with connection() as con:
        for key, value in values.items():
            con.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key,json.dumps(value,ensure_ascii=False,allow_nan=False)))

def serialize(df):
    return json.loads(df.to_json(orient='records',date_format='iso'))

def sales_frame():
    df = pd.DataFrame(load('sales', []))
    if df.empty:
        raise ValueError('판매 기록을 먼저 업로드하세요.')
    df.ds = pd.to_datetime(df.ds)
    return df

def demo():
    today = now().date()
    items = [{'id': 'ham', 'name':'햄치즈 샌드위치','price':6500,'buffer':2}, {'id':'egg','name':'에그 샌드위치','price':6000,'buffer':1}, {'id':'bagel','name':'크림치즈 베이글','price':5500,'buffer':1}, {'id':'salmon','name':'연어 베이글','price':8500,'buffer':0}, {'id':'latte','name':'카페라떼','price':4500,'buffer':0}]
    materials = []
    for ident,name,unit,stock,pack,cost in [('bread','식빵','장',40,20,180),('ham','햄','g',700,500,14),('cheese','슬라이스 치즈','장',40,20,220),('egg','달걀','개',30,30,280),('bagel','베이글','개',30,10,900),('cream','크림치즈','g',800,1000,12),('salmon','훈제 연어','g',600,500,35),('milk','우유','mL',6000,1000,2.5),('coffee','원두','g',800,1000,25)]:
        materials.append({'id':ident,'name':name,'unit':unit,'stock':stock,'pack_size':pack,'unit_cost':cost,'remaining_today':0,'expiry_date':str(today+timedelta(days=3)),'incoming_qty':0,'incoming_date':str(today+timedelta(days=1)),'incoming_expiry':str(today+timedelta(days=5)),'lead_time_days':1,'cutoff':'15:00'})
    config = {'name':'모닝컵','source':'demo','items':items,'materials':materials,'recipes':{'ham':{'bread':2,'ham':40,'cheese':1},'egg':{'bread':2,'egg':2},'bagel':{'bagel':1,'cream':35},'salmon':{'bagel':1,'salmon':60,'cream':20},'latte':{'milk':200,'coffee':18}}}
    rng = np.random.default_rng(17)
    rows=[]
    for offset in range(180):
        ds=today-timedelta(days=180-offset)
        temp=18+9*np.sin(offset/65)+rng.normal(0,2)
        rain=float(rng.choice([0,0,0,2,8,20]))
        for i,it in enumerate(items):
            qty=max(0,round([25,20,23,12,45][i] + (ds.weekday()>=5)*8 + offset*.015 - rain*.22 + rng.normal(0,3)))
            rows.append({'ds':str(ds),'item_id':it['id'],'y':qty,'temp_open_mean':round(temp,1),'rain_open_mm':rain,'open_hours':10,'discount_rate':0,'is_closed':0,'sales_data_valid':1,'item_available':1,'stockout_minutes':0,'confirmed_order_qty':0})
    return config, rows

def validate_config(c):
    c['area'] = validate_area(c.get('area', default_area()))
    if not isinstance(c.get('name'),str) or not c['name'].strip():
        raise ValueError('매장 이름이 필요합니다.')
    for key in ['items','materials']:
        if not c.get(key) or len(c[key]) > 30:
            raise ValueError('메뉴와 재료는 각각 1~30개 등록할 수 있습니다.')
        ids=[x['id'] for x in c[key]]
        if len(ids)!=len(set(ids)) or not all(isinstance(i,str) and i.strip() for i in ids):
            raise ValueError('메뉴·재료 ID는 비어 있거나 중복될 수 없습니다.')
        if any(not str(x.get('name','')).strip() for x in c[key]):
            raise ValueError('이름을 입력하세요.')
    for it in c['items']:
        for key in ['price','buffer']:
            it[key]=number(it[key],key)
    for m in c['materials']:
        for key in ['stock','unit_cost','remaining_today','incoming_qty']:
            m[key]=number(m[key],key)
        m['pack_size']=number(m['pack_size'],'주문 묶음',.001)
        lead=number(m['lead_time_days'],'납기',0,365)
        if not lead.is_integer():
            raise ValueError('납기는 정수 일수여야 합니다.')
        m['lead_time_days']=int(lead)
        for k in ['expiry_date','incoming_date','incoming_expiry']:
            date.fromisoformat(m[k])
        datetime.strptime(m['cutoff'],'%H:%M')
        if m['incoming_expiry'] < m['incoming_date']:
            raise ValueError('입고 사용기한은 입고일 이후여야 합니다.')
    mats={m['id'] for m in c['materials']}
    ids={i['id'] for i in c['items']}
    if not set(c['recipes']).issubset(ids):
        raise ValueError('레시피에 알 수 없는 메뉴 ID가 있습니다.')
    for ident in ids:
        rec=c['recipes'].get(ident,{})
        if not rec or not set(rec).issubset(mats):
            raise ValueError('각 메뉴에 등록된 재료로 레시피를 입력하세요.')
        for k,v in rec.items():
            rec[k]=number(v,'레시피 사용량',.001)
    return c

@app.before_request
def local_only():
    public = app.config.get('PUBLIC_DEMO', False)
    #if not public and request.host.split(':')[0] not in ('127.0.0.1','localhost'):
    #    return jsonify(error='로컬 접속만 지원합니다.'),403
    if request.method == 'POST':
        origin=request.headers.get('Origin')
        allowed = ('http://'+request.host, 'https://'+request.host)
        if not public and app.config['LIVE_SERVER']:
            allowed = (*allowed, *LIVE_ORIGINS)
        if origin and origin not in allowed:
            return jsonify(error='다른 사이트의 요청은 허용하지 않습니다.'),403
        if not request.is_json:
            return jsonify(error='JSON 요청이 필요합니다.'),415
    if public:
        if request.path in ('/api/upload', '/api/start-real'):
            return jsonify(error='공개 체험판에서는 샘플 데이터만 사용합니다. 실제 판매 파일은 로컬 프로그램에서 업로드하세요.'),403
        if not request.path.startswith('/static/') and not load('config'):
            c, s = demo()
            save_many({'config': c, 'sales': s})

@app.after_request
def demo_headers(response):
    origin = request.headers.get('Origin')
    if not app.config.get('PUBLIC_DEMO') and app.config['LIVE_SERVER'] and origin in LIVE_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.vary.add('Origin')
    if app.config.get('PUBLIC_DEMO'):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
    return response

@app.errorhandler(ValueError)
@app.errorhandler(KeyError)
@app.errorhandler(TypeError)
@app.errorhandler(pd.errors.ParserError)
@app.errorhandler(pd.errors.EmptyDataError)
def invalid(err):
    return jsonify(error=str(err)),400

@app.errorhandler(413)
def too_large(err):
    return jsonify(error='파일은 8MB 이하만 가능합니다.'),413

@app.get('/')
def home():
    return redirect('/static/index.html')

@app.get('/api/state')
def state():
    config=load('config')
    if not config:
        return jsonify(needs_setup=True, area_presets=PRESETS)
    config.setdefault('area', default_area())
    sales=load('sales',[])
    daily={}
    for row in sales:
        ds=row['ds'][:10]
        daily[ds]=daily.get(ds,0)+row['y']
    return jsonify(public_demo=bool(app.config.get('PUBLIC_DEMO')), config=config, area_presets=PRESETS, area_features=FEATURES, area_preview=preview(config['area'], now().date()+timedelta(days=1)), sales_count=len(sales), sales_start=min(daily) if daily else None, sales_end=max(daily) if daily else None, history=[{'date':d,'qty':daily[d]} for d in sorted(daily)[-28:]], plan=load('plan'), closings=load('closings',[]), comparison=load('comparison'), tomorrow=str(now().date()+timedelta(days=1)), now=now().isoformat(), draft=load('draft'))

@app.post('/api/area')
def area_settings():
    a = validate_area(request.json)
    a['selected'] = True
    a['updated_at'] = now().isoformat()
    c = load('config')
    c['area'] = a
    save_many({'config': c, 'plan': None, 'draft': None, 'comparison': None})
    return jsonify(ok=True)

@app.post('/api/setup')
def setup_shop():
    if app.config.get('PUBLIC_DEMO'):
        return jsonify(error='공개 체험판에서는 사용할 수 없습니다.'),403
    if load('config'):
        return jsonify(error='이미 설정된 매장입니다. 매장 설정에서 수정하세요.'),409
    mode=request.json.get('mode')
    if mode not in ('demo','real'):
        raise ValueError('샘플 체험 또는 내 가게로 시작을 선택하세요.')
    if mode=='demo':
        c,s=demo()
    else:
        name=request.json.get('name','').strip()
        if not name or len(name)>100:
            raise ValueError('매장 이름을 1~100자로 입력하세요.')
        area=validate_area({**default_area(),'type':request.json.get('area_type'),'selected':True})
        c={'name':name,'source':'real','area':area,'items':[],'materials':[],'recipes':{}}
        s=[]
    save_many({'config':c,'sales':s,'plan':None,'draft':None,'closings':[],'comparison':None})
    return jsonify(ok=True)

@app.post('/api/config')
def settings():
    c=validate_config(request.json)
    c['source']=load('config')['source']
    old_ids={r['item_id'] for r in load('sales',[])}
    if not old_ids.issubset({i['id'] for i in c['items']}):
        raise ValueError('판매 이력이 있는 메뉴 ID는 삭제할 수 없습니다. 실제 매장 전환 후 수정하세요.')
    save_many({'config':c,'plan':None,'draft':None,'comparison':None})
    return jsonify(ok=True)

@app.post('/api/start-real')
def start_real():
    c=load('config'); c['source']='real'
    for m in c['materials']:
        m['stock']=0; m['incoming_qty']=0; m['remaining_today']=0
    save_many({'config':c,'sales':[],'plan':None,'draft':None,'closings':[],'comparison':None})
    return jsonify(ok=True)

@app.post('/api/upload')
def upload():
    c=load('config')
    if c['source']=='demo':
        raise ValueError('먼저 실제 매장으로 전환하세요. 샘플 재고와 실제 판매를 섞지 않습니다.')
    df=validate_sales(pd.read_csv(io.StringIO(request.json['csv']),dtype={'item_id':str}),c['items'])
    if df.empty:
        raise ValueError('판매 행이 없습니다.')
    save_many({'sales':serialize(df),'plan':None,'draft':None,'comparison':None})
    return jsonify(ok=True,rows=len(df))

@app.get('/api/template')
def template():
    config=load('config')
    rows=[]
    for it in config['items']:
        rows.append({'ds':str(now().date()-timedelta(days=1)),'item_id':it['id'],'y':0,'temp_open_mean':24,'rain_open_mm':0,'open_hours':10,'discount_rate':0,'is_closed':0,'sales_data_valid':1,'item_available':1,'stockout_minutes':0,'confirmed_order_qty':0})
    return Response('\ufeff'+pd.DataFrame(rows).to_csv(index=False),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=sales-template.csv'})

@app.post('/api/forecast')
def run_forecast():
    c=load('config')
    if not c or not c.get('items') or not c.get('materials'):
        raise ValueError('먼저 메뉴·재료·레시피를 등록하세요.')
    plan=forecast(sales_frame(),load('config'),request.json)
    save_many({'plan':plan,'draft':None})
    return jsonify(plan)

@app.post('/api/backtest')
def run_backtest():
    result=backtest(sales_frame(),load('config'))
    save_many({'comparison':result})
    return jsonify(result)

@app.post('/api/draft')
def draft():
    p=load('plan')
    if not p or p['target']!=str(now().date()+timedelta(days=1)):
        raise ValueError('내일 예측을 먼저 실행하세요.')
    quantities=request.json['packs']
    orders=[]
    for row in p['orders']:
        packs=number(quantities[row['id']],row['name'],0,1e6)
        if not packs.is_integer():
            raise ValueError('발주 묶음 수는 정수여야 합니다.')
        orders.append({**row,'approved_packs':int(packs),'approved_qty':packs*row['pack_size'],'approved_cost':round(packs*row['pack_size']*row['unit_cost'])})
    d={'target':p['target'],'saved_at':now().isoformat(),'status':'초안 저장 · 거래처 미전송','orders':orders}
    save_many({'draft':d})
    return jsonify(d)

@app.get('/api/order.csv')
def export_order():
    d=load('draft')
    if not d:
        raise ValueError('발주 초안을 먼저 저장하세요.')
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(['필요일','재료','묶음 수','수량','단위','예상 원가','예상 입고일','상태'])
    def safe(v):
        s=str(v)
        return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
    for r in d['orders']:
        w.writerow([safe(v) for v in [d['target'],r['name'],r['approved_packs'],r['approved_qty'],r['unit'],r['approved_cost'],r['arrival'],d['status']]])
    return Response('\ufeff'+out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=order-draft.csv'})

@app.post('/api/closing')
def closing():
    data=request.json; ds=date.fromisoformat(data['date'])
    if ds > now().date():
        raise ValueError('미래 날짜의 마감은 기록할 수 없습니다.')
    config=load('config')
    for row in data['items']:
        if row['id'] not in {i['id'] for i in config['items']}:
            raise ValueError('알 수 없는 메뉴입니다.')
        for col in ['waste','left','stockout_minutes']:
            row[col]=number(row[col],col,0,1440 if col=='stockout_minutes' else 1e8)
    records=load('closings',[])
    records=[r for r in records if r['date']!=data['date']]+[data]
    sales=load('sales',[])
    for sale in sales:
        for row in data['items']:
            if sale['ds'][:10]==data['date'] and sale['item_id']==row['id']:
                sale['stockout_minutes']=row['stockout_minutes']
    save_many({'closings':records,'sales':sales,'plan':None,'draft':None,'comparison':None})
    return jsonify(ok=True)

if __name__=='__main__':
    # Railway가 환경 변수로 지정한 포트를 가져오거나, 없으면 8765를 사용합니다.
    port = int(os.environ.get("PORT", 8765))
    # host를 '0.0.0.0'으로 설정하여 Railway 플랫폼의 외부 접속을 허용합니다.
    app.run(host='0.0.0.0', port=port, debug=False, threaded=False)
