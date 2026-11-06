"""История курсов: ЕЦБ (eurofxref-hist.zip) и рубль Банка России (XML_dynamic).

Проверяется то, ради чего история заведена: курс есть на каждый месяц с
2025 года, задним числом добавленные дни не перекрывают друг друга и
ежедневный курс, адрес запроса к ЦБ заканчивается сегодняшней датой, а ряд
цены топлива в России после демпфера начинается с начала окна, а не с
запуска ежедневного сборщика.
"""

from __future__ import annotations

import io
import pathlib
import sys
import tempfile
import unittest
import zipfile
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp import fx as FX                          # noqa: E402
from flightcostapp import monitor as M                      # noqa: E402
from flightcostapp.parsers import cbr_fx_hist, ecb_fx_hist  # noqa: E402
from flightcostapp.refresh import _candidate_urls, load_registry, refresh_source  # noqa: E402
from flightcostapp.store import Fact, Store                 # noqa: E402


def ecb_zip() -> bytes:
    cur = ["USD", "JPY", "GBP"] + [f"X{i:02d}" for i in range(20)]
    lines = ["Date," + ",".join(cur) + ","]
    for d, usd in (("2026-02-02", 1.18), ("2025-01-02", 1.03), ("2024-12-31", 1.04), ("2025-06-02", 1.13)):
        lines.append(f"{d},{usd}," + ",".join(["N/A" if c == "JPY" else "1.5" for c in cur[1:]]) + ",")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("eurofxref-hist.csv", "\n".join(lines))
    return b.getvalue()


def cbr_xml(days) -> bytes:
    recs = "".join(f'<Record Date="{d[8:10]}.{d[5:7]}.{d[:4]}" Id="R01239"><Nominal>1</Nominal>'
                   f'<Value>{str(v).replace(".", ",")}</Value><VunitRate>{v}</VunitRate></Record>'
                   for d, v in days)
    return (f'<?xml version="1.0" encoding="windows-1251"?><ValCurs ID="R01239" DateRange1="01.01.2025" '
            f'DateRange2="06.11.2026" name="Foreign Currency Market Dynamic">{recs}</ValCurs>').encode("windows-1251")


CBR_DAYS = [(f"2025-{m:02d}-10", 100.0 - m) for m in range(1, 13)] + \
           [(f"2026-{m:02d}-10", 90.0 + m / 10) for m in range(1, 11)]


class Parse(unittest.TestCase):
    def test_ecb_window_and_closed_intervals(self):
        facts = ecb_fx_hist.parse(ecb_zip(), {"source_id": "ecb_fx_hist"})
        usd = [f for f in facts if f.key == "USD"]
        self.assertEqual([f.valid_from for f in usd], ["2025-01-02", "2025-06-02", "2026-02-02"])
        self.assertEqual([f.valid_to for f in usd], ["2025-06-02", "2026-02-02", None])
        self.assertFalse([f for f in facts if f.key == "JPY"], "N/A не превращается в курс")

    def test_cbr_rub_series(self):
        facts = cbr_fx_hist.parse(cbr_xml(CBR_DAYS), {"source_id": "cbr_fx_hist"})
        self.assertEqual(len(facts), len(CBR_DAYS))
        self.assertEqual({f.key for f in facts}, {"RUB"})
        self.assertEqual(facts[0].valid_from, "2025-01-10")
        self.assertEqual(facts[0].valid_to, "2025-02-10")

    def test_cbr_url_ends_today(self):
        reg = load_registry()
        url = _candidate_urls(reg["sources"]["cbr_fx_hist"], date(2026, 11, 6))
        self.assertEqual(url, ["https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=01/01/2025"
                               "&date_req2=06/11/2026&VAL_NM_RQ=R01239"])


class Through(unittest.TestCase):
    def test_history_behind_existing_daily_rate(self):
        tmp = tempfile.TemporaryDirectory()
        st = Store(pathlib.Path(tmp.name) / "f.db", shared=True)
        try:
            # Ежедневный курс уже есть — за октябрь 2026.
            st.commit_facts([Fact(domain="fx", key="RUB", valid_from="2026-10-20", value=91.5, unit="per_EUR",
                                  currency="RUB", source_id="cbr_fx", extracted_by="t")])
            reg = load_registry()
            r = refresh_source("cbr_fx_hist", reg, st,
                               fetch=lambda url, timeout=60: (cbr_xml(CBR_DAYS), "text/xml"),
                               today=date(2026, 11, 6))
            if r["outcome"] == "proposal":
                st.resolve_proposal(r["proposal_id"], True, "тест")
            self.assertEqual(st.value("fx", "RUB", "2025-03-28"), 97.0)
            self.assertEqual(st.value("fx", "RUB", "2026-10-28"), 91.5, "свежий ежедневный курс главнее")
            self.assertEqual(FX.quote(st, "RUB", "2025-03-28")["kind"], "cbr")
            # Ряд России после демпфера — с начала окна.
            st.commit_facts([Fact(domain="fx", key="USD", valid_from="2025-01-02", value=1.1, unit="per_EUR",
                                  currency="USD", source_id="ecb_fx_hist", extracted_by="t")])
            regs = [{"code": "russia_centre", "k": 1.2, "conf": "",
                     "line": [(f"2025-{m:02d}", 1000) for m in range(1, 13)]}]
            out = M._russia_net(st, regs, [("2024-12", 10000.0)], 3000.0)
            self.assertEqual(out[0]["line"][0][0], "2025-01")
            self.assertEqual(len(out[0]["line"]), 12)
        finally:
            st.db.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
