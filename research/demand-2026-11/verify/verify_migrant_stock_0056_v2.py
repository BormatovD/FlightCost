#!/usr/bin/env python3
"""Independent complete-cube audit of official Eurostat country-of-birth stock.

Uses row-major Cartesian coordinates rather than the collector's stride helper.
Coverage is recalculated from a long pandas table. No collector is imported.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import re

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
YEARS = list(range(2005, 2026))


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage(frame):
    valid = frame["value"].notna()
    counts = frame.groupby(["residence", "origin"], dropna=False)["value"].count()
    periods = frame.loc[valid, "year"]
    return {"series":len(counts),"series_with_any_numeric_value":int((counts>0).sum()),
            "series_with_all_21_numeric_values":int((counts==21).sum()),"expected_cells":len(frame),
            "numeric_cells":int(valid.sum()),"missing_cells":int((~valid).sum()),
            "observed_zero_cells":int((frame["value"]==0).sum()),
            "first_year_with_numeric_value":int(periods.min()) if len(periods) else None,
            "last_year_with_numeric_value":int(periods.max()) if len(periods) else None,
            "flags":dict(sorted(frame["flag"].dropna().value_counts().to_dict().items()))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir",type=Path,required=True)
    args = parser.parse_args()
    panel=load(OUT/"migrant_stock.json.gz")
    summary=load(OUT/"migrant_stock_summary.json")
    failures=[]; raw_cells=[]; checks=[]

    def same(name,actual,stored):
        if actual!=stored:
            failures.append({"check":name,"independent":actual,"stored":stored})

    same("panel hash",sha(OUT/"migrant_stock.json.gz"),summary["meta"]["panel_sha256"])
    same("years",YEARS,panel["meta"]["years"])
    same("reference dates",[f"{y}-01-01" for y in YEARS],panel["meta"]["reference_dates"])
    all_stored=panel["country_series"]+panel["aggregate_series"]+panel["other_series"]
    keyed={(r["country_of_residence"],r["c_birth"]):r for r in all_stored}
    same("series keys unique",len(keyed),len(all_stored))
    groups={(r["country_of_residence"],r["c_birth"]):group for group in ("country_series","aggregate_series","other_series") for r in panel[group]}
    kind_counts=Counter()
    seen_keys=set()
    for residence in ("DE","ES","FR","IT","NL"):
        name="migrant_stock_probe_"+residence.lower()
        path=args.raw_dir/(name+".raw")
        raw=load(path); meta=load(path.with_suffix(".meta.json"))
        source=panel["meta"]["sources"]["eurostat-migr-pop3ctb-"+residence.lower()]
        same(residence+":raw SHA",sha(path),meta["sha256"])
        same(residence+":source SHA",sha(path),source["sha256"])
        same(residence+":HTTP",meta["status"],200)
        same(residence+":source URL",meta["url"],source["url"])
        same(residence+":updated timestamp",raw.get("updated"),source["source_updated_at"])
        axes={}
        for key in raw["id"]:
            category=raw["dimension"][key]["category"]
            index=category["index"]
            axes[key]=list(index) if isinstance(index,list) else [c for c in sorted(index,key=index.get)]
            stored_axis=panel["source_dimensions"][residence][key]
            same(residence+":axis:"+key,[{"code":c,"label":category.get("label",{}).get(c,c)} for c in axes[key]],stored_axis)
        same(residence+":shape",[len(axes[k]) for k in raw["id"]],raw["size"])
        for key,value in {"freq":"A","geo":residence,"sex":"T","age":"TOTAL","unit":"NR"}.items():
            same(residence+":filter:"+key,axes[key],[value])
        same(residence+":time axis",[int(y) for y in axes["time"]],YEARS)
        source_values=raw.get("value",{})
        source_flags=raw.get("status",{})
        observed=0
        for index,coordinates in enumerate(itertools.product(*(axes[k] for k in raw["id"]))):
            coordinates=dict(zip(raw["id"],coordinates))
            origin,year=coordinates["c_birth"],int(coordinates["time"])
            value=source_values.get(str(index)) if isinstance(source_values,dict) else source_values[index]
            flag=source_flags.get(str(index)) if isinstance(source_flags,dict) else source_flags[index]
            row=keyed[(residence,origin)]
            same(f"{residence}:{origin}:{year}:value",value,row["values"][year-2005])
            same(f"{residence}:{origin}:{year}:flag",flag,row["flags"][year-2005])
            if value is not None:
                observed+=1
                if isinstance(value,bool) or int(value)!=value or value<0:
                    failures.append({"check":"invalid source population","residence":residence,"origin":origin,"year":year})
            raw_cells.append({"residence":residence,"origin":origin,"year":year,"value":value,"flag":flag,"kind":row["origin_kind"],"group":groups[(residence,origin)],"cross_border":row["cross_border_pair"]})
        for origin in axes["c_birth"]:
            row=keyed[(residence,origin)]
            seen_keys.add((residence,origin))
            label=raw["dimension"]["c_birth"]["category"]["label"][origin]
            same(residence+":"+origin+":label",label,row["country_of_birth_label"])
            same(residence+":"+origin+":unit","persons",row["unit"])
            same(residence+":"+origin+":source_id","eurostat-migr-pop3ctb-"+residence.lower(),row["source_id"])
            # Source categories reviewed independently: AN and grouped historical
            # countries are historical; FR91–94 are old NUTS, not country origins.
            if re.fullmatch(r"[A-Z]{2}",origin) and origin!="AN":
                kind="country_or_territory"
                same(residence+":"+origin+":country group","country_series",groups[(residence,origin)])
                same(residence+":"+origin+":origin country",origin,row["country_of_birth"])
                same(residence+":"+origin+":cross border",origin!=residence,row["cross_border_pair"])
            else:
                kind=({"NAT":"reporter_relative_native_born","UNK":"unknown_country_of_birth","RNC":"other_special_category","OTH":"other_special_category"}.get(origin)
                      or ("historical_geography" if origin in {"AN","CZ_SK","RS_ME","EX_YU","EX_SU"}
                          else "subnational_geography" if origin in {"FR91","FR92","FR93","FR94"} else "aggregate"))
                same(residence+":"+origin+":not individual country",None,row["country_of_birth"])
                same(residence+":"+origin+":not bilateral",None,row["cross_border_pair"])
                same(residence+":"+origin+":special group","aggregate_series" if kind=="aggregate" else "other_series",groups[(residence,origin)])
            same(residence+":"+origin+":kind",kind,row["origin_kind"])
            if residence=="DE":kind_counts[kind]+=1
        checks.append({"residence":residence,"source_cells":len(axes["c_birth"])*len(YEARS),"numeric_cells":observed,"raw_sha256":sha(path)})
    same("complete source-key coverage",sorted(seen_keys),sorted(keyed))
    frame=pd.DataFrame(raw_cells)
    same("all coverage",coverage(frame),summary["all_categories"])
    same("category counts",dict(sorted(kind_counts.items())),summary["origin_categories"])
    for group in ("country_series","aggregate_series","other_series"):
        same(group+":coverage",coverage(frame[frame.group==group]),summary["category_groups"][group])
    for residence,stats in summary["reporters"].items():
        local=frame[frame.residence==residence]
        countries=local[local.kind=="country_or_territory"]
        cross=countries[countries.cross_border==True]
        for name,sub in {"all_categories":local,"country_or_territory":countries,"cross_border_country_pairs":cross,"aggregates":local[local.group=="aggregate_series"],"other_categories":local[local.group=="other_series"]}.items():
            same(residence+":"+name,coverage(sub),stats[name])
        same(residence+":bilateral availability",bool(cross.value.notna().any()),stats["bilateral_country_input_available"])
        for item in stats["annual_coverage"]:
            sub=countries[countries.year==item["year"]]
            expected={"year":item["year"],"country_territory_origins_numeric":int(sub.value.notna().sum()),"cross_border_origins_numeric":int(sub[sub.cross_border==True].value.notna().sum()),"country_territory_origins_missing":int(sub.value.isna().sum()),"observed_zero_country_territory_origins":int((sub.value==0).sum())}
            same(residence+":annual:"+str(item["year"]),expected,item)
        for key,code in (("latest_total_population","TOTAL"),("latest_foreign_born_aggregate","FOR"),("latest_native_born","NAT"),("latest_unknown_birthplace","UNK")):
            sub=local[(local.origin==code)&local.value.notna()].sort_values("year")
            if len(sub):
                r=sub.iloc[-1]
                expected={"c_birth":code,"year":int(r.year),"reference_date":f"{int(r.year)}-01-01","persons":int(r.value),"flag":r.flag}
            else:expected=None
            same(residence+":"+key,expected,stats[key])
    same("DE absence remains missing",0,summary["reporters"]["DE"]["country_or_territory"]["numeric_cells"])
    result={"stage":"0056-v2","status":"pass_with_limitations" if not failures else "fail","independent":True,"panel_sha256":sha(OUT/"migrant_stock.json.gz"),"summary_sha256":sha(OUT/"migrant_stock_summary.json"),"method":"Independent Cartesian JSON-stat decoding; every numeric, missing and flag cell compared. Long-table pandas groupby recalculates all overall, category, residence and annual coverage measures. No collection module imported.","checks":checks,"cells_checked":len(frame),"series_checked":len(keyed),"numeric_values_checked":int(frame.value.notna().sum()),"country_pair_numeric_values":int(frame[frame.kind=="country_or_territory"].value.notna().sum()),"failures":failures,
            "manual_semantics":["The measure is resident population on 1 January by country of birth, not nationality or annual journeys.","The origin catalogue mixes individual countries/territories, overlapping aggregate groups, historical entities and old NUTS areas; they stay separate.","Original Eurostat EL/UK and other geography labels remain unchanged. No ISO or sovereignty harmonization is silently performed.","Own-country birth rows are marked non-cross-border; NAT is reporter-relative and is not invented as another country code.","Current revised history is not a vintage database proving what was known at an old forecast origin."],
            "limitations":["DE has zero individual-origin observations in the selected slice, not a zero foreign-born population.","ES and FR have sparse/changing individual-origin coverage; latest aggregate totals must not fill missing bilateral cells.","Country-level stocks cannot allocate passengers to city pairs without additional geography and a tested trip-frequency relationship.","The collected panel does not estimate the diaspora coefficient or resolve causal travel demand."]}
    (HERE/"migrant_stock_0056_v2.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(result["status"],result["cells_checked"],"cells;",result["numeric_values_checked"],"numeric;",len(failures),"failures")


if __name__=="__main__":
    main()
