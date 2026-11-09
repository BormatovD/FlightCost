"""Множитель «средний чек ÷ p10 пары» как функция потока пары (T-100, оба направления, все перевозчики).

Подбор на половине пар (по хэшу), проверка на другой половине; сравнение
со ступенькой 1,2/2,0 (решение 210) в единицах p10 (× 1,37 — кэш ÷ p10).
    python3 thick_fit.py <свёртки DB1C> <T-100 csv>
"""
import csv, glob, json, math, statistics as S, sys, zlib, collections
import numpy as np
D, T = sys.argv[1], sys.argv[2]
flow = collections.defaultdict(float)              # (пара, ГГГГ-ММ) -> пассажиров T-100, оба направления
for r in csv.DictReader(open(T, encoding='utf-8-sig')):
    if r['CLASS'] not in ('F', 'L'):
        continue
    a, b = sorted((r['ORIGIN'], r['DEST']))
    flow[(f'{a}-{b}', f"{int(r['YEAR'])}-{int(r['MONTH']):02d}")] += float(r['PASSENGERS'] or 0)
rows = []
for f in sorted(glob.glob(D + '/DB1C-2025-*.json')):
    d = json.load(open(f))
    for pair, v in d['pairs'].items():
        q = flow.get((pair, d['month']))
        if q and q > 0:
            dr = v['direct']
            rows.append((pair, q, dr['mean'], dr['p10']))
train = [r for r in rows if zlib.crc32(r[0].encode()) % 2 == 0]
test = [r for r in rows if zlib.crc32(r[0].encode()) % 2 == 1]
X = np.array([[1, math.log(q)] for _, q, _, _ in train]); y = np.array([math.log(m / p) for _, _, m, p in train])
(al, be), *_ = np.linalg.lstsq(X, y, rcond=None)
const = math.exp(np.median(y))
print(f'пар-месяцев: подбор {len(train)}, проверка {len(test)}')
print(f'ln(средний/p10) = {al:.3f} + {be:.4f}·ln(поток); при 5 тыс. → {math.exp(al+be*math.log(5e3)):.2f}, '
      f'50 тыс. → {math.exp(al+be*math.log(5e4)):.2f}, 200 тыс. → {math.exp(al+be*math.log(2e5)):.2f}')
def err(pred):
    e = [pred(q) * p / m - 1 for _, q, m, p in test]
    return S.median(e) * 100, S.median(sorted(abs(x) for x in e)) * 100
for name, f in (('ступенька 1,2/2,0 × 1,37', lambda q: 1.37 * (2.0 if q >= 80000 else 1.2)),
                ('константа (медиана)', lambda q: const),
                ('от потока', lambda q: math.exp(al + be * math.log(q)))):
    b, a = err(f); print(f'{name:28} смещение {b:+.0f}%, медиана |ошибки| {a:.0f}%')
bins = [0, 5e3, 2e4, 8e4, 1e9]
for lo, hi in zip(bins, bins[1:]):
    t = [r for r in test if lo <= r[1] < hi]
    if t:
        for name, f in (('ступенька', lambda q: 1.37 * (2.0 if q >= 80000 else 1.2)), ('от потока', lambda q: math.exp(al + be * math.log(q)))):
            e = [f(q) * p / m - 1 for _, q, m, p in t]
            print(f'  поток {lo/1e3:.0f}–{hi/1e3:.0f} тыс., n {len(t):5}: {name:10} смещение {S.median(e)*100:+.0f}%  |ош| {S.median(sorted(abs(x) for x in e))*100:.0f}%')
json.dump({'alpha': al, 'beta': be, 'n_train': len(train)}, open('thick_fit.json', 'w'))
