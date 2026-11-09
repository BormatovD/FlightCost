exec(open('charts1.py').read().split('R=[r for r')[0])
import json, numpy as np
res=json.load(open('../verify/items.json'))
keys=['Топливо, тыс. т','Блок-часы, тыс.','ТОиР','Экипаж',None]
fig,axes=plt.subplots(1,2,figsize=(10,4.6),sharey=True)
for ax,(c,name) in zip(axes,(('F9','Frontier'),('WN','Southwest'))):
    r=res[c]; ks=[k for k in ['Топливо, тыс. т','Блок-часы, тыс.','ТОиР','Экипаж','Аэропорт + наземка','Аэропортовые сборы'] if k in r]
    y=np.arange(len(ks))[::-1]; h=0.36
    b=[(r[k]['before']/r[k]['fact']-1)*100 for k in ks]; a=[(r[k]['after']/r[k]['fact']-1)*100 for k in ks]
    ax.barh(y+h/2+0.01,b,h,color=GRID if False else '#b9b8b2',label='до')
    ax.barh(y-h/2-0.01,a,h,color=B,label='после')
    for yi,v in zip(y,a): ax.text(v+(3 if v>=0 else -3),yi-h/2,f"{v:+.0f}%",va='center',ha='left' if v>=0 else 'right',fontsize=9,color=INK)
    for yi,v in zip(y,b): ax.text(v+(3 if v>=0 else -3),yi+h/2,f"{v:+.0f}%",va='center',ha='left' if v>=0 else 'right',fontsize=8.5,color=INK2)
    ax.axvline(0,color=INK2,lw=1); ax.set_yticks(y); ax.set_yticklabels([k.replace(', тыс. т','').replace(', тыс.','').replace('Аэропортовые сборы','Сборы аэропортов') for k in ks])
    ax.set_xlim(-95,95); ax.set_title(name,loc='left',color=INK,fontsize=12); ax.grid(axis='y',visible=False)
    ax.set_xlabel('ошибка модели к отчётности, %')
axes[0].legend(frameon=False,loc='lower left')
fig.suptitle('Модель против отчётности 2025 года: до и после правок',x=0.01,ha='left',color=INK,fontsize=13)
fig.text(0.01,0.01,'Сети — BTS T-100 2025; факт — 10-K (топливо, аэропорты), Form 41 P-5.2 (ТОиР; экипаж = пилоты × 1,56, бортпроводники оценкой ACMG)',color=INK2,fontsize=8.3)
fig.tight_layout(rect=(0,0.04,1,0.95)); fig.savefig('fig/8-before-after.png'); plt.close()
