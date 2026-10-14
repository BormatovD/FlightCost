"""Экономика эксплуатации флота.

Три статьи — владение, ТОиР и экипаж — дают около трети себестоимости
рейса и до сих пор задавались тремя плоскими ставками за час, взятыми
из головы. Плоская ставка неверна не только величиной, но и формой.

**Почему час — не единственный драйвер.** Восстановление двигателей,
тяжёлые формы и пул компонентов идут по налёту. А шасси, ВСУ, детали с
ограниченным ресурсом и линейное обслуживание — по посадкам. Цикловые
статьи не зависят от длительности рейса вовсе: часовой рейс и
шестичасовой изнашивают шасси одинаково. Значит короткое плечо дороже в
пересчёте на час, и плоская ставка его систематически занижает — ровно
та же ошибка, что была с топливом до подключения профиля полёта.

**Почему владение считается через налёт.** Лизинг платится за месяц, а
не за час. Ставка за час — производная величина: месячный платёж,
делённый на месячный налёт борта. Оба множителя добываемы по
отдельности, непрозрачный EUR/ч — нет. Отсюда же следует, почему
единицей расчёта стал маршрут с частотой: частота задаёт налёт.

**Про значения.** Ставки конкретных договоров лизинга и обслуживания не
публикуются. Поэтому здесь не справочник, а параметрическая заготовка:
масштабирование от массы и числа кресел по поколению типа, с явно
выписанными коэффициентами. Её уровень сверен с полосой — Form 41
перевозчиков США, оценки лизинга IBA и годовая отчётность (решения
177–186, `fca bench`), — но это всё равно заготовка, а не ставка
перевозчика. Пользователь подставляет свои — это и есть замысел
продукта: структура наша, ставки его.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cycles import Split, fit, from_share

# ---------------------------------------------------------------------
# Параметрическая заготовка.
#
# Опорная точка — узкофюзеляжный борт около 78 т: лизинг по поколению
# (GENERATIONS), ТОиР 900 EUR/ч на плече 1,8 ч, экипаж 700 EUR/ч. Уровни
# сверены с полосой (решение 186), но это НЕ измерения, а связная
# заготовка. Каждый коэффициент выписан отдельной строкой именно для
# того, чтобы его было легко оспорить и заменить.
# ---------------------------------------------------------------------

DEFAULTS = {
    # Лизинг: месячная ставка растёт примерно как масса в степени 1.1.
    # Опорная точка — узкофюзеляжный борт 78 т. Уровень — по поколению,
    # см. GENERATIONS ниже (решение 186); это значение — текущее поколение.
    "lease_ref_mtow_t": 78.0,
    "lease_ref_eur_month": 200_000.0,
    "lease_mtow_exponent": 1.10,

    # Налёт: часов в месяц на борт. Лоукостер держит 11-12 ч в сутки,
    # сетевой на ближних плечах 8-9. Берём среднее.
    #
    # По-русски именно «налёт»: «утилизация» означает списание техники,
    # то есть ровно противоположное. Английское utilisation — калька,
    # от которой здесь отказались.
    "monthly_hours": 300.0,

    # ИЗВЕСТНАЯ ПРИВЯЗКА, не применённая намеренно.
    #
    # Техники Lufthansa и Аэрофлота (2026, неформально) называют полную
    # стоимость обслуживания семейства A320 около 1000 EUR за блок-час при
    # среднем плече чуть больше двух часов. Наша заготовка даёт там 842,
    # то есть занижает примерно на 16% — внутри целевых ±15% впритык.
    #
    # Подгонять по этой точке не стали. Одна точка позволяет сдвинуть
    # уровень, но не проверить структуру: тот же промах объясняется и
    # заниженной почасовой частью, и неверной долей цикловой, и тем, что
    # в названную цифру входит что-то, чего у нас нет. Различить можно
    # только по двум точкам на разных плечах.
    #
    # Кроме того, это по построению пользовательские данные: перевозчик
    # знает свою ставку точно, и подставит её через слой сценария.
    # Заготовка должна оставаться связной и объяснимой, а не подогнанной.

    # ТОиР: делится на почасовую и поцикловую части. Доля цикловой у
    # узкофюзеляжных примерно 45% при типичном плече — шасси, ВСУ,
    # ресурсные детали двигателя, линейное обслуживание за прилёт-вылет.
    "maint_ref_eur_h": 900.0,
    "maint_cycle_share": 0.45,
    "maint_ref_block_h": 1.8,          # плечо, на котором доли равны заявленным
    "maint_mtow_exponent": 0.85,

    # Экипаж: почасовая оплата плюс постоянная часть на вылет — брифинг,
    # предполётная и послеполётная работа.
    "crew_ref_eur_h": 700.0,
    "crew_fixed_eur_cycle": 260.0,
    "crew_seats_exponent": 0.60,       # численность кабинного экипажа от кресел
    "crew_ref_seats": 180.0,
}


# ПОКОЛЕНИЕ (решение 186). Прежняя заготовка ставила рядом лизинг НОВОГО
# борта (330 тыс. EUR — уровень A320neo) и ТОиР борта СРЕДНИХ ЛЕТ (900 EUR/ч)
# — пару, которой не бывает у одного самолёта. Сумма владения и ТОиР
# выходила 566 тыс. EUR на борт в месяц при 433 по Form 41 США (A320ceo) и
# 469 у Wizz (новый парк A320/A321neo). Разделение по поколению сводит
# обе пары в полосу:
#
#   текущее (ceo, NG, E1, CRJ…), борт около 12 лет: лизинг IBA 07/2026 —
#     220 тыс. USD у A320ceo 12 лет, 228 тыс. у 737-800 → ≈ 200 тыс. EUR;
#     ТОиР — прежний, он в нижней половине полосы Form 41 (A320ceo:
#     медиана 1 249 USD/блок-ч на плече 2,5 ч, заготовка 913);
#   новое (neo, MAX, A220, E2, A350, 787): лизинг IBA 07/2026 — «at or
#     above US$400,000» у нового A320neo, MAX 8 чуть ниже → 345 тыс. EUR;
#     ТОиР 0,55 от текущего: Form 41 2025 — A20N 558, B38M 389–593 USD на
#     блок-час против 1 249 у A320ceo (первые годы — гарантия и
#     межремонтный ресурс двигателей не выбран).
#
# Сумма на борт в месяц при 300 ч: текущее 200 + 236 = 436 (Form 41 A320ceo
# 433), новое 345 + 130 = 475 (Wizz 469). Курс пересчёта — 1,16 USD/EUR,
# октябрь 2026. Ставки — ОПЕРАЦИОННЫЙ лизинг без резервов на ТОиР: резервы
# платятся сверху, но покрывают тот же ТОиР, что считается отдельной
# статьёй, — сложить их значило бы посчитать ТОиР дважды.
NEW_GENERATION = {
    "A19N", "A20N", "A21N", "B37M", "B38M", "B39M", "B3XM", "BCS1", "BCS3",
    "E290", "E295", "A339", "A338", "A359", "A35K", "B788", "B789", "B78X",
    "B77X", "B779",
}
GENERATIONS = {
    "current": {"lease_ref_eur_month": 200_000.0, "maint_factor": 1.00,
                "label": "текущее поколение, борт около 12 лет"},
    "new":     {"lease_ref_eur_month": 345_000.0, "maint_factor": 0.55,
                "label": "новое поколение, новый борт"},
}


def generation(icao: str) -> str:
    return "new" if (icao or "").upper() in NEW_GENERATION else "current"


@dataclass
class FleetEconomics:
    """Ставки одного типа у одного перевозчика."""

    icao: str
    operator: str = "*"
    lease_eur_month: float = 0.0
    monthly_hours: float = 300.0
    maint_eur_per_fh: float = 0.0
    maint_eur_per_fc: float = 0.0
    crew_eur_per_fh: float = 0.0
    crew_eur_per_fc: float = 0.0
    provenance: str = "estimated"
    note: str = ""
    # Происхождение по полю (решение 190): лизинг может быть назван
    # автором типа, а ТОиР — оставаться заготовкой. Одна метка на все
    # шесть ставок выдавала заготовку за данные, а данные — за заготовку.
    field_prov: dict = field(default_factory=dict)
    field_ref: dict = field(default_factory=dict)

    def prov(self, name: str) -> str:
        """`store` · `override` · `default` для одного поля."""
        if name in self.field_prov:
            return self.field_prov[name]
        return {"store": "store", "mixed": "override"}.get(self.provenance, "default")

    def monthly_hours_for(self, block_h: float, freq_week: float | None,
                          mode: str) -> tuple[float, str]:
        """Месячный налёт борта и пояснение, откуда он взялся.

        Развилка, которую нельзя решить за пользователя.

        `fleet_average` — борт летает и на других линиях, поэтому доля
        месячного платежа считается по ЕГО налёту, а не по налёту
        маршрута. Иначе одна машина «оплатит» себя трижды на трёх линиях.

        `dedicated` — маршруту нужен свой борт: налёт выводится из
        частоты, весь платёж несёт линия. Вопрос производителя и
        лизингодателя.

        `marginal` — борт уже оплачен и простаивает: владение в расчёт
        не входит вовсе. Вопрос эксплуатанта, куда деть свободные часы.
        """
        if mode == "dedicated":
            if not freq_week:
                raise ValueError("режим dedicated требует частоты рейсов")
            # частота задаётся в рейсах в неделю в одну сторону;
            # 4.33 — среднее число недель в месяце
            h = freq_week * block_h * 4.33
            return max(h, 1.0), (f"из частоты: {freq_week:g} рейсов в неделю · "
                                 f"{block_h:.2f} ч · 4.33")
        return self.monthly_hours, "типовой налёт перевозчика на типе"

    @property
    def maint_split(self) -> Split:
        """Разложение ТОиР как общая величина класса «час плюс цикл».

        Тот же механизм, что у топлива на втором ярусе: решение 11
        описывает не одну статью, а форму, и форма существует в проекте
        один раз (`cycles.py`). Вторая реализация того же разложения
        разошлась бы с первой так же молча, как расходились два источника
        масс до A16.
        """
        return Split(per_h=self.maint_eur_per_fh,
                     per_cycle=self.maint_eur_per_fc,
                     source=f"{self.operator}/{self.icao}")

    @property
    def crew_split(self) -> Split:
        return Split(per_h=self.crew_eur_per_fh, per_cycle=self.crew_eur_per_fc,
                     source=f"{self.operator}/{self.icao}")

    def effective_maint_per_h(self, block_h: float) -> float:
        """Полная ставка ТОиР на блок-час при этом плече.

        Именно её называют «ставкой» в отрасли, и именно с ней сравнивают.
        Почасовая составляющая по отдельности вдвое меньше, и показывать
        её как «ставку» — верный способ получить вывод, что модель
        занижает вдвое.
        """
        return self.maint_split.per_hour_at(block_h)

    def effective_crew_per_h(self, block_h: float) -> float:
        return self.crew_split.per_hour_at(block_h)

    def per_flight(self, block_h: float, freq_week: float | None = None,
                   mode: str = "fleet_average") -> dict[str, float]:
        """Три статьи на один рейс.

        Владение распределяется по доле месячного налёта, которую занял
        этот рейс. ТОиР и экипаж складываются из почасовой и поцикловой
        частей: цикл здесь — один рейс, посадка плюс взлёт.
        """
        hours, _ = self.monthly_hours_for(block_h, freq_week, mode)
        own = 0.0 if mode == "marginal" else self.lease_eur_month * block_h / hours
        return {
            "ownership": own,
            "maintenance": self.maint_eur_per_fh * block_h + self.maint_eur_per_fc,
            "crew": self.crew_eur_per_fh * block_h + self.crew_eur_per_fc,
        }


def parametric(icao: str, mtow_t: float, seats: float,
               cfg: dict | None = None) -> FleetEconomics:
    """Заготовка по массе и креслам, когда своих ставок нет."""
    gen = generation(icao)
    g = GENERATIONS[gen]
    c = {**DEFAULTS, "lease_ref_eur_month": g["lease_ref_eur_month"], **(cfg or {})}
    m = mtow_t / c["lease_ref_mtow_t"]

    lease = c["lease_ref_eur_month"] * m ** c["lease_mtow_exponent"]

    maint_h_total = (c["maint_ref_eur_h"] * g["maint_factor"]
                     * m ** c["maint_mtow_exponent"])
    # Заявленная доля цикловой части, зафиксированная на опорном плече: на
    # нём сумма обеих частей равна исходной ставке. Считает общий
    # механизм, а не эти три строки: заготовка и подбор по точкам обязаны
    # давать величину одной и той же формы, иначе замена заготовки
    # измерением незаметно поменяет смысл полей.
    ms = from_share(maint_h_total, c["maint_cycle_share"],
                    c["maint_ref_block_h"])
    cycle, per_h = ms.per_cycle, ms.per_h

    s = seats / c["crew_ref_seats"]
    crew_h = c["crew_ref_eur_h"] * s ** c["crew_seats_exponent"]

    return FleetEconomics(
        icao=icao,
        lease_eur_month=lease,
        monthly_hours=c["monthly_hours"],
        maint_eur_per_fh=per_h,
        maint_eur_per_fc=cycle,
        crew_eur_per_fh=crew_h,
        crew_eur_per_fc=c["crew_fixed_eur_cycle"] * s ** c["crew_seats_exponent"],
        provenance="estimated",
        note=f"параметрическая заготовка от массы и кресел, {g['label']}; не измерения",
    )


def fit_rates(points, prior_cycle_share: float | None = None,
              source: str = "точки эксплуатанта") -> Split:
    """Ставка по точкам «плечо → стоимость рейса».

    Появилась ради топлива, годится и здесь: канал добычи ТОиР один —
    практики, а практик называет стоимость на своём плече, а не
    раскладку. Две названные величины на разных плечах раскладываются
    однозначно, одна задаёт только уровень.
    """
    return fit(points, prior_cycle_share=prior_cycle_share, source=source)


def load(res, icao: str, as_of=None, operator: str = "*",
         mtow_t: float | None = None, seats: float | None = None):
    """Ставки из хранилища, иначе заготовка.

    Порядок: сначала ставки конкретного перевозчика, затем общие для
    типа, затем параметрика. Слой сценария применяется выше, при чтении.
    """
    fields = ("lease_eur_month", "monthly_hours", "maint_eur_per_fh",
              "maint_eur_per_fc", "crew_eur_per_fh", "crew_eur_per_fc")
    ops = [operator, "*"] if operator != "*" else ["*"]
    for op in ops:
        got = {f: res.value("fleet_economics", f"{op}/{icao}/{f}") for f in fields}
        if all(v is not None for v in got.values()):
            # Слой сценария перебивает и полный набор: значение он уже
            # подставил через `value`, здесь — только честная метка.
            fp = {f: ("override" if res.has_override("fleet_economics", f"{op}/{icao}/{f}")
                      else "store") for f in fields}
            return FleetEconomics(icao=icao, operator=op,
                                  provenance="mixed" if "override" in fp.values() else "store",
                                  note=f"ставки перевозчика {op}",
                                  field_prov=fp,
                                  field_ref={f: f"fleet_economics/{op}/{icao}/{f}" for f in fields},
                                  **got)
    if mtow_t is None or seats is None:
        raise KeyError(f"нет ставок для {icao} и нечего подставить в заготовку")

    # Заготовка, поверх которой — по полю, в таком порядке: слой сценария
    # (`--set`, поле на витрине), отдельная ставка в справочнике
    # (`fleet_economics`), ставка, названная автором своего типа в его
    # карточке (`aircraft/<тип>/fleet_<поле>`, решение 190). Задать одну
    # ставку и оставить пять заготовкой — обычный случай, а не ошибка.
    fe = parametric(icao, mtow_t, seats)
    fe.field_prov = {f: "default" for f in fields}
    touched, named = [], []
    for f in fields:
        done = False
        for op in ops:
            key = f"{op}/{icao}/{f}"
            if res.has_override("fleet_economics", key):
                was = getattr(fe, f)
                setattr(fe, f, res.value("fleet_economics", key))
                res.note_baseline("fleet_economics", key, was)
                fe.field_prov[f] = "override"
                touched.append(f)
                done = True
                break
            v = res.value("fleet_economics", key)
            if v is not None:
                setattr(fe, f, v)
                fe.field_prov[f], fe.field_ref[f] = "store", f"fleet_economics/{key}"
                named.append(f)
                done = True
                break
        if not done:
            v = res.value("aircraft", f"{icao}/fleet_{f}")
            if v is not None:
                setattr(fe, f, v)
                fe.field_prov[f], fe.field_ref[f] = "store", f"aircraft/{icao}/fleet_{f}"
                named.append(f)
    if touched or named:
        fe.provenance = "mixed"
        bits = []
        if named:
            bits.append("из справочника или карточки типа: " + ", ".join(named))
        if touched:
            bits.append("задано вручную: " + ", ".join(touched))
        fe.note = "заготовка, поверх неё " + "; ".join(bits)
    return fe
