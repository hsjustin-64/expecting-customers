"""Single-store daily forecast and next-day procurement calculations."""
import math
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).resolve().parent / 'data' / 'matplotlib'))
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
from prophet import Prophet
from stan_compat import configure_stan
configure_stan()
from areas import enrich, default_area, preview

KST = timezone(timedelta(hours=9))
REGRESSORS = ['temp_open_mean', 'rain_open_mm', 'open_hours', 'discount_rate']

def now():
    return datetime.now(KST)

def number(value, name, low=0, high=1e12):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name}: 숫자를 입력해 주세요.')
    if not math.isfinite(v) or not low <= v <= high:
        raise ValueError(f'{name}: {low}~{high} 범위로 입력해 주세요.')
    return v

def validate_sales(df, items):
    required = ['ds', 'item_id', 'y']
    if not set(required).issubset(df.columns):
        raise ValueError('CSV 필수 열: ds, item_id, y')
    df = df.copy()
    df['ds'] = pd.to_datetime(df.ds, format='%Y-%m-%d', errors='coerce')
    if df.ds.isna().any():
        raise ValueError('날짜는 YYYY-MM-DD 형식이어야 합니다.')
    if (df.ds >= pd.Timestamp(now().date())).any():
        raise ValueError('판매 이력은 어제까지의 마감된 날짜만 업로드해 주세요.')
    df['item_id'] = df.item_id.astype(str)
    if not set(df.item_id).issubset({i['id'] for i in items}):
        raise ValueError('등록되지 않은 item_id가 있습니다. 매장 설정에서 메뉴를 먼저 등록하세요.')
    if df.duplicated(['ds', 'item_id']).any():
        raise ValueError('같은 날짜·메뉴가 중복되었습니다. 하루 수량으로 합산해 주세요.')
    for col, default in [('is_closed', 0), ('sales_data_valid', 1), ('item_available', 1), ('stockout_minutes', 0), ('confirmed_order_qty', 0)]:
        if col not in df:
            df[col] = default
    for col in ['y', 'stockout_minutes', 'confirmed_order_qty']:
        df[col] = [number(v, col) for v in df[col]]
    for col in ['is_closed', 'sales_data_valid', 'item_available']:
        if not df[col].isin([0, 1]).all():
            raise ValueError(f'{col}: 0 또는 1만 가능합니다.')
    if (df.confirmed_order_qty > df.y).any():
        raise ValueError('예약 판매 수량은 전체 판매 수량보다 클 수 없습니다.')
    for col in REGRESSORS:
        if col in df:
            limits = {'temp_open_mean': (-60, 60), 'rain_open_mm': (0, 1000), 'open_hours': (0, 24), 'discount_rate': (0, 1)}[col]
            df[col] = [number(v, col, *limits) for v in df[col]]
    return df.sort_values('ds')

def clean(df):
    out = df[(df.is_closed == 0) & (df.sales_data_valid == 1) & (df.item_available == 1) & (df.stockout_minutes == 0)].copy()
    out['y'] = out.y - out.confirmed_order_qty
    return out

def baseline(df, target):
    same = df[df.ds.dt.dayofweek == pd.Timestamp(target).dayofweek].tail(4)
    return float((same if len(same) else df.tail(14)).y.mean())

def predict(df, target, weather=None, area_features=()):
    if len(df) < 14:
        raise ValueError('품질 조건을 만족하는 판매 이력이 최소 14일 필요합니다.')
    if len(df) < 42:
        y = baseline(df, target)
        spread = float(df.tail(28).y.std(ddof=0))
        return y, max(0, y-spread), y+spread, '같은 요일 평균', []
    model = Prophet(weekly_seasonality=True, yearly_seasonality=False, daily_seasonality=False, interval_width=.8, uncertainty_samples=200)
    model.add_country_holidays(country_name='KR')
    regs = [c for c in REGRESSORS + list(area_features) if weather is not None and c in df and df[c].nunique() > 1]
    for col in regs:
        model.add_regressor(col, prior_scale=2.0 if col in area_features else 10.0)
    model.fit(df[['ds', 'y'] + regs])
    future = pd.DataFrame([{'ds': pd.Timestamp(target), **{c: weather[c] for c in regs}}])
    p = model.predict(future).iloc[0]
    return max(0, float(p.yhat)), max(0, float(p.yhat_lower)), max(0, float(p.yhat_upper)), 'Prophet', regs

def forecast(sales, config, request):
    timestamp = now()
    target = timestamp.date() + timedelta(days=1)
    issued = datetime.fromisoformat(request['issued_at'])
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=KST)
    if issued > timestamp:
        raise ValueError('예보 발표 시각은 현재보다 미래일 수 없습니다.')
    if issued.date() < timestamp.date() - timedelta(days=3):
        raise ValueError('예보가 오래되었습니다. 최근 발표된 내일 예보를 입력하세요.')
    weather = {c: number(request[c], c, *{'temp_open_mean': (-60,60), 'rain_open_mm': (0,1000), 'open_hours': (0,24), 'discount_rate': (0,1)}[c]) for c in REGRESSORS}
    closed = bool(request.get('is_closed')) or weather['open_hours'] == 0
    rows = []
    for item in config['items']:
        data = clean(sales[sales.item_id == item['id']])
        data, area_values, area_status = enrich(data, target, config.get('area', default_area()))
        if closed:
            y, lo, hi, model, regs = 0, 0, 0, '예정 휴무', []
            for s in area_status:
                s.update(used=False, reason='예정 휴무로 판매량을 0으로 설정')
        else:
            y, lo, hi, model, regs = predict(data, target, {**weather, **area_values}, area_values.keys())
        reserved = number(request.get('reservations', {}).get(item['id'], 0), '내일 예약 수량')
        if closed and reserved:
            raise ValueError('휴무일 예약이 있습니다. 예약 또는 휴무 설정을 확인하세요.')
        buffer = number(item.get('buffer', 0), '메뉴별 여유 수량', 0, 10000)
        prep = 0 if closed else math.ceil(y + reserved + buffer)
        rows.append({'id': item['id'], 'name': item['name'], 'predicted': round(y+reserved,1), 'lower': round(lo+reserved,1), 'upper': round(hi+reserved,1), 'prepare': prep, 'reserved': reserved, 'buffer': buffer, 'model': model, 'regressors': regs, 'usable_days': len(data), 'excluded_days': len(sales[sales.item_id == item['id']])-len(data), 'revenue': round((y+reserved)*item['price']*(1-weather['discount_rate']))})
        rows[-1]['area_status'] = area_status
    return {'target': str(target), 'created_at': timestamp.isoformat(), 'issued_at': issued.isoformat(), 'weather': weather, 'area': preview(config.get('area', default_area()), target), 'items': rows, 'orders': procurement(rows, config, target, timestamp), 'source': config['source']}

def procurement(rows, config, target, timestamp):
    result = []
    for mat in config['materials']:
        needed = sum(r['prepare'] * config['recipes'].get(r['id'], {}).get(mat['id'], 0) for r in rows)
        stock = mat['stock'] if mat['expiry_date'] >= str(target) else 0
        available = max(0, stock-mat['remaining_today'])
        incoming = mat['incoming_qty'] if mat['incoming_date'] <= str(target) and mat['incoming_expiry'] >= str(target) and mat['incoming_date'] >= str(timestamp.date()) else 0
        shortage = max(0, needed-available-incoming)
        packs = math.ceil(round(shortage / mat['pack_size'], 10))
        cutoff = datetime.strptime(mat['cutoff'], '%H:%M').time()
        arrival = timestamp.date() + timedelta(days=mat['lead_time_days'] + (timestamp.time().replace(tzinfo=None) > cutoff))
        result.append({**mat, 'needed': round(needed,2), 'available': round(available,2), 'incoming_usable': incoming, 'expired': mat['stock'] if mat['expiry_date'] < str(target) else 0, 'packs': packs, 'order_qty': packs*mat['pack_size'], 'cost': round(packs*mat['pack_size']*mat['unit_cost']), 'arrival': str(arrival), 'late': bool(packs and arrival > target), 'excess': round(max(0, available+incoming+packs*mat['pack_size']-needed),2)})
    return result

def backtest(sales, config):
    """Seven rolling targets; exclude day before target (incomplete at 14:00)."""
    result = []
    for item in config['items']:
        df = clean(sales[sales.item_id == item['id']])
        errors, bases = [], []
        for target in df.ds.tail(7):
            train = df[df.ds < target-pd.Timedelta(days=1)]
            if len(train) < 42:
                continue
            pred = predict(train, target)[0]
            actual = float(df.loc[df.ds == target, 'y'].iloc[0])
            errors.append(abs(pred-actual))
            bases.append(abs(baseline(train, target)-actual))
        result.append({'name': item['name'], 'days': len(errors), 'prophet_mae': round(float(np.mean(errors)),2) if errors else None, 'baseline_mae': round(float(np.mean(bases)),2) if bases else None})
    return result
