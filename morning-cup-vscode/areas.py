"""User-confirmed local calendars. Unknown coverage never becomes a zero."""
from datetime import date
import pandas as pd

FEATURES = {
    'semester': '학기 중',
    'exam_period': '시험 기간',
    'office_low_attendance': '주변 회사 휴무·출근 감소 기간',
    'school_vacation': '초·중·고 방학',
    'peak_season': '지역 관광 성수기',
    'local_event': '주변 축제·행사',
}
PRESETS = {
    'university': {'name': '대학가', 'description': '학기와 시험 일정에 따라 달라지는 학생 수요', 'features': ['semester', 'exam_period', 'local_event']},
    'office': {'name': '오피스', 'description': '주변 회사의 휴무·출근 감소 일정과 행사', 'features': ['office_low_attendance', 'local_event']},
    'residential': {'name': '주거', 'description': '주변 학교 방학과 동네 행사', 'features': ['school_vacation', 'local_event']},
    'tourist': {'name': '관광·나들이', 'description': '지역별 성수기와 축제·행사', 'features': ['peak_season', 'local_event']},
    'mixed': {'name': '복합·기타', 'description': '여러 고객층이 섞인 상권의 주변 행사', 'features': ['local_event']},
}

def default_area():
    return {'type': 'mixed', 'selected': False, 'place': '', 'coverage_start': '', 'coverage_end': '', 'confirmed': False, 'periods': []}

def validate_area(value):
    a = {**default_area(), **value}
    if a['type'] not in PRESETS:
        raise ValueError('지원하지 않는 상권 유형입니다.')
    if not isinstance(a['place'], str) or len(a['place']) > 200:
        raise ValueError('주변 대학·회사·지역 이름은 200자 이내로 입력하세요.')
    if not isinstance(a['confirmed'], bool) or not isinstance(a['selected'], bool):
        raise ValueError('상권 확인 값이 올바르지 않습니다.')
    if not isinstance(a['periods'], list) or len(a['periods']) > 200:
        raise ValueError('일정은 최대 200개까지 등록할 수 있습니다.')
    if a['coverage_start'] or a['coverage_end'] or a['confirmed'] or a['periods']:
        start, end = date.fromisoformat(a['coverage_start']), date.fromisoformat(a['coverage_end'])
        if start > end:
            raise ValueError('일정 확인 기간의 시작일이 종료일보다 늦습니다.')
        for p in a['periods']:
            if p['feature'] not in PRESETS[a['type']]['features']:
                raise ValueError('선택한 상권에 맞지 않는 일정이 있습니다.')
            ps, pe = date.fromisoformat(p['start']), date.fromisoformat(p['end'])
            if not start <= ps <= pe <= end:
                raise ValueError('각 일정의 시작·종료일은 일정 확인 기간 안에 있어야 합니다.')
            if not isinstance(p.get('label', ''), str) or len(p.get('label', '')) > 200:
                raise ValueError('일정 이름은 200자 이내로 입력하세요.')
    return a

def preview(area, target):
    a = {**default_area(), **area}
    known = bool(a['selected'] and a['confirmed'] and a['coverage_start'] <= str(target) <= a['coverage_end'])
    values = {}
    for f in PRESETS[a['type']]['features']:
        values[f] = int(any(p['feature'] == f and p['start'] <= str(target) <= p['end'] for p in a['periods'])) if known else None
    return {'name': PRESETS[a['type']]['name'], 'place': a['place'], 'known': known, 'values': values}

def enrich(df, target, area):
    """Build the same binary variables for history and target, with support gates."""
    a = {**default_area(), **area}
    info = preview(a, target)
    result = df.copy()
    future, status = {}, []
    for f in PRESETS[a['type']]['features']:
        reason = ''
        on = off = 0
        if not a['selected']:
            reason = '상권을 아직 선택하지 않았습니다.'
        elif not a['confirmed']:
            reason = '과거·미래 일정 확인이 필요합니다.'
        elif not info['known'] or df.empty or str(df.ds.min().date()) < a['coverage_start'] or str(df.ds.max().date()) > a['coverage_end']:
            reason = '일정 확인 기간이 학습 이력 전체와 내일을 포함해야 합니다.'
        else:
            active = pd.Series(False, index=df.index)
            for p in a['periods']:
                if p['feature'] == f:
                    active |= df.ds.between(pd.Timestamp(p['start']), pd.Timestamp(p['end']))
            on, off = int(active.sum()), int((~active).sum())
            if len(df) < 42:
                reason = 'Prophet 학습에 필요한 유효 이력 42일이 부족합니다.'
            elif min(on, off) < 7:
                reason = '해당 기간·그 외 기간의 유효 판매 기록이 각각 7일 이상 필요합니다.'
            elif any(active.astype(int).equals(result[k]) for k in future):
                reason = '다른 상권 일정과 완전히 겹쳐 중복 변수를 제외했습니다.'
            else:
                result[f] = active.astype(int)
                future[f] = info['values'][f]
        status.append({'feature': f, 'label': FEATURES[f], 'value': info['values'][f], 'active_days': on, 'other_days': off, 'used': not bool(reason), 'reason': reason or '과거 일정과 판매 기록으로 학습'})
    return result, future, status
