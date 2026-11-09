exec(open('charts1.py').read().split('# 1 trend')[0])
import numpy as np
for r in R: r['real']=(r['all_pax'] or r['pax'])/0.4
bk=[0,5e3,10e3,20e3,40e3,80e3,1e9]; lab=['<5','5–10','10–20','20–40','40–80','80+']
m10=[];m25=[]
for lo,hi in zip(bk,bk[1:]):
    rs=[r for r in R if lo<=r['real']<hi]; m10.append(S.median(r['mean']/r['p10'] for r in rs)); m25.append(S.median(r['mean']/r['p25'] for r in rs))
fig,ax=plt.subplots(figsize=(8,4.2)); x=np.arange(len(lab))
ax.plot(x,m10,color=O,lw=2,marker='o',ms=6,label='средний ÷ 10-й перцентиль'); ax.plot(x,m25,color=B,lw=2,marker='o',ms=6,label='средний ÷ 25-й перцентиль')
for i,v in enumerate(m10): ax.text(i,v+0.06,f"{v:.2f}".replace('.',','),ha='center',fontsize=9,color=INK)
ax.set_xticks(x); ax.set_xticklabels(lab); ax.set_xlabel('поток пары, тыс. пассажиров в месяц (обе стороны)'); ax.set_ylim(1,3)
ax.legend(frameon=False,loc='upper left',fontsize=9.5); ax.set_title('Чем толще пара, тем дальше средний чек от дешёвых билетов',loc='left',color=INK,fontsize=12)
fig.text(0.01,0.01,'BTS DB1C, прямые, 39 тыс. пар-месяцев, медиана; поток — выборка ÷ 0,4',color=INK2,fontsize=8.5)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig('fig/5-thickness.png'); plt.close()
