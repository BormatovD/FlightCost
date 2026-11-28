/* Sources and method for the existing FlightCost v0.2 forecast. */
(function () {
  'use strict';

  const outputs = '/outputs/';
  const v02 = 'forecast-v02-trial/';
  const release = 'forecast-releases/FlightCost-forecast-v0.2.zip';
  const previous = 'forecast-releases/FlightCost-forecast-v0.1.zip';
  const replay = 'forecast-final/Сценарий потока и парка.zip';
  const shockArchive = 'forecast-regional-shocks/FlightCost-shocks-study.zip';
  const method = 'forecast-releases/FlightCost-forecast-v0.2.ru.md';
  const tables = 'forecast-final/Пассажиропоток.xlsx';
  const icaoArc = 'https://www.icao.int/sites/default/files/annual-report-2024/World%20of%20Air%20Transport/ARC_2024_Tables_final_EN.pdf';
  const safety = 'https://www.icao.int/sites/default/files/sp-files/safety/Documents/ICAO_SR_2026.pdf#page=5';
  const weo = 'https://data.imf.org/-/media/iData/External-Storage/Documents/0FA3DC49A04D446E9D69DBEB29979E1C/en/WEOOct2026all.xlsx';
  const wpp = 'https://population.un.org/wpp/assets/Excel%20Files/1_Indicator%20(Standard)/CSV_FILES/WPP2024_TotalPopulationBySex.csv.gz';
  const m49 = 'https://unstats.un.org/unsd/methodology/m49/overview/';
  const naturalEarth = 'https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/';
  const violence = 'https://ucdp.uu.se/downloads/organizedviolencecy/organizedviolencecy-261-csv.zip';
  const wdiPassengers = 'https://data.worldbank.org/indicator/IS.AIR.PSGR';
  const wdiGdp = 'https://data.worldbank.org/indicator/NY.GDP.MKTP.KD';

  const source = (title, url, detail) => ({ title, url, detail });
  const link = (label, path) => ({ label, url: outputs + encodeURI(path) });
  const arcSource = source('ИКАО · статистическое приложение ARC 2024', icaoArc,
    'Таблица 1, с. 1, строки 2015 и 2024, столбец Passengers (millions). Внутренние и международные регулярные перевозки в мире. ИКАО использует формы A и A-S и собственные оценки.');
  const safetySource = source('ИКАО · Safety Report 2026', safety,
    ({ number }) => `График 1, с. 5, столбцы пассажиров за 2021–2025 годы. Регулярные коммерческие рейсы самолётов с максимальной взлётной массой свыше ${number(5700)} кг. Уровень 2025 года предварительный.`);
  const gdpSource = source('МВФ · WEO, октябрь 2026', weo,
    'Полный Excel, лист Countries, код показателя NGDP_RPCH, страна и год. Единица — годовое процентное изменение реального ВВП. В расчёте чувствительности значения источника используются до 2031 года.');
  const wdiPassengerSource = source('Всемирный банк · WDI, перевозки авиакомпаний', wdiPassengers,
    'IS.AIR.PSGR. Число перевезённых пассажиров по стране регистрации авиакомпании. Вход исторической панели и приближение при отдельных пробелах региональной базы.');
  const wdiGdpSource = source('Всемирный банк · WDI, реальный ВВП', wdiGdp,
    'NY.GDP.MKTP.KD. Исторический ВВП в постоянных долларах США. Для расчёта используются отношения соседних годовых значений.');

  const cards = {
    macroReference: {
      description: 'В обычном режиме среднегодовой темп задают два крайних наблюдения из десятилетней таблицы одного выпуска ИКАО. В текущем расчёте это 2015 и 2024 годы.',
      formula: ({ number }) => `Мир в году Y = ${number(4669000000)} × (${number(4669)} ÷ ${number(3567)})^((Y − 2024) ÷ 9).`,
      rows: [
        ['Исходные строки', ({ number }) => `2015 — ${number(3567)} млн, 2024 — ${number(4669)} млн перевезённых пассажиров`],
        ['Геометрический темп', ({ percentage }) => percentage((4669 / 3567) ** (1 / 9) - 1, {signed: true, perYear: true})],
        ['Сверка в архиве v0.2', 'lines/forward/icao-arc-2024-table-1.csv и coordinates.csv, m49=001, model=v0.2'],
        ['Допущение выпуска', 'После 2024 года сохраняется один темп. Уровень 2026 года расчётный.'],
      ],
      sources: [arcSource],
      links: [link('Метод расчёта мирового ряда', v02 + 'lines/forward/README.ru.md'), link('Архив v0.2 с таблицей и координатами', release)],
    },
    historyWorld: {
      description: 'На историческом графике периоды 2015–2020 и 2021–2025 показаны по двум выпускам ИКАО с разным охватом. Эти наблюдения помогают сверить прогноз. Мировую опорную линию продолжает только сопоставимая таблица ARC 2024.',
      rows: [
        ['Охват исторического графика', 'ARC 2024 за 2015–2020 годы, Safety Report 2026 за 2021–2025 годы'],
        ['Различие охвата', ({ number }) => `В 2024 году ARC даёт ${number(4669)} млн, Safety даёт ${number(4528)} млн. Оценка Safety за 2025 год — ${number(4950)} млн.`],
        ['Ретропроверка', 'Цели 2019 и 2025, по три горизонта. Решения реконструированы на 30 июня. Даты редакции PDF местами служат приближением к дате доступности.'],
        ['Допуск автора', ({ percent }) => `±${percent(0.05)} по мировым сегментам. В допуске 3 из 6 окон. Для других трёх в принятом выпуске отдельно приведено сравнение в RPK.`],
        ['Файлы для сверки', 'lines/history_world/annual.csv, inputs.csv, icao-editions.csv и verification.json в архиве v0.2'],
      ],
      sources: [arcSource, safetySource],
      links: [link('Исторический ряд и отсечки', v02 + 'lines/history_world/README.ru.md'),
        link('Критерии принятия выпуска', method), link('Таблица контрольных окон', v02 + 'decision.csv'),
        link('Архив исторических входов', release)],
    },
    regionalReference: {
      description: 'Для каждого года FlightCost берёт долю субрегиона из замороженного сценария local_business v0.1 и умножает её на новый мировой уровень v0.2. Унаследованная база сочетает наблюдения по месту вылета, пересчитанные аэропортовые итоги и распределение недостающего объёма по WDI страны регистрации перевозчика. Региональная доля остаётся расчётной.',
      formula: 'Субрегион v0.2 = Мир v0.2 × (local_business субрегиона v0.1 ÷ local_business мира v0.1), все три числа за один год.',
      rows: [
        ['Источник доли', 'Архив v0.1, outputs/forecast-global-calibration/regional/scenario-annual.csv'],
        ['Строка и поле', 'target = год, m49 = код территории или 001 для мира, значение local_business в сегментах'],
        ['Состав базы v0.1 за 2025', ({ percent }) => `${percent(0.5576)} — направленные наблюдения 2025 года, ${percent(0.2064)} — пересчитанные аэропортовые итоги трёх стран, ${percent(0.0416)} — доступные части за 2024 год, ${percent(0.1944)} — расчётный остаток.`],
        ['Исходный сценарий v0.1', ({ percent }) => `Для стран с пригодным рядом местный темп и рост ВВП имеют веса по ${percent(0.5)}. При нехватке наблюдений используется ВВП. Деловой слой сохраняет допущения о доле ${percent(0.1926)} и годовом росте ${percent(0.01)}.`],
        ['Проверка покрытия', 'Ретропроверка субрегионов охватывает доступные выборки пар. Точность оценки полного субрегионального потока не установлена.'],
      ],
      sources: [wdiPassengerSource, gdpSource],
      links: [link('Замороженный сценарий v0.1', previous), link('Распределение мира v0.2', v02 + 'lines/forward/README.ru.md'),
        link('Состав выборок исторической проверки', v02 + 'lines/history_regions/README.ru.md'),
        link('Таблицы пассажиропотока', tables)],
    },
    macroDemand: {
      description: 'Пессимистичный и оптимистичный варианты сдвигают годовой рост реального ВВП каждой страны на −1 и +1 процентный пункт. Сохранённая страновая модель переводит этот сдвиг в региональные множители спроса. В базовом варианте множители равны единице.',
      formula: 'Поправка субрегиона = его базовый поток v0.2 × (множитель спроса − 1). Мировая поправка = сумма региональных поправок.',
      rows: [
        ['Темпы ВВП', 'МВФ WEO октября 2026, NGDP_RPCH, 2027–2031. При пропусках — медиана субрегиона или исходный тренд.'],
        ['Горизонт 2032–2036', 'Продолжается средний годовой логарифмический темп страны за 2027–2031 годы. Затем к арифметическому темпу прибавляется сценарный сдвиг.'],
        ['Коэффициент старой модели', ({ number }) => `Около ${number(0.499611)} при логарифмическом изменении реального ВВП на человека. Вход ограничен ${number(2.5)}-м и ${number(97.5)}-м процентилями обучения. Параметры населения, потребления и вылетов при сравнении сохранены.`],
        ['Историческая выборка', ({ number }) => `${number(3839)} страновых годовых изменений за 1991–2023 годы с заполненными четырьмя входами и рядом перевозок.`],
        ['Файлы для сверки', 'Сценарий потока и парка.zip, inputs.json → extras.world.demandFactors, provenance/fleet_trajectory.py'],
        ['Смысл допущения', 'Сценарий чувствительности к росту ВВП. Вероятности пессимистичного и оптимистичного исходов не оценивались.'],
      ],
      sources: [gdpSource, wdiGdpSource, wdiPassengerSource],
      links: [link('Годовые множители и воспроизведение', replay)],
    },
    population: {
      description: 'ООН оценивает население мира и 22 субрегионов на середину года. Демография также входила в страновую модель, из которой унаследованы множители чувствительности к ВВП.',
      formula: 'Перевозок на жителя = расчётный пассажиропоток за год ÷ оценка населения на 1 июля.',
      rows: [
        ['Фильтр WPP 2024', 'Variant = Medium, LocTypeName = World, Subregion или Geographic region, Time = нужный год'],
        ['Единица и дата', ({ number }) => `PopTotal в тысячах человек × ${number(1000)}, округление до человека, оценка на 1 июля`],
        ['Смысл показателя', 'Годовой пассажиропоток в расчёте на одного жителя. На значение влияют поездки посетителей и повторные перелёты одного человека.'],
        ['Файл для сверки', 'Сценарий потока и парка.zip, inputs.json → extras.world.population'],
      ],
      sources: [source('ООН · World Population Prospects 2024', wpp,
        'Total Population by Sex. Средний вариант, полный региональный ряд PopTotal на середину года.')],
      links: [link('Исходные численности в открытом архиве', replay)],
    },
    geography: {
      description: 'Разбивка определяет, какие страны и территории входят в каждый из 22 субрегионов и куда попадают сценарные поправки. Геометрия Natural Earth используется для рисования карты. Мировой уровень до распределения берётся из общей линии ИКАО.',
      rows: [
        ['Ключ классификации', 'ISO-alpha2 страны или территории. Берётся Intermediate Region, если заполнен, иначе Sub-region.'],
        ['Покрытие справочника', '249 стран и территорий в 22 субрегионах. Код мира 001.'],
        ['Уточнения FlightCost', 'Тайвань (TW) отнесён к Восточной Азии, Косово (XK) — к Южной Европе отдельными строками атласа.'],
        ['Поля для сверки', 'regions.json → countryRegions. В координатах выпуска m49 — трёхзначный код с ведущими нулями.'],
      ],
      sources: [source('ООН · географии M49', m49, 'Статистическая классификация, поля Sub-region, Intermediate Region, ISO-alpha2. Коды M49 сохраняют ведущие нули.'),
        source('Natural Earth · границы стран', naturalEarth, 'Слой Admin 0, масштаб 1:110 млн. Координаты используются для иллюстрации карты.')],
      links: [link('Состав субрегионов и привязка стран', 'forecast-route-map/regions.json'), link('Годовые региональные координаты', release)],
    },
    macroEvents: {
      description: 'Пользователь включает событие и задаёт охват субрегиона. Эффект берётся из исторических аналогов и применяется к потоку после поправки спроса. Если включено несколько событий, каждое применяется к потоку, оставшемуся после предыдущего.',
      formula: 'Изменение от события = текущий поток × охват × (exp(β) − 1) × коэффициент остаточного спада.',
      rows: [
        ['Охват сценария', ({ percent }) => `${[0.1, 0.25, 0.5, 0.75, 1].map(value => percent(value)).join(' / ')}. Без отдельной настройки включённое событие имеет охват ${percent(0.25)}.`],
        ['Оценка β', 'Местная медиана логарифмического отклонения от тренда и общая медиана с условным весом четырёх наблюдений. При отсутствии местных примеров используется общая медиана.'],
        ['Очередность', 'Война, пандемия, финансовый кризис. Мировой эффект складывается из поправок по субрегионам.'],
        ['Допущение восстановления', 'После заданного последнего года спада отрицательный эффект пандемии или финансового кризиса уменьшается вдвое за каждые два года. Для войны правило не задано.'],
        ['Пятилетняя проверка по времени', ({ percent }) => `WAPE около ${percent(0.2912)} у базовой макромодели и ${percent(0.2915)} с общей событийной поправкой. Поправка не улучшила результат. Даты событий были известны.`],
        ['Файл коэффициентов', 'Сценарий потока и парка.zip, inputs.json → extras.world.shocks, поля beta, n и raw'],
      ],
      sources: [wdiPassengerSource, wdiGdpSource],
      links: [link('Коэффициенты этой версии и повтор расчёта', replay)],
    },
    macroInvestment: {
      description: 'Источник добавки — ручная оценка пассажиропотока в файле автономного сценария. При пустых настройках добавка равна нулю. Данные об открытии объектов и их мощности изучаются отдельно.',
      formula: 'Добавка в году Y = ввод × min(1, (Y − 2026) ÷ (горизонт − 2026)).',
      rows: [
        ['Поле автономного сценария', 'state.scenarios[горизонт][субрегион].investment. Принимается положительное конечное число.'],
        ['Единица', 'Дополнительные пассажирские сегменты за год'],
        ['Порядок', 'Прибавляется после сценария спроса и событий. Мировой итог получает сумму региональных добавок.'],
        ['Авторское допущение', 'Линейное нарастание с 2026 года. Эффект проекта вводит пользователь.'],
      ],
      links: [link('Формат сценария и пример ввода', replay)],
    },
  };

  const shockStudy = link('Исторические эксперименты и их ограничения', shockArchive);
  const definitions = {
    shockWar: {
      kind: 'war',
      description: 'Калибровка использует начало эпизодов, найденных по порогу боевых потерь UCDP. Из отклонения трафика от предыдущего тренда вычитается медиана отклонений стран без начала конфликта в том же году. Значение β применяется только к охвату, заданному в сценарии.',
      rows: [
        ['Строки UCDP', ({ number }) => `OrganizedViolenceCYDataSet26_1.csv, country, year, sb_total_deaths_best. В 1999–2023 годах не менее ${number(1000)} боевых смертей за год и менее ${number(1000)} в предшествующем году.`],
        ['Фильтр калибровки', '2009 и 2020 годы исключены. Требуются положительные ряды для соседних лет, предшествующий тренд и как минимум пять стран сравнения.'],
        ['Обучающая выборка', '37 наблюдений по 24 странам в 19 разных годах'],
        ['Дальнейшая траектория', 'Заданный эффект применяется без правила автоматического ослабления.'],
      ],
      sources: [source('Уппсальский университет · UCDP OrganizedViolenceCY 26.1', violence,
        'Страновые годовые записи, поле sb_total_deaths_best. Порог и окно выборки заданы FlightCost.'), wdiPassengerSource, wdiGdpSource],
    },
    shockPandemic: {
      kind: 'pandemic',
      description: 'Пандемийная поправка основана на отклонении перевозок зарегистрированных авиакомпаний в 2020 году от предшествующего тренда. Это один глобальный эпизод. Его перенос на будущую пандемию задаёт сценарное допущение.',
      rows: [
        ['Годы наблюдения', '2020 к 2019 году, по странам с данными WDI о пассажирах, реальном ВВП и предыдущем тренде'],
        ['Предшествующий тренд', 'Медиана доступных логарифмических годовых изменений за семь лет до события. Требуются не менее трёх изменений.'],
        ['Обучающая выборка', '141 страна, один год'],
        ['Дальнейшая траектория', 'После последнего заданного года спада отрицательный эффект уменьшается вдвое за два года.'],
      ],
      sources: [wdiPassengerSource, wdiGdpSource],
    },
    shockFinance: {
      kind: 'finance',
      description: 'Поправка основана на отклонении фактического изменения перевозок в 2009 году от предшествующего тренда. В выборке один глобальный финансовый эпизод. Охват и срок восстановления в будущем задаёт пользователь.',
      rows: [
        ['Годы наблюдения', '2009 к 2008 году, по странам с данными WDI о пассажирах, реальном ВВП и предыдущем тренде'],
        ['Предшествующий тренд', 'Медиана доступных логарифмических годовых изменений за семь лет до события. Требуются не менее трёх изменений.'],
        ['Обучающая выборка', '136 стран, один год'],
        ['Дальнейшая траектория', 'После последнего заданного года спада отрицательный эффект уменьшается вдвое за два года.'],
      ],
      sources: [wdiPassengerSource, wdiGdpSource],
    },
  };

  function regionalRows({ core, region, year }, numbers) {
    const row = core?.series?.regions?.[region];
    const regional = row?.forecast?.[year];
    const world = core?.series?.regions?.world?.forecast?.[year];
    if (region === 'world' || !Number.isFinite(regional) || !(world > 0)) return [];
    const share = numbers.percentage(regional / world);
    return [
      ['Территория и год для сверки', row.ru + ' · M49 ' + row.m49 + ' · ' + year],
      ['Проверка по опубликованным итогам v0.2', numbers.text(share), share],
    ];
  }

  function eventRows(definition, { core, region }, { number, percent }) {
    const fit = core?.extras?.world?.shocks?.[definition.kind]?.[region];
    if (!fit || !Number.isFinite(fit.beta)) return [];
    return [
      [`Региональный коэффициент β × ${number(10000)}`, `${number(fit.beta * 10000)} · местных наблюдений ${number(fit.n)}`],
      ['Оценка при полном охвате', `${percent(Math.expm1(fit.beta))} до ослабления эффекта`],
    ];
  }

  function forNode(id, context = {}) {
    const definition = Object.hasOwn(definitions, id) ? definitions[id] : undefined;
    const card = definition || (Object.hasOwn(cards, id) ? cards[id] : undefined);
    if (!card) return {};
    const numbers = context.numbers || window.ForecastMapNumbers.create(context.lang || window.ForecastMapPageData?.lang);
    const formats = {number: numbers.format, percent: numbers.percent, percentage: numbers.percentage};
    const format = text => typeof text === 'function' ? text(formats) : text;
    const sources = card.sources?.map(item => ({ ...item, detail: format(item.detail) }));
    if (id === 'macroReference' && !context.verifiedTrend) {
      return { sources, links: card.links };
    }
    const rows = card.rows.map(([label, value]) => {
      const cell = format(value);
      return typeof cell === 'string' ? [label, cell] : [label, numbers.text(cell), cell];
    });
    if (definition) rows.push(...eventRows(definition, context, formats));
    if (id === 'regionalReference') rows.push(...regionalRows(context, numbers));
    return { description: card.description, formula: format(card.formula), rows, sources,
      links: definition ? [link('Коэффициенты этой версии', replay), shockStudy] : card.links };
  }

  window.FlightCostForecastMapEvidence = { forNode };
})();
