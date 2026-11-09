import json, glob, math, statistics as S
import airportsdata
AP = airportsdata.load('IATA')
def gc(a,b):
    A,B=AP.get(a),AP.get(b)
    if not A or not B: return None
    p1,p2=math.radians(A['lat']),math.radians(B['lat']); dl=math.radians(B['lon']-A['lon'])
    return 2*6371*math.asin(math.sqrt(math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))
def load(d):
    rows=[]
    for f in sorted(glob.glob(d+'/DB1C-*.json')):
        doc=json.load(open(f))
        for pair,segs in doc['pairs'].items():
            dr=segs['direct']; al=segs.get('all',{})
            rows.append(dict(month=doc['month'],pair=pair,**{k:dr.get(k) for k in dr},all_mean=al.get('mean'),all_pax=al.get('pax')))
    return rows
