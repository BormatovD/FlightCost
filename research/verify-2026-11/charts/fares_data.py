"""Данные доходной части статьи -> out/fares.json (из свёрток DB1C и T-100; сырьё в репозиторий не кладётся).

    python3 charts/fares_data.py <папка свёрток DB1C> <T-100 csv>
"""
import collections, csv, glob, json, math, statistics as S, sys, zlib, pathlib
import numpy as np
import airportsdata
HERE = pathlib.Path(__file__).resolve().parents[1]
D, T100 = sys.argv[1], sys.argv[2]
AP = airportsdata.load('IATA')
ULCC = {'F9', 'NK', 'G4', 'SY', 'MX'}


def gc(a, b):
    A, B = AP.get(a), AP.get(b)
    if not A or not B:
        return None
    p1, p2 = math.radians(A['lat']), math.radians(B['lat']); dl = math.radians(B['lon'] - A['lon'])
    return 2 * 6371 * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


docs = [json.load(open(f)) for f in sorted(glob.glob(D + '/DB1C-*.json'))]
rows = []
for d in docs:
    for pair, v in d['pairs'].items():
        km = gc(*pair.split('-'))
        if km:
            rows.append(dict(m=d['month'], pair=pair, km=km, all_pax=v['all']['pax'], carriers=v.get('carriers') or {}, **v['direct']))
out = {}
# 1. ряд: средний тариф по панели пар, которые есть во всех месяцах
cnt = collections.Counter(r['pair'] for r in rows); panel = {p for p, c in cnt.items() if c == len(docs)}
tr = {}
for d in docs:
    rs = [r for r in rows if r['m'] == d['month'] and r['pair'] in panel]
    tr[d['month']] = sum(r['mean'] * r['pax'] for r in rs) / sum(r['pax'] for r in rs)
by_pair = collections.defaultdict(dict)
for r in rows:
    if r['pair'] in panel:
        by_pair[r['pair']][r['m']] = r['mean']
first, last = docs[0]['month'], docs[-1]['month']
out['trend'] = {'panel_pairs': len(panel), 'months': tr,
                'median_pair_growth': S.median(v[last] / v[first] - 1 for v in by_pair.values())}
# 2. бонусные и провал 10–15 USD
out['award'] = {d['month']: {'hist': d['low_fare_hist'],
                             'share': sum(v['direct'].get('award_pax', 0) for v in d['pairs'].values()) /
                             max(1, sum(v['direct'].get('award_pax', 0) + v['direct']['pax'] for v in d['pairs'].values()))}
                for d in docs}
out['rows_total'] = sum(d['rows'] for d in docs)
# 3. глубина покупки по дальности
bins = [0, 500, 1000, 1500, 2000, 3000, 4000, 6000]
bk = []
for lo, hi in zip(bins, bins[1:]):
    rs = [r for r in rows if lo <= r['km'] < hi]
    q = lambda a, b: S.median(r[a] / r[b] for r in rs if r.get(a) and r.get(b))  # noqa: E731
    bk.append({'lo': lo, 'hi': hi, 'n': len(rs), 'r21': q('mean_21AP', 'mean_91UP'), 'r22': q('mean_2290', 'mean_91UP'),
               'share21': S.median(r['share_21AP'] for r in rs if r.get('share_21AP') is not None)})
out['booking'] = bk
# 4. тариф и дальность
xs = np.array([r['km'] for r in rows]); ys = np.array([r['mean'] for r in rows]); w = np.array([r['pax'] for r in rows], float)
def wls(wt):
    W = wt.sum(); mx = (xs * wt).sum() / W; my = (ys * wt).sum() / W
    b = (wt * (xs - mx) * (ys - my)).sum() / (wt * (xs - mx) ** 2).sum(); a = my - b * mx
    r2 = 1 - (wt * (ys - a - b * xs) ** 2).sum() / (wt * (ys - my) ** 2).sum()
    return a, b * 1000, r2
out['distance'] = {'weighted': wls(w), 'unweighted': wls(np.ones_like(w))}
# 5. перевозчики в смешанных рынках
rel = collections.defaultdict(list)
for r in rows:
    cs = r['carriers']
    if any(c in ULCC for c in cs) and any(c not in ULCC for c in cs):
        for c, x in cs.items():
            if x['pax'] >= 100:
                rel[c].append(x['mean'] / r['p10'])
out['carriers_mixed'] = {c: S.median(v) for c, v in rel.items() if len(v) >= 50}
# 6. доля ультралоукостеров
ub = []
for lo, hi in [(0, 1e-9), (1e-9, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]:
    rs = []
    for r in rows:
        cs = r['carriers']; tot = sum(x['pax'] for x in cs.values())
        if not tot or tot < 0.8 * r['pax']:
            continue
        u = sum(x['pax'] for c, x in cs.items() if c in ULCC) / tot
        if lo <= u < hi or (hi == 1e-9 and u == 0):
            rs.append(r)
    ub.append({'lo': lo, 'hi': hi, 'n': len(rs), 'mean': S.median(r['mean'] for r in rs), 'p10': S.median(r['p10'] for r in rs)})
out['ulcc_share'] = ub
# 7. множитель от потока (T-100), подбор и проверка на разных половинах пар
flow = collections.defaultdict(float)
for r in csv.DictReader(open(T100, encoding='utf-8-sig')):
    if r['CLASS'] in ('F', 'L'):
        a, b = sorted((r['ORIGIN'], r['DEST']))
        flow[(f'{a}-{b}', f"{int(r['YEAR'])}-{int(r['MONTH']):02d}")] += float(r['PASSENGERS'] or 0)
fr = [(r['pair'], flow[(r['pair'], r['m'])], r['mean'], r['p10']) for r in rows if r['m'].startswith('2025') and flow.get((r['pair'], r['m']), 0) > 0]
train = [x for x in fr if zlib.crc32(x[0].encode()) % 2 == 0]; test = [x for x in fr if zlib.crc32(x[0].encode()) % 2 == 1]
X = np.array([[1, math.log(q)] for _, q, _, _ in train]); Y = np.array([math.log(m / p) for _, _, m, p in train])
(al, be), *_ = np.linalg.lstsq(X, Y, rcond=None)
const = math.exp(np.median(Y))
rules = {'step': lambda q: 1.37 * (2.0 if q >= 80000 else 1.2), 'const': lambda q: const, 'flow': lambda q: math.exp(al + be * math.log(q))}
def err(rs, f):
    e = [f(q) * p / m - 1 for _, q, m, p in rs]
    return {'bias': S.median(e), 'mae': S.median(sorted(abs(x) for x in e)), 'n': len(rs)}
bands = []
for lo, hi in [(0, 5e3), (5e3, 2e4), (2e4, 8e4), (8e4, 1e12)]:
    t = [x for x in test if lo <= x[1] < hi]
    bands.append({'lo': lo, 'hi': hi, 'step': err(t, rules['step']), 'flow': err(t, rules['flow'])})
# средний/p10 по потоку для графика (все пар-месяцы 2025 с потоком)
curve = []
for lo, hi in [(0, 5e3), (5e3, 1e4), (1e4, 2e4), (2e4, 4e4), (4e4, 8e4), (8e4, 1e12)]:
    t = [m / p for _, q, m, p in fr if lo <= q < hi]
    curve.append({'lo': lo, 'hi': hi, 'n': len(t), 'ratio': S.median(t)})
out['flow_fit'] = {'alpha': al, 'beta': be, 'n_train': len(train), 'n_test': len(test),
                   'all': {k: err(test, f) for k, f in rules.items()}, 'bands': bands, 'curve': curve}
json.dump(out, open(HERE / 'out' / 'fares.json', 'w'), ensure_ascii=False, indent=1, default=float)
print('ok', {k: (round(v['mae'], 3)) for k, v in out['flow_fit']['all'].items()})
