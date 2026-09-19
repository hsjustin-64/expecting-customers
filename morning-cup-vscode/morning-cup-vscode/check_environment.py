"""Smoke-test the installed Prophet binary, not just its import."""
import math
from importlib.metadata import version

def main():
    import pandas as pd
    from prophet import Prophet
    from stan_compat import configure_stan
    configure_stan()
    dates = pd.date_range('2025-01-01', periods=90)
    history = pd.DataFrame({'ds': dates, 'y': [20 + i * .03 + 3 * math.sin(i * 2 * math.pi / 7) for i in range(90)],
                            'temperature': [10 + math.sin(i / 5) * 5 for i in range(90)]})
    model = Prophet(weekly_seasonality=True, daily_seasonality=False, yearly_seasonality=False)
    model.add_country_holidays(country_name='KR')
    model.add_regressor('temperature')
    model.fit(history)
    result = model.predict(pd.DataFrame({'ds': [dates[-1] + pd.Timedelta(days=1)], 'temperature': [13]}))
    assert all(math.isfinite(float(result.iloc[0][k])) for k in ('yhat', 'yhat_lower', 'yhat_upper'))
    for name in ('prophet', 'pandas', 'Flask'):
        print(f'{name}: {version(name)}')
    print('PASS: real Prophet fit + next-day prediction =', round(float(result.iloc[0]['yhat']), 3))

if __name__ == '__main__':
    main()
