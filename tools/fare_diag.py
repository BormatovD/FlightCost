"""Где в сырых выгрузках цена 1000+ на коротких парах: файл, заголовок, строка."""
import csv, glob, sys
pairs = {("FRA", "ZRH"), ("MUC", "HAM"), ("HEL", "ARN"), ("LHR", "MAD")}
for f in sorted(glob.glob("data/raw/market_fare/*.csv", recursive=True)):
    with open(f, encoding="utf-8", errors="replace") as fh:
        rd = csv.reader(fh)
        head = next(rd, [])
        if "price" not in head:
            continue
        ip, io, idd = head.index("price"), head.index("origin_req"), head.index("destination_req")
        bad = [r for r in rd if len(r) > max(ip, io, idd) and (r[io], r[idd]) in pairs
               and r[ip].replace(".", "", 1).isdigit() and float(r[ip]) > 1000]
        if bad:
            print(f"\n== {f}: строк {len(bad)}; колонок в заголовке {len(head)}, в строке {len(bad[0])}")
            print("заголовок:", head)
            for r in bad[:3]:
                print("строка:   ", r)
