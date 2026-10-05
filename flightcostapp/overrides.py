"""Слой сценария: ручные переопределения.

Третий слой данных из решения 33. Справочник курируется, сообщество
предлагает, сценарий принадлежит одному расчёту одного пользователя.

Два правила, из которых следует всё остальное.

**Переопределение применяется при чтении и никогда не пишется в факты.**
Утечка частного допущения в общий справочник — тот самый тихий сбой,
против которого построен весь контур. Для лизингодателя это ещё и
разглашение коммерческой тайны: один такой случай закроет продукт для
всей категории пользователей.

**Переопределённое значение видно в трассировке вместе с исходным.**
Не «ставка 1100», а «было 495 из заготовки → задано 1100 вручную».
Иначе расчёт меняется, а причина не видна — отказ того же рода, что
мёртвый валидатор.

Ключ пишется точками: `<домен>.<что именно>`. Для флотских ставок
`fleet_economics.A320.maint_eur_per_fh`, для аэронавигации
`enroute_rate.ED`, для цены топлива `fuel_price.jet_global`. Перевозчик
указывается перед типом, если нужны его ставки:
`fleet_economics.LH.A320.maint_eur_per_fh`.

**Два пространства имён, а не два флага.** Кроме переопределений фактов
через `--set` задаются значения условий начисления:
`charge_context.EDDF.noise_cat=3`. Это НЕ переопределение факта — такого
факта в хранилище нет вовсе, — а вход расчёта, наравне с загрузкой и
месяцем. Отсюда и разное обращение: у фактов значение обязано быть
числом, потому что его проверяет гейт; у условий тип и допустимость
берутся из области `DOMAINS`, той же, по которой проверяется
достижимость правил. Заводить под них отдельный флаг значило бы начать
ту самую россыпь необязательных ключей, против которой решение 24.

Звёздочки в пользовательском ключе нет намеренно. Внутри хранилища
ставки «для любого перевозчика» лежат под ключом `*/A320/...`, но
подставлять эту звёздочку в командную строку нельзя: zsh раскрывает её
как шаблон файлов и, ничего не найдя, отказывается запускать команду.
Преобразование делает `parse_set`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .charges import CONTEXT_PREFIX, parse_context_value


# Поля флотских ставок: по ним отличается запись «тип.поле» от
# «перевозчик.тип.поле» без угадывания.
FLEET_FIELDS = {"lease_eur_month", "monthly_hours", "maint_eur_per_fh",
                "maint_eur_per_fc", "crew_eur_per_fh", "crew_eur_per_fc"}


def canonical(key: str) -> str:
    """Пользовательский ключ -> внутренний адрес факта.

        fleet_economics.A320.maint_eur_per_fh   -> fleet_economics.*/A320/maint_eur_per_fh
        fleet_economics.LH.A320.maint_eur_per_fh -> fleet_economics.LH/A320/maint_eur_per_fh
        enroute_rate.ED                          -> без изменений
    """
    parts = key.split(".")
    if parts[0] != "fleet_economics" or len(parts) < 3:
        return key
    if parts[-1] not in FLEET_FIELDS:
        raise ValueError(
            f"неизвестное поле ставок {parts[-1]!r}; допустимые: "
            + ", ".join(sorted(FLEET_FIELDS)))
    field = parts[-1]
    rest = parts[1:-1]
    op, icao = ("*", rest[0]) if len(rest) == 1 else (rest[0], rest[1])
    return f"fleet_economics.{op}/{icao.upper()}/{field}"


def parse_set(items) -> dict:
    """Ключи вида `домен.что.именно=значение` из командной строки.

    Возвращает оба пространства имён вперемешку; разводит их
    `split_context` на входе в расчёт.
    """
    out: dict[str, float] = {}
    for raw in items or []:
        if "=" not in raw:
            raise ValueError(
                f"ожидалось ключ=значение, получено {raw!r}. Если в ключе была "
                f"звёздочка — уберите её и возьмите строку в кавычки: "
                f"оболочка раскрывает шаблоны до запуска")
        key, val = raw.split("=", 1)
        key = key.strip()
        # Условия начисления: значение проверяется по своей области, а не
        # приводится к числу. `stand=pier` — законное значение, и требовать
        # от него числовой формы было бы требованием к факту, которого нет.
        if key.startswith(CONTEXT_PREFIX + "."):
            parts = key.split(".")
            if len(parts) != 3:
                raise ValueError(
                    f"{key}: ожидается {CONTEXT_PREFIX}.<ИКАО>.<условие>, "
                    f"например {CONTEXT_PREFIX}.EDDF.noise_cat=3. Аэропорт "
                    f"обязателен: категория шума у каждого своя")
            out[key] = parse_context_value(parts[2], val.strip())
            continue
        try:
            out[canonical(key)] = float(
                val.replace(",", ".").replace(" ", ""))
        except ValueError as exc:
            if "неизвестное поле" in str(exc):
                raise
            raise ValueError(f"значение {val!r} для {key} — не число") from None
    return out


def split_context(overrides: dict | None) -> tuple[dict, dict]:
    """Разделить переопределения фактов и условия начисления.

    Один ключ `--set` на входе, два разных механизма на выходе. Разделение
    делается здесь, а не в командной строке, чтобы `Resolver` никогда не
    увидел нечислового значения и чтобы условие не попало в `unused()`:
    оно не факт, его никто не «спрашивает», и предупреждение о
    неиспользованном ключе было бы ложным.
    """
    facts, ctx = {}, {}
    for k, v in (overrides or {}).items():
        if not k.startswith(CONTEXT_PREFIX + "."):
            facts[k] = v
            continue
        # Опечатка в имени условия проверяется ЗДЕСЬ, потому что здесь
        # единственная точка, через которую проходят оба пути — командная
        # строка и форма. `charge_context.EDDF.nose_cat=3` формально верен,
        # разводится по префиксу и до резолвера не доходит, поэтому в
        # `unused()` не попадает и не срабатывает никогда. Решение 21 с той
        # стороны, откуда ключ задаёт человек.
        parts = k.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"{k}: ожидается {CONTEXT_PREFIX}.<ИКАО>.<условие>. "
                f"Аэропорт обязателен: категория у каждого своя")
        ctx[k] = parse_context_value(parts[2], v)
    return facts, ctx


@dataclass
class Resolver:
    """Единственная точка чтения справочных значений в расчёте.

    До неё `econ.py` дёргал хранилище в пяти местах напрямую, и вставить
    слой переопределений было некуда. Заодно здесь собирается журнал:
    что спрашивали, что ответили и откуда.
    """

    store: object
    as_of: str
    overrides: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def __post_init__(self):
        """Переопределение факта обязано быть числом.

        Не третий страж на одном пути, а первый на втором: `split_context`
        гарантирует числа только там, где ключи пришли из командной
        строки. Форма строит переопределения сама и `parse_set` не
        вызывает, а резолвер — единственное место, через которое проходят
        оба пути.
        """
        bad = {k: v for k, v in self.overrides.items()
               if isinstance(v, bool) or not isinstance(v, (int, float))}
        if bad:
            raise TypeError(
                "переопределение факта должно быть числом; не числа: "
                + ", ".join(f"{k}={v!r}" for k, v in sorted(bad.items()))
                + ". Условия начисления задаются ключом charge_context.* и "
                  "сюда не попадают")

    def value(self, domain: str, key: str, default=None):
        """Значение с учётом слоя сценария. Возраст истёкшего сохраняется."""
        path = f"{domain}.{key}"
        base, age = self.store.value_with_age(domain, key, self.as_of)
        if path in self.overrides:
            new = self.overrides[path]
            self.log.append({"path": path, "was": base, "now": new,
                             "layer": "scenario"})
            return new
        self.log.append({"path": path, "was": base, "now": base,
                         "layer": "store" if base is not None else "missing",
                         "age": age})
        return base if base is not None else default

    def has_override(self, domain: str, key: str) -> bool:
        return f"{domain}.{key}" in self.overrides

    def applied(self) -> list[dict]:
        """Сработавшие переопределения, по одному на ключ.

        Один и тот же ключ спрашивается несколько раз за расчёт — сначала
        проверкой наличия, потом чтением. В журнале это нормально, в
        отчёте пользователю — шум.
        """
        seen, out = set(), []
        for x in self.log:
            if x["layer"] == "scenario" and x["path"] not in seen:
                seen.add(x["path"])
                out.append(x)
        return out

    def note_baseline(self, domain: str, key: str, was) -> None:
        """Указать, что именно заменено, если исходное не из хранилища.

        Ставки заготовки в фактах не лежат, поэтому без этого в отчёте
        стоит «не было» — как будто пользователь задал значение на пустом
        месте, а он заменил расчётное.
        """
        path = f"{domain}.{key}"
        for x in self.log:
            if x["path"] == path and x["was"] is None:
                x["was"] = was

    def unused(self) -> list[str]:
        """Заданные, но ни разу не спрошенные ключи.

        Опечатка в имени ключа иначе проходит бесследно: значение задано,
        расчёт не изменился, причина не видна. Шестой случай подряд одного
        и того же класса отказа — поэтому проверяется явно.
        """
        asked = {x["path"] for x in self.log}
        return sorted(set(self.overrides) - asked)
