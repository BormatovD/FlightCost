import sys; sys.path.insert(0,'.')
from load import load, gc
import statistics as S, collections
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
B,O,A,INK,INK2,GRID,BG='#2a78d6','#eb6834','#1baf7a','#0b0b0b','#52514e','#e6e5e0','#fcfcfb'
plt.rcParams.update({'font.size':11,'axes.edgecolor':GRID,'axes.labelcolor':INK2,'xtick.color':INK2,'ytick.color':INK2,
 'axes.grid':True,'grid.color':GRID,'grid.linewidth':0.8,'axes.spines.top':False,'axes.spines.right':False,
 'figure.facecolor':BG,'axes.facecolor':BG,'savefig.dpi':200})
R=[r for r in load('../db1c2') if (r.update(km=gc(*r['pair'].split('-'))) or True) and r['km']]
MON='июл авг сен окт ноя дек янв фев мар апр май июн июл'.split()
# 1 trend
cnt=collections.Counter(r['pair'] for r in R); panel={p for p,c in cnt.items() if c==13}
months=sorted({r['month'] for r in R}); w=[]
for m in months:
    rs=[r for r in R if r['month']==m and r['pair'] in panel]; w.append(sum(r['mean']*r['pax'] for r in rs)/sum(r['pax'] for r in rs))
fig,ax=plt.subplots(figsize=(8,4.2)); x=range(len(months))
ax.plot(x,w,color=B,lw=2,marker='o',ms=5); ax.set_xticks(list(x)); ax.set_xticklabels([f"{MON[i]}\n{m[2:4]}" if i in(0,6,12) else MON[i] for i,m in enumerate(months)])
for i in (0,12): ax.annotate(f"${w[i]:.0f}",(i,w[i]),textcoords='offset points',xytext=(0,9),ha='center',color=INK)
ax.set_ylabel('USD за рынок в одну сторону'); ax.set_ylim(180,290)
ax.set_title('Средний оплаченный тариф, прямые рейсы, 2 391 пара США',loc='left',color=INK,fontsize=12)
fig.text(0.01,0.01,'BTS DB1C, выборка 40 % билетов; без бонусных; взвешено по пассажирам',color=INK2,fontsize=8.5)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig('fig/1-trend.png'); plt.close()
# 2 booking window by distance
bins=[0,500,1000,1500,2000,3000,4000,6000]; lab=[];a21=[];a22=[];s21=[]
for lo,hi in zip(bins,bins[1:]):
    rs=[r for r in R if lo<=r['km']<hi]
    lab.append(f"{lo}–{hi}")
    a21.append(S.median(r['mean_21AP']/r['mean_91UP'] for r in rs if r.get('mean_21AP') and r.get('mean_91UP')))
    a22.append(S.median(r['mean_2290']/r['mean_91UP'] for r in rs if r.get('mean_2290') and r.get('mean_91UP')))
    s21.append(S.median(r['share_21AP'] for r in rs))
fig,ax=plt.subplots(figsize=(8,4.2)); import numpy as np; xi=np.arange(len(lab)); wd=0.38
ax.bar(xi-wd/2-0.01,a21,wd,color=O,label='куплен за 0–21 день'); ax.bar(xi+wd/2+0.01,a22,wd,color=B,label='за 22–90 дней')
ax.axhline(1,color=INK2,lw=1); ax.set_xticks(xi); ax.set_xticklabels(lab); ax.set_xlabel('дальность пары, км')
ax.set_ylabel('средний тариф ÷ тариф за 91+ день'); ax.set_ylim(0.8,1.7)
for i,v in enumerate(a21): ax.text(i-wd/2,v+0.015,f"{v:.2f}".replace('.',','),ha='center',fontsize=9,color=INK)
ax.legend(frameon=False,loc='upper right'); ax.set_title('Надбавка за позднюю покупку',loc='left',color=INK,fontsize=12)
fig.text(0.01,0.01,'BTS DB1C, июль 2025 — июль 2026; медиана по пар-месяцам',color=INK2,fontsize=8.5)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig('fig/2-booking.png'); plt.close()
# 3 share of late purchases
fig,ax=plt.subplots(figsize=(8,3.6)); ax.bar(xi,[v*100 for v in s21],0.6,color=O)
for i,v in enumerate(s21): ax.text(i,v*100+1,f"{v*100:.0f}%",ha='center',fontsize=9,color=INK)
ax.set_xticks(xi); ax.set_xticklabels(lab); ax.set_xlabel('дальность пары, км'); ax.set_ylabel('% пассажиров'); ax.set_ylim(0,75)
ax.set_title('Доля билетов, купленных за 21 день и ближе',loc='left',color=INK,fontsize=12)
fig.tight_layout(); fig.savefig('fig/3-late-share.png'); plt.close()
# 4 fare vs distance
J=[r for r in R if r['month']=='2025-10']
fig,ax=plt.subplots(figsize=(8,4.6))
ax.scatter([r['km'] for r in J],[r['mean'] for r in J],s=[max(4,r['pax']/400) for r in J],color=B,alpha=0.35,lw=0)
ax.set_xlabel('расстояние по ортодромии, км'); ax.set_ylabel('средний тариф, USD'); ax.set_ylim(0,800); ax.set_xlim(0,5500)
ax.plot([0,5500],[141.2,141.2+56.8*5.5],color=O,lw=2); ax.text(3000,560,'141 + 57 $ на 1000 км\nR² = 0,41',color=INK,fontsize=9.5)
ax.set_title('Тариф и дальность: постоянная часть больше переменной',loc='left',color=INK,fontsize=12)
fig.text(0.01,0.01,f'BTS DB1C; точки — октябрь 2025, {len(J)} пар, размер — пассажиры; линия — все 13 месяцев, взвешено по пассажирам',color=INK2,fontsize=8.5)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig('fig/4-distance.png'); plt.close()
print(w[0],w[-1])
