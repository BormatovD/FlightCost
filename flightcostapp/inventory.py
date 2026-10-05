"""Витрина хранилища: посмотреть на то, что в нём лежит.

Зачем отдельная команда. Продукт умеет показывать РАСЧЁТ — `explain`
разбирает маршрут по шагам, `heatmap` рисует ставки зон, `map` показывает,
откуда что берётся. Посмотреть на сами ДАННЫЕ нельзя было ничем, кроме
SQL, и это тот же класс отказа, что был у приёмки: контур человека
предусматривает, а показать ему нечего.

ЧТО ЭТА ВИТРИНА ДЕЛАЕТ, А ЧЕГО НЕТ.

Делает: перечисляет домены, включая пустые; для каждого показывает
покрытие, происхождение, достоверность, свежесть и историю ключа. Пустой
домен показывается наравне с наполненным — отсутствие данных это тоже
состояние, а не пробел в таблице.

Не делает: не заменяет специализированные виды. Зоны хотят карту, маршрут
хочет трассировку, наблюдения захотят временной ряд. Витрина на каждый
домен — это девять вещей, которые надо поддерживать; правильная единица не
домен, а ВОПРОС. Поэтому здесь один общий обозреватель, честный и полный,
а отдельный вид заводится тогда, когда общий на конкретном вопросе не
работает — как это уже случилось с картой сборов.

Не показывает всё. В `airport_limits` 120 тысяч строк, в реестре бортов
почти полмиллиона: вываливать их в HTML значит сделать нечитаемым и это.
Крупные домены показываются сводкой и выборкой, с явной пометкой, сколько
не показано.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime
from pathlib import Path

from .ui import style_tag

SAMPLE = 40          # строк на домен в подробном виде
BIG = 2000           # домен крупнее — только сводка и выборка

# Геометрия — ДАННЫЕ, а не ресурс пакета: лежит рядом с базой, собирается
# рецептом, в репозиторий не идёт (решение 1). Путь объявлен один раз;
# `serve.py` берёт его отсюда.
GEO = Path("data/geo")

# Домены, которые по замыслу не держат фактов, объявляют это в реестре
# полем `holds` у источника (`kind: file | table`, `at`, `what`, `facts`,
# `how`). Отсутствие поля — факты; это умолчание, а не флаг (решение 24):
# домен без `holds` и без фактов остаётся поломкой.


def collect(store, as_of=None) -> dict:
    """Состояние хранилища доменами: что есть, откуда и насколько свежо."""
    as_of = str(as_of or date.today())
    live = """valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)"""

    known = [r[0] for r in store.db.execute(
        "SELECT DISTINCT domain FROM facts ORDER BY domain")]
    # Домены, объявленные реестром, но пустые: без них витрина показывала
    # бы только успехи. Цена пустоты — главное, что о них можно сказать.
    declared = {s.get("domain") for s in
                (store.registry or {}).get("sources", {}).values()
                if s.get("domain")} if hasattr(store, "registry") else set()

    out = []
    for dom in sorted(set(known) | {d for d in declared if d}):
        n_keys = store.count_keys(dom, as_of)
        n_rows = store.db.execute(
            "SELECT COUNT(*) FROM facts WHERE domain = ?", (dom,)).fetchone()[0]
        inv = store.inventory(dom, as_of) if n_keys else {
            "keys": 0, "currencies": {}, "units": {}, "certainty": {}}
        prov = {r[0]: r[1] for r in store.db.execute(
            f"""SELECT confidence, COUNT(*) FROM facts
                WHERE domain = ? AND {live} GROUP BY confidence""",
            (dom, as_of, as_of))}
        srcs = {r[0]: r[1] for r in store.db.execute(
            f"""SELECT source_id, COUNT(*) FROM facts
                WHERE domain = ? AND {live} GROUP BY source_id""",
            (dom, as_of, as_of))}
        span = store.db.execute(
            f"""SELECT MIN(valid_from), MAX(valid_from) FROM facts
                WHERE domain = ? AND {live}""", (dom, as_of, as_of)).fetchone()
        rows = [] if n_keys > BIG else _rows(store, dom, as_of, SAMPLE)
        sample = _rows(store, dom, as_of, 12) if n_keys > BIG else []
        # Источники домена по реестру — чтобы состояние источника (когда в
        # последний раз удалось, SLA) стояло рядом с данными, а не только
        # в `fca status`.
        reg = ((store.registry or {}).get("sources", {})
               if hasattr(store, "registry") else {})
        my_sources = {sid: sv for sid, sv in reg.items()
                      if dom in (sv.get("domain") if isinstance(sv.get("domain"), list)
                                 else [sv.get("domain")])}
        holds = next((dict(sv["holds"]) for sv in my_sources.values()
                      if isinstance(sv.get("holds"), dict)), None)
        if holds:
            sla = min((sv.get("sla_days") for sv in my_sources.values()
                       if sv.get("sla_days")), default=None)
            holds.update(_holding_state(store, holds, as_of, sla))
            holds["sources"] = {sid: _source_state(store, sid)
                                for sid in my_sources}
        out.append({
            "domain": dom, "keys": n_keys, "rows_total": n_rows,
            "units": inv["units"], "currencies": inv["currencies"],
            "certainty": inv["certainty"], "provenance": prov,
            "sources": srcs, "span": [span[0], span[1]],
            "shown": rows or sample, "big": n_keys > BIG,
            "superseded": n_rows - n_keys,
            # Пусто и «всё истекло» — разные вещи, и путать их нельзя:
            # у ставок CRCO 41 ключ, но на сегодняшнюю дату не действует
            # ни один, потому что источник помесячный. Показать это как
            # «ни одного факта» значило бы обвинить контур в том, чего он
            # не делал, и спрятать настоящую причину — просрочку.
            "state": ("never" if n_rows == 0
                      else "expired" if n_keys == 0 else "live"),
            # Для домена, который фактов не держит, главное состояние — не
            # число фактов, а состояние его хранилища: файл или таблица.
            "holds": holds,
        })
    return {"as_of": as_of, "domains": out}


def _holding_state(store, holds: dict, as_of: str, sla_days) -> dict:
    """Состояние файла или таблицы, в которых живёт домен без фактов.

    Четыре исхода, и все четыре названы (решение 67):
      unknown  — не смогли посмотреть (таблицы нет, файл не читается);
      empty    — посмотрели, пусто;
      stale    — есть, но старше SLA источника;
      live     — есть и свежо.
    """
    today = date.fromisoformat(as_of)
    st: dict = {"state": "unknown", "why": "", "count": None,
                "latest": None, "age_days": None, "sla_days": sla_days}
    if holds.get("kind") == "file":
        f = Path(holds["at"])
        if not f.exists():
            st.update(state="empty", why=f"{holds['at']} нет: рецепт не запускался")
            return st
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            st.update(state="unknown", why=f"{holds['at']} не читается: {exc}")
            return st
        n = len(data) if hasattr(data, "__len__") else None
        mtime = datetime.fromtimestamp(f.stat().st_mtime).date()
        st.update(count=n, latest=mtime.isoformat(),
                  size_bytes=f.stat().st_size,
                  age_days=(today - mtime).days)
        if not n:
            st.update(state="empty", why="файл есть, но в нём ни одной зоны")
        elif sla_days and st["age_days"] > sla_days:
            st.update(state="stale",
                      why=f"файл собран {st['age_days']} дн. назад при SLA {sla_days}")
        else:
            st["state"] = "live"
        return st
    # Таблица наблюдений: что о ней известно, знает её владелец — `observe`.
    from . import observe
    if holds.get("kind") != "table":
        st["why"] = f"holds.kind = {holds.get('kind')!r}: витрина знает только file и table"
        return st
    st.update(observe.table_state(store, as_of=as_of, sla_days=sla_days,
                                  table=holds["at"]))
    return st


def _source_state(store, source_id: str) -> dict:
    """Что хранилище знает о последнем заборе источника.

    Схема таблицы состояний — ветки B, и читать её здесь по именам колонок
    значит завязаться на то, чего в этом файле не видно. Поэтому колонки
    ищутся по назначению, а если таблицы нет — ответ «не считалось», а не
    пустая строка, похожая на «никогда».
    """
    tables = [r[0] for r in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    cand = [t for t in tables if "source" in t.lower()]
    for t in cand:
        cols = [r[1] for r in store.db.execute(f"PRAGMA table_info({t})")]
        idc = next((c for c in cols if c in ("source_id", "id", "source")), None)
        if not idc:
            continue
        row = store.db.execute(
            f"SELECT * FROM {t} WHERE {idc} = ?", (source_id,)).fetchone()
        if row is None:
            return {"checked": True, "found": False,
                    "why": f"в {t} записи об источнике нет: не запускался"}
        rec = dict(zip(cols, row))
        pick = lambda *names: next((rec[c] for c in cols   # noqa: E731
                                    if any(n in c for n in names)
                                    and rec[c] not in (None, "")), None)
        return {"checked": True, "found": True, "table": t,
                "last_ok": pick("last_ok", "ok_at", "succeeded"),
                "last_check": pick("last_check", "checked", "attempt"),
                "status": pick("status", "state"),
                "message": pick("message", "note")}
    return {"checked": False, "found": False,
            "why": "таблицы состояний источников в хранилище не найдено"}


def _rows(store, domain: str, as_of: str, limit: int) -> list[dict]:
    q = """SELECT key, value, value_text, unit, currency, valid_from,
                  confidence, certainty, source_id, error_cost, confirm_by,
                  source_note
           FROM facts WHERE domain = ? AND valid_from <= ?
             AND (valid_to IS NULL OR valid_to > ?)
           ORDER BY key LIMIT ?"""
    out = []
    for r in store.db.execute(q, (domain, as_of, as_of, limit)):
        out.append({"key": r[0], "value": r[1], "text": (r[2] or "")[:160],
                    "unit": r[3], "currency": r[4], "from": r[5],
                    "prov": r[6], "certainty": r[7], "source": r[8],
                    "error_cost": r[9], "confirm_by": r[10],
                    "note": (r[11] or "")[:200]})
    return out


def build(store, as_of=None) -> str:
    data = collect(store, as_of)
    return (_TPL.replace("__DATA__", json.dumps(data, ensure_ascii=False,
                                                default=str))
                .replace("__ASOF__", html.escape(str(data["as_of"])))
                .replace("__UI__", style_tag(inline_fonts=True)))


_TPL = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Хранилище — что в нём лежит</title>
__UI__<style>
.wrap{max-width:1180px;margin:0 auto;padding:26px 24px 80px}
h1{margin:0 0 4px;font:600 19px/1.2 var(--sans)}
.sub{color:var(--dim);font-size:13px;margin:0 0 22px;max-width:78ch}
.dom{border:1px solid var(--line);border-radius:7px;margin-bottom:10px;
 background:var(--panel);overflow:hidden}
.dom.empty{border-color:var(--guess)}
.hd{display:grid;grid-template-columns:1fr 90px 1fr 26px;gap:14px;
 padding:12px 16px;cursor:pointer;align-items:baseline}
.hd:hover{background:var(--select)}
.hd .k{font:600 14px var(--mono)}
.dom.empty .hd .k{color:var(--warn)}
.hd .n{text-align:right;font-variant-numeric:tabular-nums;color:var(--dim)}
.dom.empty .hd .n{color:var(--warn)}
.hd .s{color:var(--dim);font-size:12.5px}
.hd .c{color:var(--faint);text-align:center}
.body{display:none;border-top:1px solid var(--line);padding:14px 16px 18px}
.dom.open .body{display:block}
.dom.open .hd .c{transform:rotate(90deg)}
.facets{display:flex;flex-wrap:wrap;gap:6px 18px;margin-bottom:12px;font-size:12.5px}
.facets b{color:var(--dim);font-weight:400;margin-right:5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:600;color:var(--dim);font-size:11.5px;
 padding:0 9px 6px 0;border-bottom:1px solid var(--line)}
th.r,td.r{text-align:right}
td{padding:5px 9px 5px 0;border-bottom:1px solid var(--line2);vertical-align:top}
td.k{font-family:var(--mono);white-space:nowrap}
td.v{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.txt{color:var(--faint);font-size:11.5px;max-width:46ch;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap;display:block}
.note{margin:10px 0 0}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:12.5px;margin:10px 0}
.kv dt{color:var(--dim)} .kv dd{margin:0;overflow-wrap:break-word}
.grp{margin:14px 0 4px;font-size:11.5px;color:var(--faint);
 border-bottom:1px solid var(--line);padding-bottom:4px}
.foot{margin-top:30px;padding-top:14px;border-top:1px solid var(--line);
 color:var(--faint);font-size:12.5px;max-width:80ch;line-height:1.6}
</style></head><body><div class="wrap">
<h1>Хранилище</h1>
<p class="sub">Справочники на __ASOF__. Пустой домен показан наравне с
наполненным: отсутствие данных — тоже состояние, а не пробел в таблице.
Крупные домены показаны сводкой и выборкой — вываливать сто двадцать тысяч
строк значит сделать нечитаемым и это.</p>
<div id="list"></div>
<p class="foot">Общий обозреватель, а не витрина на каждый домен. Зоны хотят
карту, маршрут — трассировку, наблюдения захотят временной ряд; правильная
единица здесь не домен, а вопрос. Отдельный вид заводится тогда, когда
общий на конкретном вопросе не работает — так уже случилось с картой
сборов.</p>
</div>
<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const fmt = v => v === null || v === undefined ? "—"
  : (typeof v === "number" ? v.toLocaleString("ru-RU",
      {maximumSignificantDigits: 6}).replace(/\u00a0/g," ") : esc(v));
const PROV = {exact:"doc", derived:"calc", estimated:"param",
              input:"user", "default":"param"};
const CERT_BAD = new Set(["stale_edition", "disputed"]);

function chips(obj, cls) {
  return Object.entries(obj || {}).map(([k, n]) =>
    `<span class="chip ${cls === "auto" ? (CERT_BAD.has(k) ? "warn"
      : PROV[k] || "") : cls}">${esc(k)} ${n}</span>`).join(" ");
}

// Состояние хранилища домена без фактов: файл или таблица. Слово и цвет
// по состоянию, и «не считалось» — отдельно от «пусто» (решение 67).
const HOLD = {unknown: ["не считалось", "warn"], empty: ["пусто", "warn"],
              stale: ["истекло", "warn"], live: ["свежо", "calc"]};
function holdHead(h) {
  const [word, cls] = HOLD[h.state] || [h.state, ""];
  return `<span class="chip ${cls}">${word}</span>`;
}
function holdBody(d) {
  const h = d.holds, [word] = HOLD[h.state] || [h.state];
  const src = Object.entries(h.sources || {}).map(([id, s]) => {
    if (!s.checked) return `<dt>${esc(id)}</dt><dd style="color:var(--warn)">${esc(s.why)}</dd>`;
    if (!s.found)   return `<dt>${esc(id)}</dt><dd style="color:var(--warn)">${esc(s.why)}</dd>`;
    return `<dt>${esc(id)}</dt><dd>${s.status ? esc(s.status) + " · " : ""}${
      s.last_ok ? "последний успех " + esc(s.last_ok) : "успеха ещё не было"}${
      s.message ? ` <span style="color:var(--faint)">— ${esc(s.message)}</span>` : ""}</dd>`;
  }).join("");
  return `<div class="note ${h.state === "live" ? "quiet" : ""}"><b>${
      h.kind === "file" ? "Файл" : "Таблица"} — ${word}.</b> ${esc(h.why || "")}</div>
    <dl class="kv">
      <dt>что</dt><dd>${esc(h.what)}</dd>
      <dt>где</dt><dd class="num">${esc(h.at)}</dd>
      <dt>факты</dt><dd>${esc(h.facts)}</dd>
      ${h.count != null ? `<dt>${h.kind === "file" ? "зон" : "строк"}</dt><dd>${
        fmt(h.count)}${h.size_bytes ? ` · ${fmt(Math.round(h.size_bytes / 1024))} КБ` : ""}</dd>` : ""}
      ${h.kinds ? `<dt>по видам</dt><dd>${Object.entries(h.kinds).map(([k, n]) =>
        `<span class="chip">${esc(k)} ${fmt(n)}</span>`).join(" ")}</dd>` : ""}
      ${h.days != null ? `<dt>суток</dt><dd>${fmt(h.days)}${
        h.first ? ` · с ${esc(String(h.first).slice(0, 10))}` : ""}${
        h.pairs != null ? ` · пар аэропортов ${fmt(h.pairs)}` : ""}</dd>` : ""}
      ${h.latest ? `<dt>${h.kind === "file" ? "собран" : "последнее"}</dt><dd>${
        esc(String(h.latest).slice(0, 19).replace("T", " "))}${
        h.age_days != null ? ` · ${fmt(h.age_days)} дн. назад` : ""}${
        h.sla_days ? ` · SLA ${fmt(h.sla_days)} дн.` : ""}</dd>` : ""}
      <dt>обновить</dt><dd class="num">${esc(h.how)}</dd>
    </dl>
    ${src ? `<div class="grp">источник в реестре</div><dl class="kv">${src}</dl>` : ""}`;
}

document.getElementById("list").innerHTML = D.domains.map((d, i) => {
  // Домен, который по замыслу фактов не держит, судится по своему
  // хранилищу, а не по числу фактов: «0 фактов» у него — не поломка.
  const hold = d.holds;
  const empty = hold ? hold.state !== "live" : d.state !== "live";
  const rows = (d.shown || []).map(r => `<tr>
      <td class="k">${esc(r.key)}${r.text ? `<span class="txt">${esc(r.text)}</span>` : ""}</td>
      <td class="v">${fmt(r.value)}</td>
      <td>${esc(r.unit || r.currency || "")}</td>
      <td class="num" style="color:var(--faint)">${esc(r.from)}</td>
      <td><span class="chip ${PROV[r.prov] || ""}">${esc(r.prov)}</span>${
        r.certainty && r.certainty !== "exact"
          ? ` <span class="chip ${CERT_BAD.has(r.certainty) ? "warn" : ""}">${
              esc(r.certainty)}</span>` : ""}</td>
    </tr>`).join("");
  const hidden = d.keys - (d.shown || []).length;
  return `<div class="dom ${empty ? "empty" : ""}" data-i="${i}">
    <div class="hd">
      <span class="k">${esc(d.domain)}</span>
      <span class="n">${hold ? holdHead(hold)
        : d.state === "never" ? "пусто"
        : d.state === "expired" ? "истекло" : d.keys.toLocaleString("ru-RU")}</span>
      <span class="s">${hold
        ? `${hold.kind === "file" ? "файл" : "таблица"} ${esc(hold.at)}${
            hold.count != null ? ` · ${fmt(hold.count)} ${hold.kind === "file" ? "зон" : "строк"}` : ""}${
            hold.latest ? ` · ${esc(String(hold.latest).slice(0, 10))}` : ""}${
            d.keys ? ` · агрегатов в фактах ${d.keys.toLocaleString("ru-RU")}` : ""}`
        : d.state === "never"
        ? "объявлен реестром, ни одного факта"
        : d.state === "expired"
          ? `${d.rows_total.toLocaleString("ru-RU")} в истории, на дату не действует ни один`
          : Object.keys(d.sources).join(", ")}</span>
      <span class="c">›</span>
    </div>
    <div class="body">
      ${hold ? holdBody(d) + (d.state === "live" ? `<div class="grp">агрегаты в фактах — ${
          d.keys.toLocaleString("ru-RU")}</div>` : hold.kind === "table"
          ? `<div class="note quiet"><b>Агрегатов в фактах нет.</b> Свёртка не
          запускалась или по парам ещё не накопилось дат — это состояние, а не сбой.</div>` : "") : ""}
      ${hold && d.state === "never" ? "" : d.state === "never" ? `<div class="note"><b>Фактов нет ни одного.</b>
          Источник объявлен в реестре и ничего не принёс: либо не
          запускался, либо разбор не дошёл, либо кладёт не факты, а файл —
          так делает геометрия зон. Смотреть
          <span class="num">fca status</span>.</div>`
        : d.state === "expired" ? `<div class="note"><b>Всё истекло.</b>
          В истории ${d.rows_total.toLocaleString("ru-RU")} записей, но на
          выбранную дату не действует ни одна: интервал закрыт у всех.
          У помесячных источников это означает просрочку обновления, а не
          отсутствие данных — <span class="num">fca refresh</span>.</div>` : `
      <div class="facets">
        <span><b>происхождение</b>${chips(d.provenance, "auto")}</span>
        <span><b>прочтение</b>${chips(d.certainty, "auto")}</span>
        ${Object.keys(d.units).length ? `<span><b>единицы</b>${
          chips(d.units, "")}</span>` : ""}
        ${Object.keys(d.currencies).length > 1 ? `<span><b>валюты</b>${
          chips(d.currencies, "")}</span>` : ""}
        <span><b>интервалы</b><span class="chip">${esc(d.span[0])} … ${
          esc(d.span[1])}</span></span>
        ${d.superseded ? `<span><b>в истории</b><span class="chip">${
          d.superseded.toLocaleString("ru-RU")} закрытых</span></span>` : ""}
      </div>
      <table><thead><tr><th>ключ</th><th class="r">значение</th>
        <th>единица</th><th>с даты</th><th>происхождение</th></tr></thead>
        <tbody>${rows}</tbody></table>
      ${hidden > 0 ? `<div class="note quiet"><b>Показано ${
        (d.shown || []).length} из ${d.keys.toLocaleString("ru-RU")}.</b>
        ${d.big ? "Домен крупный: полный список читать всё равно нельзя, "
          + "а сводка выше считана по всем строкам." : ""}</div>` : ""}
      `}
    </div></div>`;
}).join("");

document.querySelectorAll(".hd").forEach(h =>
  h.addEventListener("click", () => h.parentElement.classList.toggle("open")));
</script></body></html>"""
