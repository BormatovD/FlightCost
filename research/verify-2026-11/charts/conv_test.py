"""Множитель «средний чек к 10-му перцентилю пары» по типу перевозчика.

Подбор — по перевозчикам вне контрольной выборки (взвешенная медиана),
проверка — на Frontier и Southwest против прежнего правила 1,2/2,0
(в единицах p10: × 1,37 — медиана «кэш агрегатора ÷ p10» по 13 парам).
    python3 conv_test.py <папка со свёртками DB1C>
"""
import glob, json, statistics as S, sys
D = sys.argv[1] if len(sys.argv) > 1 else '../in/agg3'
ULCC = {'F9', 'NK', 'G4', 'SY', 'MX'}
CLS = {'NK': 'ulcc', 'G4': 'ulcc', 'SY': 'ulcc', 'MX': 'ulcc', 'F9': 'ulcc', 'WN': 'lcc', 'B6': 'lcc', 'AS': 'lcc',
       'HA': 'lcc', 'AA': 'network', 'UA': 'network', 'DL': 'network'}
docs = [json.load(open(f)) for f in sorted(glob.glob(D + '/DB1C-*.json'))]
obs = {}
for d in docs:
    for pair, v in d['pairs'].items():
        cs = v.get('carriers') or {}
        mixed = any(c in ULCC for c in cs)
        for c, x in cs.items():
            if c in CLS and x['pax'] >= 100 and c not in ('F9', 'WN'):
                obs.setdefault((CLS[c], mixed), []).append((x['mean'] / v['direct']['p10'], x['pax']))
def wmed(xs):
    xs = sorted(xs); tot = sum(w for _, w in xs); acc = 0
    for val, w in xs:
        acc += w
        if acc >= tot / 2:
            return val
cal = {k: wmed(v) for k, v in obs.items()}
for k, v in sorted(cal.items()):
    print('калибровка', k, round(v, 2))
res = {}
for d in docs:
    for pair, v in d['pairs'].items():
        cs = v.get('carriers') or {}
        mixed = any(c in ULCC for c in cs); thick = v['all']['pax'] / 0.4 >= 80000
        for c, cls in (('F9', 'ulcc'), ('WN', 'lcc')):
            x = cs.get(c)
            if not x or x['pax'] < 100:
                continue
            p10 = v['direct']['p10']
            res.setdefault(c, []).append((p10 * 1.37 * (2.0 if thick else 1.2) / x['mean'] - 1,
                                          p10 * cal[(cls, mixed)] / x['mean'] - 1))
for c, L in res.items():
    for i, n in ((0, 'старое правило 1,2/2,0'), (1, 'по типу перевозчика')):
        e = [x[i] for x in L]
        print(c, n, 'n', len(L), 'смещение %+.0f%%, медиана |ошибки| %.0f%%' % (S.median(e) * 100, S.median(sorted(abs(t) for t in e)) * 100))
