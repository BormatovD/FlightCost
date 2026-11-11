"""Readable cash-flow diagrams, using the independently checked lease example."""
from __future__ import annotations

import textwrap

from _report import T, e, money, n


CSS = """<style>
.deal-stage{margin:24px 0 30px;padding:18px 16px;background:var(--panel);border:1px solid var(--line);border-radius:14px}
.deal-stage h3{margin:0 0 7px;font-size:18px}.deal-stage .small{margin:6px 0}
.deal-map{overflow-x:auto;max-width:100%;margin:14px 0}.deal-map svg{display:block;width:100%;min-width:720px;height:auto}
.deal-map .actor-title{font:600 16px var(--sans);fill:var(--ink2)}
.deal-map .actor-note{font:13px var(--sans);fill:var(--dim)}
.deal-map .flow-value{font:600 17px var(--sans);fill:var(--ink2)}
.deal-map .flow-note{font:12.5px var(--sans);fill:var(--dim)}
.deal-map .flow-value .mny{font:inherit;fill:inherit}
.deal-balance{font-size:13px;color:var(--dim);border-top:1px solid var(--line);padding-top:11px;margin-top:4px}
.deal-key{display:flex;flex-wrap:wrap;gap:7px 18px;font-size:12.5px;color:var(--dim)}
.deal-key span:before{content:"";display:inline-block;width:7px;height:7px;background:var(--sky-t);border-radius:50%;margin-right:6px}
.deal-key span:last-child:before{background:var(--aqua-t)}
.deal-reading{border-left:3px solid var(--guess);padding:4px 13px;margin:18px 0}
.deal-terms{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:12px 0}
.deal-terms div{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--bg)}
.deal-terms b{display:block;font-weight:500;color:var(--ink2)}.deal-terms span{font-size:12.5px;color:var(--dim)}
</style>"""


def actor(ident, x, y, title, note, color='var(--aqua-t)', width=250):
    notes = textwrap.wrap(note, width=31, break_long_words=False, break_on_hyphens=False)
    return (f'<g data-actor="{ident}"><rect x="{x}" y="{y}" width="{width}" height="80" rx="12" '
            f'fill="var(--bg)" stroke="var(--line)"/><rect x="{x+1}" y="{y+1}" width="4" height="78" rx="2" fill="{color}"/>'
            f'<text class="actor-title" x="{x+18}" y="{y+32}">{e(title)}</text>'
            + ''.join(f'<text class="actor-note" x="{x+18}" y="{y+53+14*i}">{e(line)}</text>' for i,line in enumerate(notes)) + '</g>')


def flow(stage, ident, source, target, path, label_x, label_y, amount, notes, *, color='var(--sky-t)', width=286):
    """Labels cover only the middle of a visible directional connector."""
    label_height = 37 + 17 * len(notes)
    return (f'<g data-flow="{ident}" data-from="{source}" data-to="{target}" data-amount-usd="{amount:.12g}" '
            f'data-period="{stage}"><path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
            f'marker-end="url(#arrow-{stage})"/>'
            f'<rect x="{label_x}" y="{label_y}" width="{width}" height="{label_height}" rx="7" fill="var(--panel)"/>'
            f'<text class="flow-value" x="{label_x+width/2}" y="{label_y+23}" text-anchor="middle">'
            + money(amount, 'USD', tag='tspan') + '</text>'
            + ''.join(f'<text class="flow-note" x="{label_x+width/2}" y="{label_y+44+17*i}" text-anchor="middle">{e(t)}</text>' for i,t in enumerate(notes))
            + '</g>')


def map_open(stage, title, height):
    return (f'<div class="deal-map"><svg class="deal-cashflow" data-stage="{stage}" viewBox="0 0 900 {height}" '
            f'role="img" aria-labelledby="deal-{stage}"><title id="deal-{stage}">{e(title)}</title>'
            f'<defs><marker id="arrow-{stage}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="var(--sky-t)"/></marker></defs>')


def purchase_map(data):
    p, f = data['inputs'], data['financing']
    stage = 'purchase'
    title=T('Покупка: банк и инвестор финансируют лизингодателя', 'Purchase: lender and investor fund the lessor', 'Kauf: Bank und Investor finanzieren den Leasinggeber')
    svg=[map_open(stage,title,500)]
    svg.extend([
        flow(stage,'debt-advance','bank','lessor','M175 100 V122 Q175 190 382 215',35,120,f['opening_debt_usd'],
             [T(f'кредит на {n(p["debt_maturity_months"]/12)} лет под {n(p["debt_interest_annual_effective"]*100)} % годовых',f'{n(p["debt_maturity_months"]/12)}-year loan at {n(p["debt_interest_annual_effective"]*100)}% annually',f'{n(p["debt_maturity_months"]/12)} Jahre Kredit, {n(p["debt_interest_annual_effective"]*100)} % jährlich'),
              T('эффективная ставка; возврат остатка в конце', 'effective rate; balance repaid at maturity', 'Effektivzins; Restschuld am Laufzeitende')]),
        flow(stage,'equity-injection','investor','lessor','M725 100 V122 Q725 190 518 215',579,120,f['initial_equity_usd'],
             [T('собственный капитал в начале сделки', 'equity invested at transaction start', 'Eigenkapital zum Transaktionsbeginn'),
              T('включает финансирование начальных затрат', 'includes funding of initial costs', 'einschließlich Finanzierung der Anfangskosten')],color='var(--aqua-t)'),
        flow(stage,'aircraft-purchase','lessor','seller','M382 295 Q175 335 175 405',35,310,p['purchase_usd'],
             [T('цена самолёта', 'aircraft purchase price', 'Kaufpreis des Flugzeugs')]),
        flow(stage,'purchase-cost','lessor','services','M518 295 Q725 335 725 405',579,310,p['upfront_cost_usd'],
             [T('оформление и прочие затраты приобретения', 'closing and other acquisition costs', 'Abschluss- und sonstige Anschaffungskosten')]),
    ])
    svg.extend([
        actor('bank',50,20,T('Банк', 'Bank', 'Bank'),T('заёмный капитал', 'debt capital', 'Fremdkapital'),'var(--sky-t)'),
        actor('investor',600,20,T('Инвестор / акционеры', 'Investor / shareholders', 'Investor / Anteilseigner'),T('собственный капитал', 'equity capital', 'Eigenkapital'),'var(--blue-t)'),
        actor('lessor',325,215,T('Лизинговая компания', 'Leasing company', 'Leasinggesellschaft'),T('покупает и владеет самолётом', 'buys and owns the aircraft', 'kauft und besitzt das Flugzeug')),
        actor('seller',50,405,T('Продавец самолёта', 'Aircraft seller', 'Flugzeugverkäufer'),T('производитель или прежний владелец', 'manufacturer or previous owner', 'Hersteller oder bisheriger Eigentümer'),'var(--green-t)'),
        actor('services',600,405,T('Участники оформления', 'Transaction services', 'Transaktionsdienstleister'),T('услуги по приобретению', 'acquisition services', 'Dienstleistungen beim Kauf'),'var(--blue-t)'),
        '</svg></div>'])
    return ''.join(svg)


def operating_map(data):
    p,b,f=data['inputs'],data['base'],data['financing'];stage='monthly'
    title=T('Каждый месяц: аренда распределяется между кредитом, расходами и собственником', 'Each month: rent funds debt service, costs and equity cash', 'Monatlich: Miete finanziert Kreditdienst, Kosten und Eigenkapitalzufluss')
    svg=[map_open(stage,title,570)]
    svg.extend([
        flow(stage,'monthly-rent','airline','lessor','M450 100 V245',307,126,b['rent_usd_month_end'],
             [T('базовая аренда в месяц', 'basic rent per month', 'monatliche Grundmiete'), T('в примере — в конце месяца', 'month-end in this example', 'im Beispiel am Monatsende')]),
        flow(stage,'monthly-debt','lessor','bank','M450 325 V350 H155 V465',12,368,f['scheduled_debt_payment_usd_month'],
             [T('платёж по кредиту в месяц', 'monthly debt service', 'monatlicher Kreditdienst'), T('проценты + основной долг', 'interest + principal', 'Zinsen + Tilgung')]),
        flow(stage,'monthly-cost','lessor','services','M450 325 V465',307,368,p['owner_cost_usd_month'],
             [T('расходы владельца в месяц', 'monthly owner costs', 'monatliche Eigentümerkosten'), T('без обычного ТОиР авиакомпании', 'excludes ordinary airline maintenance', 'ohne normale Wartung der Airline')]),
        flow(stage,'monthly-equity','lessor','investor','M450 325 V350 H745 V465',602,368,f['regular_equity_cash_usd_month'],
             [T('денежный остаток для собственника', 'cash available to equity', 'für Eigenkapital verfügbarer Zufluss'), T('до налогов; при выполнении допущений', 'pre-tax; if assumptions hold', 'vor Steuern; unter den Annahmen')],color='var(--aqua-t)'),
    ])
    svg.extend([
        actor('airline',325,20,T('Авиакомпания', 'Airline', 'Fluggesellschaft'),T('эксплуатирует самолёт', 'operates the aircraft', 'betreibt das Flugzeug'),'var(--green-t)'),
        actor('lessor',325,245,T('Лизинговая компания', 'Leasing company', 'Leasinggesellschaft'),T('получает аренду и несёт обязательства', 'receives rent and meets obligations', 'erhält Miete und erfüllt Verpflichtungen')),
        actor('bank',30,465,T('Банк', 'Bank', 'Bank'),T('заработок — проценты и комиссии', 'earnings: interest and fees', 'Ertrag: Zinsen und Gebühren'),'var(--sky-t)'),
        actor('services',325,465,T('Сервисы владельца', 'Owner services', 'Eigentümerdienstleister'),T('получают оплату своих услуг', 'receive service payments', 'erhalten Leistungsentgelte'),'var(--blue-t)'),
        actor('investor',620,465,T('Инвестор / акционеры', 'Investor / shareholders', 'Investor / Anteilseigner'),T('поток ещё включает возврат капитала', 'cash also recovers invested capital', 'Zufluss enthält auch Kapitalrückfluss'),'var(--blue-t)'),
        '</svg></div>'])
    return ''.join(svg)


def terminal_map(data):
    p,f=data['inputs'],data['financing'];stage='sale'
    title=T('Продажа через десять лет: расходы, остаток долга и капитал собственника', 'Resale after ten years: costs, remaining debt and equity proceeds', 'Verkauf nach zehn Jahren: Kosten, Restschuld und Eigenkapitalerlös')
    svg=[map_open(stage,title,570)]
    svg.extend([
        flow(stage,'resale-proceeds','buyer','lessor','M450 100 V245',307,126,p['resale_usd'],
             [T('предполагаемая цена продажи', 'assumed resale price', 'angenommener Verkaufspreis'),T('будущий результат может отличаться', 'the eventual outcome may differ', 'das spätere Ergebnis kann abweichen')]),
        flow(stage,'balloon','lessor','bank','M450 325 V350 H155 V465',12,368,f['remaining_debt_at_sale_usd'],
             [T('погашение остатка долга', 'repayment of remaining debt', 'Rückzahlung der Restschuld'),T('после 120-го обычного платежа', 'after the 120th regular payment', 'nach der 120. regulären Zahlung')]),
        flow(stage,'sale-cost','lessor','services','M450 325 V465',307,368,p['sale_cost_usd'],
             [T('затраты продажи', 'selling costs', 'Verkaufskosten')]),
        flow(stage,'sale-equity','lessor','investor','M450 325 V350 H745 V465',602,368,f['net_sale_cash_to_equity_usd'],
             [T('остаток собственнику', 'remaining proceeds to equity', 'verbleibender Eigenkapitalerlös'),T('дополнительно к месячным потокам', 'in addition to monthly cash flows', 'zusätzlich zu den Monatszuflüssen')],color='var(--aqua-t)'),
    ])
    svg.extend([
        actor('buyer',325,20,T('Следующий покупатель', 'Next buyer', 'Nächster Käufer'),T('платит за самолёт', 'pays for the aircraft', 'bezahlt das Flugzeug'),'var(--green-t)'),
        actor('lessor',325,245,T('Лизинговая компания', 'Leasing company', 'Leasinggesellschaft'),T('продаёт самолёт и закрывает долг', 'sells the aircraft and settles debt', 'verkauft das Flugzeug und tilgt Schulden')),
        actor('bank',30,465,T('Банк', 'Bank', 'Bank'),T('получает оставшийся основной долг', 'receives remaining principal', 'erhält restlichen Kreditbetrag'),'var(--sky-t)'),
        actor('services',325,465,T('Участники продажи', 'Sale services', 'Verkaufsdienstleister'),T('получают оплату сделки', 'receive transaction fees', 'erhalten Transaktionsentgelte'),'var(--blue-t)'),
        actor('investor',620,465,T('Инвестор / акционеры', 'Investor / shareholders', 'Investor / Anteilseigner'),T('принимает риск будущей цены', 'bears future-value risk', 'trägt das künftige Preisrisiko'),'var(--blue-t)'),
        '</svg></div>'])
    return ''.join(svg)


def contract_flows(s):
    """Qualitative contractual flows; never assign fabricated amounts."""
    rows=[
        (T('Авиакомпания','Airline','Fluggesellschaft'),T('Лизингодатель','Lessor','Leasinggeber'),T('Обеспечительный депозит','Security deposit','Kaution'),T('Размер и условия возврата задаёт договор.','Amount and repayment conditions are contractual.','Betrag und Rückzahlung folgen dem Vertrag.')),
        (T('Авиакомпания','Airline','Fluggesellschaft'),T('Лизингодатель','Lessor','Leasinggeber'),T('Технические резервы','Maintenance reserves','Wartungsrücklagen'),T('Если предусмотрены: начисление по времени, часам или циклам.','If agreed: based on time, hours or cycles.','Falls vereinbart: nach Zeit, Stunden oder Zyklen.')),
        (T('Авиакомпания','Airline','Fluggesellschaft'),T('Ремонтная организация','Maintenance provider','Wartungsbetrieb'),T('Оплата выполненного ТОиР','Payment for completed maintenance','Zahlung für ausgeführte Wartung'),T('Обычное обслуживание оператора учитывается отдельно от базовой аренды.','Ordinary operator maintenance is separate from basic rent.','Normale Betreiberwartung wird getrennt von der Grundmiete erfasst.')),
        (T('Лизингодатель','Lessor','Leasinggeber'),T('Авиакомпания','Airline','Fluggesellschaft'),T('Возмещение из резервов','Reimbursement from reserves','Erstattung aus Rücklagen'),T('По допустимым событиям и документам согласно условиям договора.','For eligible events and records under the lease.','Für zulässige Ereignisse und Nachweise laut Vertrag.')),
        (T('Лизингодатель','Lessor','Leasinggeber'),T('Авиакомпания','Airline','Fluggesellschaft'),T('Возврат депозита','Deposit repayment','Kautionsrückzahlung'),T('При выполнении условий; возможны договорные удержания.','Subject to compliance and contractual deductions.','Bei erfüllten Bedingungen; vertragliche Abzüge sind möglich.')),
        (T('Авиакомпания','Airline','Fluggesellschaft'),T('Лизингодатель','Lessor','Leasinggeber'),T('Компенсация при возврате','Return-condition compensation','Rückgabeausgleich'),T('Если фактическое состояние требует согласованной компенсации.','Where return condition triggers agreed compensation.','Wenn der Rückgabezustand vereinbarten Ausgleich auslöst.')),
    ]
    html=['<style>.contract-flow{display:grid;grid-template-columns:minmax(130px,1fr) 2fr minmax(130px,1fr);gap:12px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line)}.contract-actor{padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:var(--bg);font-size:13px}.contract-transfer{position:relative;padding:0 8px 12px;border-bottom:1px solid var(--sky-t);font-size:13px;text-align:center}.contract-transfer:after{content:"";position:absolute;right:-1px;bottom:-5px;border-left:8px solid var(--sky-t);border-top:4px solid transparent;border-bottom:4px solid transparent}.contract-transfer small{display:block;color:var(--dim);font-size:12px;margin-top:4px}@media(max-width:600px){.contract-flow{grid-template-columns:1fr;gap:9px}.contract-transfer{padding:5px 12px 20px;text-align:center;border-bottom:0}.contract-transfer:after{right:calc(50% - 4px);bottom:0;border-left:4px solid transparent;border-right:4px solid transparent;border-top:8px solid var(--sky-t);border-bottom:0}}</style>',
          f'<h3>{T("Дополнительные платежи договора", "Additional contractual payments", "Weitere vertragliche Zahlungen")}</h3>',
          f'<p class="small">{T("Для этих потоков суммы в примере не заданы. Они возникают по условиям конкретного договора и показаны отдельно от базовой аренды.", "These flows have no assigned amount in this example. They depend on the contract and are shown separately from basic rent.", "Diesen Strömen sind im Beispiel keine Beträge zugewiesen. Sie folgen dem konkreten Vertrag und stehen getrennt von der Grundmiete.")}{s.cite("lease-001","lease-002")}</p>']
    for source,target,name,note in rows:
        html.append(f'<div class="contract-flow"><div class="contract-actor">{e(source)}</div><div class="contract-transfer">{e(name)}<small>{e(note)}</small></div><div class="contract-actor">{e(target)}</div></div>')
    return ''.join(html)


def deal_flow_section(data,s):
    p,b,f=data['inputs'],data['base'],data['financing']
    first=f['monthly_schedule'][0]
    body=[CSS,f'<h3>{T("Кто кому платит: одна сделка от покупки до продажи", "Who pays whom: one transaction from purchase to resale", "Wer zahlt wem: eine Transaktion vom Kauf bis zum Verkauf")}</h3>',
          f'<div class="deal-reading"><p>{T("Все суммы — тот же условный пример. Стрелка направлена к получателю денег. Покупка происходит один раз, арендные потоки повторяются ежемесячно, продажа закрывает сделку в конце десятого года. Налоги, дефолт и простой в примере не заданы.", "All amounts use the same illustrative example. Arrows point to the cash recipient. Purchase occurs once, rent cash flows recur monthly, and resale closes the transaction at year ten. Taxes, default and downtime are not modelled.", "Alle Beträge gehören zum selben Rechenbeispiel. Pfeile zeigen zum Geldempfänger. Der Kauf erfolgt einmal, Mietströme wiederholen sich monatlich, und der Verkauf schließt die Transaktion im zehnten Jahr. Steuern, Ausfall und Stillstand sind nicht modelliert.")}</p></div>',
          f'<p class="small">{T("На узком экране схемы можно прокручивать по горизонтали.", "On a narrow screen, diagrams can be scrolled horizontally.", "Auf schmalen Bildschirmen lassen sich die Schemata horizontal verschieben.")}</p>']
    body.append(f'<section class="deal-stage"><h3>{T("1. В день покупки", "1. At purchase", "1. Am Kauftag")}</h3>' + purchase_map(data))
    body.append('<div class="deal-balance">' + T('Входящие деньги = цена самолёта + затраты сделки: ', 'Cash in = aircraft price + transaction costs: ', 'Geldeingang = Flugzeugpreis + Transaktionskosten: ') + money(f['opening_debt_usd'],'USD') + ' + ' + money(f['initial_equity_usd'],'USD') + ' = ' + money(p['purchase_usd'],'USD') + ' + ' + money(p['upfront_cost_usd'],'USD') + '</div>')
    body.append(f'<p class="small">{T("Кредит возвращается через десять лет, но обычный платёж рассчитан по пятнадцатилетнему графику. Поэтому в конце десятого года остаётся крупная сумма долга, показанная на третьей схеме. Собственный капитал не обещает фиксированной выплаты: его результат зависит от аренды, затрат и будущей продажи.", "The loan matures in ten years, but regular payments follow a fifteen-year amortisation schedule. A substantial balance therefore remains at year ten, shown in the third diagram. Equity has no promised fixed return: its outcome depends on rent, costs and resale.", "Der Kredit endet nach zehn Jahren, die regelmäßige Rate folgt jedoch einem fünfzehnjährigen Tilgungsplan. Daher bleibt am Ende des zehnten Jahres die im dritten Schema gezeigte Restschuld. Eigenkapital hat keine zugesagte feste Rendite; das Ergebnis hängt von Miete, Kosten und Verkauf ab.")}</p></section>')
    body.append(f'<section class="deal-stage"><h3>{T("2. Каждый месяц эксплуатации", "2. Each operating month", "2. In jedem Betriebsmonat")}</h3>' + operating_map(data))
    body.append('<div class="deal-balance">' + money(b['rent_usd_month_end'],'USD') + ' = ' + money(f['scheduled_debt_payment_usd_month'],'USD') + ' + ' + money(p['owner_cost_usd_month'],'USD') + ' + ' + money(f['regular_equity_cash_usd_month'],'USD') + '</div>')
    body.append(f'<p class="small">{T(f"В первом платеже банку проценты составляют {money(first['interest_usd'],'USD')}, возврат основного долга — {money(first['principal_usd'],'USD')}. Дальше их соотношение меняется. Поток собственнику показан до налогов и не равен бухгалтерской прибыли. Авиакомпания должна покрыть аренду и остальные расходы выручкой от перевозок.", f"The first bank payment comprises {money(first['interest_usd'],'USD')} interest and {money(first['principal_usd'],'USD')} principal. Their proportions subsequently change. Equity cash is pre-tax and differs from accounting profit. The airline must cover rent and other costs with transport revenue.", f"Die erste Bankzahlung enthält {money(first['interest_usd'],'USD')} Zinsen und {money(first['principal_usd'],'USD')} Tilgung. Ihre Anteile verändern sich anschließend. Der Eigenkapitalzufluss liegt vor Steuern und unterscheidet sich vom bilanziellen Gewinn. Die Airline muss Miete und sonstige Kosten aus Verkehrserlösen decken.")}</p></section>')
    body.append(f'<section class="deal-stage"><h3>{T("3. Продажа в конце десятого года", "3. Resale at the end of year ten", "3. Verkauf am Ende des zehnten Jahres")}</h3>' + terminal_map(data))
    body.append('<div class="deal-balance">' + money(p['resale_usd'],'USD') + ' = ' + money(p['sale_cost_usd'],'USD') + ' + ' + money(f['remaining_debt_at_sale_usd'],'USD') + ' + ' + money(f['net_sale_cash_to_equity_usd'],'USD') + '</div>')
    body.append(f'<p class="small">{T(f"Эти суммы добавляются к обычному платежу 120-го месяца, а не заменяют его. Если будущая цена продажи окажется ниже выбранных {money(p['resale_usd'],'USD')}, уменьшается результат собственника; остаток банковского долга от этого не исчезает.", f"These amounts are additional to the regular payment in month 120. A resale below the assumed {money(p['resale_usd'],'USD')} reduces equity proceeds; it does not remove the outstanding bank debt.", f"Diese Beträge kommen zur regulären Zahlung im 120. Monat hinzu. Ein Verkauf unter den angenommenen {money(p['resale_usd'],'USD')} mindert den Eigenkapitalerlös; die Bankschuld verschwindet dadurch nicht.")}</p></section>')
    body.append(contract_flows(s))
    body.append(f'<p>{T("При sale-and-leaseback авиакомпания занимает две роли на этих схемах: сначала получает деньги как продавец, затем платит аренду как оператор. При обычной поставке продавцом выступает производитель или предыдущий владелец. Самолёт находится у оператора, право собственности — у лизинговой компании.", "In a sale-and-leaseback the airline fills two roles in these diagrams: it first receives sale proceeds, then pays rent as operator. In a regular purchase the seller is the manufacturer or previous owner. The operator uses the aircraft; the lessor owns it.", "Beim Sale-and-Leaseback übernimmt die Airline zwei Rollen: zuerst erhält sie den Verkaufserlös, danach zahlt sie als Betreiber Miete. Bei einem normalen Kauf ist der Verkäufer Hersteller oder bisheriger Eigentümer. Die Airline nutzt das Flugzeug; die Leasinggesellschaft besitzt es.")}{s.cite('lease-002','lease-004')}</p>')
    return ''.join(body)
