#!/usr/bin/env python3
"""Read-only structural audit of the 0057 article presentation.

Checks rendered HTML against the stored data without importing chart builders.
This does not independently validate calibration economics, browser interaction,
font metrics, screenshots or pixel rendering.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from lxml import html

HERE = Path(__file__).resolve().parents[1]
RESEARCH = HERE.parent
ROOT = RESEARCH.parent
CHECKS = Counter()
FAILURES = []
POLICY = ".wrap p,.wrap li{max-width:none}"
OLD_POLICY = "p,li{max-width:80ch}"
DISPLAY = {"turboprop": ["AT46", "AT76"], "regional": ["E75L", "E295"],
           "narrowbody": ["A20N", "A21N"], "widebody": ["A359", "B789"]}


def cls(name):
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def nodes(element, name):
    return element.xpath(".//*[" + cls(name) + "]")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(label, actual, expected, tolerance=None):
    CHECKS[label.split("/")[0]] += 1
    if tolerance is not None:
        ok = math.isclose(float(actual),float(expected),rel_tol=2e-10,abs_tol=tolerance)
    else:
        ok = actual == expected
    if not ok:
        def compact(value):
            if isinstance(value,str) and len(value)>500:
                return {"characters":len(value),"sha256":hashlib.sha256(value.encode()).hexdigest()}
            return value
        FAILURES.append({"check":label,"actual":compact(actual),"expected":compact(expected)})


def text(element):
    return "".join(element.itertext())


def number(value, lang):
    value=value.replace("\u00a0","").replace("\u202f","").replace(" ","").replace("−","-")
    if lang=="en":
        return float(value.replace(",",""))
    if lang=="de":
        value=value.replace(".","")
    return float(value.replace(",","."))


def numbers(value,lang):
    return [number(v,lang) for v in re.findall(r"[−-]?\d+(?:[.,\u00a0\u202f]\d+)*",value)]


def point(period):
    y=int(period[:4])
    if len(period)==4:
        return y+.5
    if "Q" in period:
        return y+(int(period[-1])-.5)/4
    return y+(int(period[-2:])-.5)/12


def transforms(svg,lang):
    xticks=[(number(text(t),lang),float(t.get("x"))) for t in svg.xpath('./text[@text-anchor="middle"]')]
    yticks=[(number(text(t),lang),float(t.get("y"))-4) for t in svg.xpath('./text[@text-anchor="end"]')]
    xticks.sort();yticks.sort()
    (x0,p0),(x1,p1)=xticks[0],xticks[-1]
    (y0,q0),(y1,q1)=yticks[0],yticks[-1]
    return (lambda v:p0+(v-x0)*(p1-p0)/(x1-x0),lambda v:q0+(v-y0)*(q1-q0)/(y1-y0))


def audit_shared_layout():
    source=(RESEARCH/"_report.py").read_text()
    check("layout/source_rule",POLICY in source,True)
    check("layout/source_old_limit",OLD_POLICY in source,False)
    files=sorted(RESEARCH.glob("*/report*.html"))
    check("layout/report_count",len(files),30)
    unchanged=[]
    for path in files:
        current=path.read_text()
        check("layout/embedded_rule/"+str(path.relative_to(RESEARCH)),POLICY in current,True)
        check("layout/old_limit_removed/"+str(path.relative_to(RESEARCH)),OLD_POLICY in current,False)
        doc=html.fromstring(current)
        check("layout/single_wrapper/"+path.parent.name,len(nodes(doc,"wrap")),1)
        if path.parent.name in {"aircraft-prices-2026-11","demand-2026-11"}:
            continue
        previous=subprocess.run(["git","show","HEAD:"+str(path.relative_to(ROOT))],cwd=ROOT,
                                capture_output=True,check=True).stdout.decode()
        # Existing articles should receive only the common width correction.
        check("layout/existing_content_preserved/"+str(path.relative_to(RESEARCH)),
              current,previous.replace(OLD_POLICY,POLICY))
        unchanged.append(str(path.relative_to(RESEARCH)))
    return {"reports_with_shared_fix":len(files),"other_reports_content_preserved":len(unchanged),
            "rule":POLICY,"previous_rule":OLD_POLICY,
            "meaning":"All paragraph/list blocks now share their existing parent width; no new horizontal translation or font family is introduced."}


def audit_report(path,lang,history,models,calibrations):
    doc=html.fromstring(path.read_bytes())
    tag="html_"+lang
    check(tag+"/language",doc.get("lang"),lang)
    svgs=doc.xpath('//svg[@data-kind and @data-segment]')
    check(tag+"/history_charts",len(svgs),8)
    check(tag+"/panels",len(nodes(doc,"segment-panel")),4)
    purchase=nodes(doc,"purchase-history")
    check(tag+"/purchase_details",len(purchase),4)
    for detail in purchase:
        check(tag+"/purchase_is_details",detail.tag,"details")
        check(tag+"/purchase_closed",detail.get("open"),None)
        check(tag+"/purchase_contains_only_value",[s.get("data-kind") for s in detail.xpath('.//svg[@data-kind]')],["value"])
    raw=doc.xpath('//polyline[@data-reference-role="raw_parametric"]')
    cards=nodes(doc,"model-card")
    corrections=nodes(doc,"model-correction")
    selected={code for pair in DISPLAY.values() for code in pair}
    corrected={code for code in selected if calibrations[code]["calibration"]["multiplier_mid"] is not None}
    check(tag+"/raw_count",len(raw),8)
    check(tag+"/raw_types",{n.get("data-icao") for n in raw},selected)
    check(tag+"/card_count",len(cards),8)
    check(tag+"/card_types",{n.get("data-icao") for n in cards},selected)
    check(tag+"/short_correction_count",len(corrections),5)
    check(tag+"/correction_types",{n.get("data-icao") for n in corrections},corrected)
    check(tag+"/no_extra_model_curves",len(doc.xpath('//polyline[@data-reference-role]')),8)
    market_count=0
    for svg in svgs:
        segment,kind=svg.get("data-segment"),svg.get("data-kind")
        codes=DISPLAY[segment]
        X,Y=transforms(svg,lang)
        div=1000 if kind=="lease" else 1e6
        unit={"ru":{"lease":"тыс. USD в месяц","value":"млн USD за ВС"},
              "en":{"lease":"USD thousands per month","value":"USD million per aircraft"},
              "de":{"lease":"Tsd. USD pro Monat","value":"Mio. USD je Flugzeug"}}[lang][kind]
        check(tag+"/axis_unit/"+segment+kind,text(svg.xpath('./text')[0]),unit)
        check(tag+"/historical_usd_fixed/"+segment+kind,len(nodes(svg,"mny")),0)
        ancestors=svg.xpath('ancestor::details')
        check(tag+"/visibility/"+segment+kind,len(ancestors),1 if kind=="value" else 0)
        obs=svg.xpath('.//g[@data-observation-id]')
        expected={o["id"]:o for o in history["observations"] if o["icao"] in codes and o["kind"]==kind and o["age"]["category"]=="new"}
        check(tag+"/observation_selection/"+segment+kind,{o.get("data-observation-id") for o in obs},set(expected))
        check(tag+"/two_types/"+segment+kind,{o.get("data-icao") for o in obs},set(codes))
        market_count+=len(obs)
        for node in obs:
            row=expected[node.get("data-observation-id")]
            check(tag+"/observation_period",node.get("data-period"),row["period"])
            check(tag+"/observation_quality",node.get("data-quality"),row["quality"])
            check(tag+"/observation_new_age",node.get("data-age-category"),"new")
            check(tag+"/source_link",node.getparent().get("href"),row["source_url"])
            circle=node.xpath('./circle')[0]
            check(tag+"/observation_x",circle.get("cx"),X(point(row["period"])),.012)
            check(tag+"/observation_y",circle.get("cy"),Y((row["amount_low_usd"]+row["amount_high_usd"])/2/div),.012)
            check(tag+"/published_range_present",bool(node.xpath('./path')),row["amount_high_usd"]!=row["amount_low_usd"])
        if kind!="lease":
            check(tag+"/no_purchase_model",len(nodes(svg,"model-reference"))+len(nodes(svg,"model-card")),0)
            continue
        current_cards={node.get("data-icao"):node for node in nodes(svg,"model-card")}
        rectangles=[node.xpath('./rect')[0] for node in current_cards.values()]
        boxes=sorted((float(r.get("y")),float(r.get("y"))+float(r.get("height"))) for r in rectangles)
        check(tag+"/cards_no_vertical_overlap",boxes[0][1]<=boxes[1][0],True)
        first_card_x=min(float(r.get("x")) for r in rectangles)
        for curve in nodes(svg,"model-reference"):
            code=curve.get("data-icao"); model=models[code]
            check(tag+"/model_age",int(curve.get("data-model-age-years")),model["model_age_years"])
            check(tag+"/model_eur",curve.get("data-model-lease-eur-month"),model["raw_parametric_lease_eur_month"],.00001)
            check(tag+"/model_dashdot",curve.get("stroke-dasharray"),"10 4 2 4")
            points=[list(map(float,p.split(','))) for p in curve.get("points").split()]
            check(tag+"/model_point_count",len(points),len(model["nominal_usd_points"]))
            for coordinates,ref in zip(points,model["nominal_usd_points"]):
                check(tag+"/model_x",coordinates[0],X(ref["x"]),.012)
                check(tag+"/model_y",coordinates[1],Y(ref["lease_thousand_usd_month"]),.012)
            check(tag+"/model_last_year",model["nominal_usd_points"][-1]["year"],2026)
            check(tag+"/right_card_clearance",points[-1][0]<first_card_x-20,True)
            links=[n for n in nodes(svg,"model-card-link") if n.get("data-icao")==code]
            check(tag+"/one_connector",len(links),1)
            start=list(map(float,re.findall(r"[-+]?\d*\.?\d+",links[0].get("d"))[:2]))
            check(tag+"/connector_x",start[0],points[-1][0],.012)
            check(tag+"/connector_y",start[1],points[-1][1],.012)
            card=current_cards[code]
            check(tag+"/card_age",int(card.get("data-model-age-years")),model["model_age_years"])
            check(tag+"/card_title",text(nodes(card,"card-title")[0]),model["label"])
            check(tag+"/card_and_curve_colour",nodes(card,"card-title")[0].get("fill"),curve.get("stroke"))
            for observation in obs:
                if observation.get("data-icao")==code:
                    check(tag+"/observation_and_curve_colour",observation.xpath('./circle')[0].get("stroke"),curve.get("stroke"))
            check(tag+"/card_model_year","2026" in text(card),True)
            check(tag+"/card_no_literal_escape","\\xa0" in text(card) or "\\u00a0" in text(card),False)
            value_nodes=nodes(card,"card-value")
            before=numbers(text(value_nodes[0]),lang)[0]
            check(tag+"/card_before_rounded",before,model["nominal_usd_points"][-1]["lease_thousand_usd_month"],.50001)
            formula=numbers(text(nodes(card,"card-formula")[0]),lang)
            check(tag+"/card_formula_components",len(formula),5)
            for actual,expected,tol in zip(formula,[model["reference_lease_eur_month"]/1000,model["mtow_t"],78,1.1,1.16],[.0001,.05001,.0001,.0001,.0001]):
                check(tag+"/card_formula_value",actual,expected,tol)
            cal=calibrations[code]["calibration"]
            if cal["multiplier_mid"] is None:
                check(tag+"/card_no_after_for_aged",len(value_nodes),1)
                check(tag+"/aged_correction_not_claimed",any(phrase in text(card) for phrase in ("Поправка не определена","Correction not established","Korrektur nicht bestimmt")),True)
            else:
                check(tag+"/card_after_exists",len(value_nodes),2)
                shown=numbers(text(value_nodes[1]),lang)
                target=[cal["amount_mid_usd"]/1000]
                if cal["amount_high_usd"]!=cal["amount_low_usd"]:
                    target.extend([cal["amount_low_usd"]/1000,cal["amount_high_usd"]/1000])
                check(tag+"/card_after_range_count",len(shown),len(target))
                for actual,expected in zip(shown,target):
                    check(tag+"/card_after_reference",actual,expected,.50001)
                ktext=[text(n) for n in card.xpath('./text') if text(n).startswith("k =")]
                check(tag+"/one_coefficient",len(ktext),1)
                check(tag+"/display_coefficient",numbers(ktext[0],lang)[0],cal["multiplier_mid"],.00050001)
                check(tag+"/card_anchor_year",cal["period"][:4] in ktext[0],True)
                if "Q" in cal["period"]:
                    check(tag+"/card_anchor_quarter",("кв." in ktext[0]) if lang=="ru" else ("Q1" in ktext[0]),True)
                correction=[n for n in nodes(svg,"model-correction") if n.get("data-icao")==code][0]
                check(tag+"/calibration_period",correction.get("data-period"),cal["period"])
                check(tag+"/calibration_age",int(correction.get("data-model-age-years")),cal["age_years"])
                check(tag+"/calibration_multiplier",correction.get("data-multiplier"),cal["multiplier_mid"],1e-10)
                check(tag+"/not_prediction_validation",correction.get("data-independent-validation"),"false")
                pathnums=list(map(float,re.findall(r"[-+]?\d*\.?\d+",correction.xpath('./path')[0].get("d"))))
                check(tag+"/calibration_short_path_vertices",len(pathnums),3)
                for actual,expected in zip(pathnums,[X(cal["display_span_x"][0]),Y(cal["amount_mid_usd"]/1000),X(cal["display_span_x"][1])]):
                    check(tag+"/calibration_short_path",actual,expected,.012)
                check(tag+"/no_calibration_polyline",len(correction.xpath('.//polyline')),0)
                check(tag+"/calibration_range_band",len(correction.xpath('./rect')),int(cal["amount_high_usd"]!=cal["amount_low_usd"]))
                if correction.xpath('./rect'):
                    rectangle=correction.xpath('./rect')[0]
                    for attribute,expected in {
                        "x":X(cal["display_span_x"][0]),
                        "width":X(cal["display_span_x"][1])-X(cal["display_span_x"][0]),
                        "y":Y(cal["amount_high_usd"]/1000),
                        "height":Y(cal["amount_low_usd"]/1000)-Y(cal["amount_high_usd"]/1000),
                    }.items():
                        check(tag+"/calibration_range_coordinate/"+attribute,rectangle.get(attribute),expected,.012)
    # The full fifteen-type model table remains behind the explanatory disclosure.
    expected_labels={r["label"] for r in models.values()}
    full_tables=[]
    for table in doc.xpath('//details//table'):
        labels={text(td) for td in table.xpath('./tbody/tr/td[1]')}
        if expected_labels<=labels:
            full_tables.append(table)
    check(tag+"/full_fifteen_type_table_preserved",len(full_tables),1)
    check(tag+"/calibration_table_rows",len(doc.xpath('//table[@id="lease-calibration"]/tbody/tr')),5)
    check(tag+"/fixed_fx_documented","1,16" in text(doc) if lang!="en" else "1.16" in text(doc),True)
    check(tag+"/widget_fx_documented","1,113" in text(doc) if lang!="en" else "1.113" in text(doc),True)
    return {"language":lang,"history_panels":4,"visible_lease_charts":4,"collapsed_purchase_charts":4,
            "market_observations_displayed":market_count,"raw_model_curves":len(raw),"formula_cards":len(cards),
            "dated_calibration_markers":len(corrections),"full_model_table_types":len(expected_labels)}


def main():
    history=json.loads((HERE/'out/segments_history.json').read_text())
    models={r["icao"]:r for r in json.loads((HERE/'out/model_reference.json').read_text())["aircraft"]}
    calibrations={r["icao"]:r for r in json.loads((HERE/'out/lease_calibration.json').read_text())["aircraft"]}
    layout=audit_shared_layout()
    reports=[]
    files=[]
    for lang in ('ru','en','de'):
        path=HERE/('report.html' if lang=='ru' else f'report.{lang}.html')
        reports.append(audit_report(path,lang,history,models,calibrations));files.append(path)
    result={"checked_on":"2026-11-11","status":"fail" if FAILURES else "pass_with_limitations",
            "scope":"Structural HTML/data-binding/coordinate audit; not independent economics validation or browser pixel QA.",
            "checks":dict(CHECKS),"checks_total":sum(CHECKS.values()),"failure_count":len(FAILURES),"failures":FAILURES[:100],
            "shared_layout":layout,"price_reports":reports,
            "inputs_sha256":{str(p.relative_to(ROOT)):sha(p) for p in files+[RESEARCH/'_report.py',HERE/'model_cards.py',HERE/'report_extensions.py',HERE/'out/lease_calibration.json']},
            "limitations":["The author of lease_calibration.py performed this display audit; economic values are treated as input, not independently revalidated here.",
                           "No browser was available; details interaction, actual font shaping and pixel alignment require separate visual review.",
                           "Numeric labels intentionally round card amounts; coordinates and data attributes are checked against full precision.",
                           "The old formula describes an approximately twelve-year-old aircraft for ATR/E175; the audit checks that no same-age correction is claimed."]}
    (Path(__file__).parent/'display_0057.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=lambda x:sorted(x))+'\n')
    print(result['status'],result['checks_total'],'checks;',len(FAILURES),'failures')
    if FAILURES:
        print(json.dumps(FAILURES[:12],ensure_ascii=False,default=lambda x:sorted(x),indent=2)[:12000])
        raise SystemExit(1)


if __name__=='__main__':
    main()
