"""Independent check: direct maintenance per block hour, fleet age, 2025-PPI deflation."""
import json, sys
import pandas as pd

BASE = 'toir/'
RAW = BASE + 'raw20/'
CASES = [('19805', '694', 2010, 'A320', 'AA'), ('19805', '694', 2019, 'A320', 'AA'),
         ('19393', '612', 2008, 'B737', 'WN'), ('19393', '612', 2022, 'B737', 'WN'),
         ('19790', '622', 2009, 'B752', 'DL')]
# B-43 before 2010 has no AIRCRAFT_TYPE -> map by MODEL text (checked by hand)
MODEL_MAP = {('19393', '612'): {'B737-7/L'}, ('19790', '622'): {'B-757-2'},
             ('19805', '694'): set()}

p = pd.read_csv(RAW + 'p52.csv', dtype={'AIRLINE_ID': str, 'AIRCRAFT_TYPE': str, 'AIRCRAFT_CONFIG': str})
t = pd.read_csv(RAW + 't2.csv', dtype={'AIRLINE_ID': str, 'AIRCRAFT_TYPE': str, 'AIRCRAFT_CONFIG': str,
                                      'UNIQUE_CARRIER_ENTITY': str})
b = pd.read_csv(RAW + 'b43.csv', dtype=str)
idx = json.load(open(BASE + 'index.json'))


def t2_hours(sub):
    """Per (quarter, entity, region): Z if present, else K+V, else F+G+L+P."""
    out = {}
    for (q, ent, reg), g in sub.groupby(['QUARTER', 'UNIQUE_CARRIER_ENTITY', 'CARRIER_REGION']):
        cls = dict(zip(g.SERVICE_CLASS, zip(g.ACRFT_HRS_RAMPTORAMP_630.fillna(0),
                                            g.REV_ACRFT_DEP_PERF_510.fillna(0),
                                            g.REV_ACRFT_MILES_FLOWN_410.fillna(0))))
        if 'Z' in cls:
            v = cls['Z']
        elif 'K' in cls or 'V' in cls:
            v = tuple(sum(cls.get(c, (0, 0, 0))[i] for c in 'KV') for i in range(3))
        else:
            v = tuple(sum(cls.get(c, (0, 0, 0))[i] for c in 'FGLP') for i in range(3))
        h, d, m = out.get(q, (0, 0, 0))
        out[q] = (h + v[0], d + v[1], m + v[2])
    return out


def ppi(y):
    w, pc = idx['wps5541_jun'], idx['pcu488190_jun']
    if str(y) in w:
        return w[str(y)]
    return pc[str(y)] * w['2009'] / pc['2009']


res = []
for aid, code, yr, icao, cr in CASES:
    ps = p[(p.AIRLINE_ID == aid) & (p.AIRCRAFT_TYPE == code) & (p.YEAR == yr) & (p.AIRCRAFT_CONFIG == '1')]
    cost_q = ps.groupby('QUARTER').TOT_DIR_MAINT.sum() * 1000
    ts = t[(t.AIRLINE_ID == aid) & (t.AIRCRAFT_TYPE == code) & (t.YEAR == yr) & (t.AIRCRAFT_CONFIG == '1')]
    hq = t2_hours(ts)
    qs = sorted(q for q in cost_q.index if q in hq and hq[q][0] > 0)
    cost = sum(cost_q[q] for q in qs)
    hrs = sum(hq[q][0] for q in qs)
    deps = sum(hq[q][1] for q in qs)
    miles = sum(hq[q][2] for q in qs)
    nom = cost / hrs if hrs else None
    f = idx['wps5541_jun']['2025'] / ppi(yr)
    # ages
    bs = b[(b.AIRLINE_ID == aid) & (b.YEAR == str(yr)) & (b.OPERATING_STATUS.str.upper() == 'Y')]
    bs = bs[(bs.AIRCRAFT_TYPE.str[:3] == code) | (bs.AIRCRAFT_TYPE.isna() & bs.MODEL.str.strip().isin(MODEL_MAP[(aid, code)]))]
    my = pd.to_numeric(bs.MANUFACTURE_YEAR, errors='coerce')
    ages = (yr - my).dropna()
    res.append(dict(carrier=cr, icao=icao, year=yr, quarters=qs, cost=cost, hours=hrs,
                    sector_h=hrs / deps if deps else None, stage_mi=miles / deps if deps else None,
                    nominal=nom, factor=f, direct2025=nom * f if nom else None,
                    n_ac=len(bs), age_mean=ages.mean() if len(ages) else None,
                    age_mean_plus05=ages.mean() + 0.5 if len(ages) else None))
for r in res:
    print(r)
json.dump(res, open(BASE + 'check/mycalc.json', 'w'), indent=1, default=float)
