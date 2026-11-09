exec(open('charts1.py').read().split('R=[r for r')[0])
import json,glob,statistics as S,collections,numpy as np
ULCC={'F9','NK','G4','SY','MX'}
rel=collections.defaultdict(list)
for f in sorted(glob.glob('../in/agg3/DB1C-*.json')):
    for pair,v in json.load(open(f))['pairs'].items():
        cs=v.get('carriers') or {}
        if not(any(c in ULCC for c in cs) and any(c not in ULCC for c in cs)): continue
        for c,x in cs.items():
            if x['pax']>=100: rel[c].append(x['mean']/v['direct']['p10'])
order=[('SY','Sun Country'),('F9','Frontier'),('NK','Spirit'),('G4','Allegiant'),('AS','Alaska'),('B6','JetBlue'),('WN','Southwest'),('AA','American'),('UA','United'),('DL','Delta')]
vals=[S.median(rel[c]) for c,_ in order]; col=[O if c in ULCC else B for c,_ in order]
fig,ax=plt.subplots(figsize=(8,4.4)); y=np.arange(len(order))[::-1]
ax.barh(y,vals,0.62,color=col)
for yi,v in zip(y,vals): ax.text(v+0.04,yi,f"{v:.2f}".replace('.',','),va='center',fontsize=9.5,color=INK)
ax.set_yticks(y); ax.set_yticklabels([n for _,n in order]); ax.set_xlim(0,3.8); ax.grid(axis='y',visible=False)
ax.set_xlabel('средний тариф перевозчика ÷ 10-й перцентиль тарифов пары')
ax.set_title('На одной паре: «минимум рынка» ставит лоукостер,\nа средний чек сетевого — втрое выше',loc='left',color=INK,fontsize=12)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=O,label='ультралоукостеры'),Patch(color=B,label='остальные')],frameon=False,loc='upper right')
fig.text(0.01,0.01,'BTS DB1C, прямые, пары, где летают и ультралоукостер, и другой перевозчик; июль 2025 — июль 2026, медиана',color=INK2,fontsize=8.5)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig('fig/6-carriers.png'); plt.close()
R=json.load(open('lcc_rows.json'))
bins=[(0,0.001,'0'),(0.001,0.2,'до 20'),(0.2,0.4,'20–40'),(0.4,0.6,'40–60'),(0.6,0.8,'60–80'),(0.8,1.01,'80–100')]
mean=[S.median(r['mean'] for r in R if lo<=r['u']<hi) for lo,hi,_ in bins]
p10=[S.median(r['p10'] for r in R if lo<=r['u']<hi) for lo,hi,_ in bins]
fig,ax=plt.subplots(figsize=(8,4.2)); x=np.arange(len(bins))
ax.plot(x,mean,color=B,lw=2,marker='o',ms=6,label='средний тариф'); ax.plot(x,p10,color=O,lw=2,marker='o',ms=6,label='10-й перцентиль')
for i,(a,b) in enumerate(zip(mean,p10)): ax.text(i,a+9,f"${a:.0f}",ha='center',fontsize=9,color=INK); ax.text(i,b-22,f"${b:.0f}",ha='center',fontsize=9,color=INK)
ax.set_xticks(x); ax.set_xticklabels([b[2] for b in bins]); ax.set_xlabel('доля ультралоукостеров на паре, % пассажиров'); ax.set_ylim(0,310); ax.set_ylabel('USD')
ax.legend(frameon=False); ax.set_title('Приход лоукостера опускает дешёвый край сильнее среднего',loc='left',color=INK,fontsize=12)
fig.text(0.01,0.01,'BTS DB1C, прямые, 39 тыс. пар-месяцев, медиана; ультралоукостеры — Frontier, Spirit, Allegiant, Sun Country, Breeze',color=INK2,fontsize=8.5)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig('fig/7-ulcc-share.png'); plt.close()
