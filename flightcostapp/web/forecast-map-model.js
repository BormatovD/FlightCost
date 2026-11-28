/* The evidence graph presents the existing scenario, without refitting or projecting it. */
(function () {
  'use strict';

  const icaoDefinition = {
    label: 'Как ИКАО считает перевезённых пассажиров',
    url: 'https://www.icao.int/sites/default/files/sp-files/sustainability/Documents/STA-Excel-Forms/English/Form_A-Instructions_en.pdf#page=3',
  };
  const caseNames = { pessimistic: 'Пессимистичный', base: 'Базовый', optimistic: 'Оптимистичный' };
  const eventTypes = [
    ['war', 'shockWar', 'Война'],
    ['pandemic', 'shockPandemic', 'Пандемия'],
    ['finance', 'shockFinance', 'Финансовый кризис'],
  ];
  // UN M49 subregion codes present in the accepted geographic partition.
  const groups = [
    ['africa', 'Африка', ['011', '014', '015', '017', '018']],
    ['america', 'Америка', ['005', '013', '021', '029']],
    ['asia', 'Азия', ['030', '034', '035', '143', '145']],
    ['europe', 'Европа', ['039', '151', '154', '155']],
    ['oceania', 'Океания', ['053', '054', '057', '061']],
  ];
  const sources = {
    icao: {
      title: 'ИКАО ARC 2024',
      url: 'https://www.icao.int/sites/default/files/annual-report-2024/World%20of%20Air%20Transport/ARC_2024_Tables_final_EN.pdf',
      detail: 'Table 1. Мировой сопоставимый ряд перевозок за 2015–2024 годы.',
    },
    weo: {
      title: 'Прогнозы ВВП МВФ',
      url: 'https://www.imf.org/en/Publications/WEO/weo-database',
      detail: 'Реальный рост ВВП в региональных сценариях чувствительности к спросу.',
    },
    population: {
      title: 'Демография ООН',
      url: 'https://population.un.org/wpp/',
      detail: 'World Population Prospects 2024, средний вариант, население на середину года.',
    },
    m49: {
      title: 'Классификация ООН M49',
      url: 'https://unstats.un.org/unsd/methodology/m49/',
      detail: 'Географическая классификация. Для этой модели используется разбивка на 22 публикуемых субрегиона.',
    },
  };
  const nonzero = n => Number.isFinite(n) && n !== 0;
  const edge = (id, label, role) => ({ id, label, role });

  function routeLinks(core, state, year, region = 'world') {
    const page = window.ForecastMapPageData || {};
    const lang = ['ru', 'en', 'de'].includes(state.lang) ? state.lang : page.lang || 'ru';
    const forecast = page.forecastUrl || '/' + lang + '/forecast';
    const network = page.networkUrl || '/outputs/forecast-leased-network/report.html';
    const query = new URLSearchParams({ year });
    if (region !== 'world') query.set('region', region);
    if (core.countries?.[region]?.[state.country]) query.set('country', state.country);
    if (state.probe === 'dev' || new URLSearchParams(window.location?.search).get('probe') === 'dev') {
      query.set('probe', 'dev');
    }
    const routeQuery = new URLSearchParams(query);
    routeQuery.set('layer', 'routes');
    if (region === 'world') routeQuery.set('route_scope', 'world');
    const sameScope = region !== 'world' && region === state.region &&
      (!state.country || query.has('country'));
    if (sameScope && /^[A-Z0-9][A-Z0-9-]{1,19}$/.test(state.hub || '')) query.set('hub', state.hub);
    query.set('lang', lang);
    return [
      { label: 'Открыть маршрутную сеть', url: network + '?' + query + '#mapSvg' },
      { label: 'Открыть рейтинг отдельных маршрутов', url: forecast + '?' + routeQuery + '#operations' },
    ];
  }

  function build(core, state = {}) {
    const lang = state.lang || window.ForecastMapPageData?.lang || 'ru';
    const numbers = window.ForecastMapNumbers.create(lang);
    const {format, quantity, percentage, percent, text} = numbers;
    const countDisplay = (n, unit = 'segments', options) => quantity(n, unit, {scale: 'none', ...options});
    const count = (n, unit, options) => text(countDisplay(n, unit, options));
    const valueRow = (label, display, unavailable) => display ? [label, text(display), display] : [label, unavailable];
    const countRow = (label, n, unit, options) => valueRow(label, countDisplay(n, unit, options));
    const signedRow = (label, n) => countRow(label, n, 'segments', {signed: true});
    const percentRow = (label, n, options) => valueRow(label, percentage(n, options), '');
    const compact = (n, unit) => quantity(n, unit);
    const line = (term, result, sign = ' ≈ ') => result ? {beforeResult: term + sign, result} : undefined;
    const math = (expression, detail, note, source, trendGuide) => ({
      expression, note,
      ...(typeof detail === 'string' ? {substitution: detail} : detail && {
        ...detail, substitution: detail.beforeResult + text(detail.result),
      }),
      source: source?.url && source.title ? {title: source.title, url: source.url} : undefined,
      ...(trendGuide && {trendGuide}),
    });
    const sumLine = (terms, total, {unit = 'segments', scale = 'none', leading} = {}) => {
      const [first = 0, ...rest] = terms;
      const printed = rest.map(value => (value < 0 ? ' − ' : ' + ') +
        quantity(Math.abs(value), unit, {scale}).number).join('');
      return line((leading || quantity(first, unit, {scale}).number) + printed, quantity(total, unit, {scale}));
    };
    const sumOf = (terms, total) => terms.length <= 5 ? sumLine(terms, total) :
      line('Сумма ' + terms.length + ' слагаемых', quantity(total, 'segments', {scale: 'none'}));
    const difference = (a, b) => format(a) + ' − ' + format(b);
    const deltaLine = (a, b, delta) => line(
      // For a visible nonzero delta, identical rounded operands would describe a different operation.
      nonzero(delta) && format(a) === format(b) && b !== 0
        ? format(b) + ' × (' + percent(delta / b, {signed: true}) + ')' : difference(a, b),
      quantity(delta, 'segments', {scale: 'none'}),
    );
    const scenario = window.BriefScenario.create(core);
    const series = core.series;
    const year = series.years.includes(Number(state.year)) ? Number(state.year)
      : series.years.includes(2031) ? 2031 : series.years[0];
    const demand = Object.hasOwn(caseNames, state.demand) ? state.demand : 'base';
    const selected = { ...state, year, demand };
    const byRegion = new Map(scenario.regions.map(region => [region, scenario.breakdown(region, year, selected)]));
    const world = scenario.breakdown('world', year, selected);
    const worldValue = scenario.forecast('world', year, selected);
    const nodes = {};
    const worldSeries = series.regions.world;
    const population = core.extras.world.population;
    const joint = core.jointForecast;
    const horizon = joint?.horizons[year];
    const releaseLabel = horizon ? 'Мировая база · ИКАО, IATA и маршруты' : 'Перевозки ИКАО · v0.2';
    const regionalMethod = horizon
      ? 'Сохраняем годовые доли субрегионов, принятые в расчёте парка по стране регистрации перевозчика. Долю умножаем на новый мировой итог. Отдельное распределение по стране вылета используется в маршрутной части мирового расчёта.'
      : 'Годовые доли субрегионов взяты из FlightCost v0.1. Базовое значение субрегиона рассчитывается из доли того же года и мирового уровня v0.2. Полного сопоставимого ряда фактов по всем субрегионам нет.';
    const provenance = window.ForecastMapPageData?.provenance || {};
    const trend = provenance.worldTrend;
    const first = trend?.observations?.[trend.startYear];
    const last = trend?.observations?.[trend.endYear];
    const factor = (last / first) ** (1 / trend?.intervals);
    const exponent = year - trend?.endYear;
    // Only explain the ordinary branch when the installed ARC edition supports it.
    // BriefScenario supplies the release value in either regime.
    const prePandemic = trend?.observations?.[2019];
    const recordedTrend = first > 0 && prePandemic > 0 && last >= prePandemic && trend.endYear - trend.startYear === trend.intervals &&
      trend.intervals > 0 && Math.abs(last * factor ** exponent - world.reference) < 0.005;
    const trendFormula = 'Перевозки в последнем году наблюдений × (годовой множитель роста)^(число лет после наблюдения).';
    const trendTerm = recordedTrend ? format(last / 1e6) + ' × (' +
      format(last / 1e6) + ' ÷ ' + format(first / 1e6) + ')^(' + exponent + ' ÷ ' + trend.intervals + ')' : undefined;
    const trendLine = line(trendTerm || 'Перевозки по выпуску v0.2',
      quantity(world.reference, 'passengers', {scale: 'million'}));
    const unverifiedTrendNote = trend ? 'Архивные наблюдения не воспроизводят этот выпуск. Показан сохранённый выход модели.' :
      'Архивные наблюдения для этой страницы недоступны. Показан сохранённый выход модели.';
    const russianYearPlural = new Intl.PluralRules('ru-RU');
    const russianYearUnit = value => ({one: 'год', few: 'года'})[russianYearPlural.select(value)] || 'лет';
    const yearUnit = value => lang === 'en' ? (value === 1 ? 'year' : 'years') :
      lang === 'de' ? (value === 1 ? 'Jahr' : 'Jahre') : russianYearUnit(value);
    const yearsApart = (symbol, meaning, end, start) =>
      ({symbol, meaning, value: format(end - start), unit: yearUnit(end - start), period: start + '–' + end});
    const guideValue = (symbol, meaning, value, signed = false) => {
      const display = quantity(value, 'passengers', {scale: 'million', signed});
      return {symbol, meaning, value: display.number, unit: display.unit, scale: display.scale};
    };
    const trendLegend = recordedTrend ? [
      {...guideValue('P₀', 'Первое наблюдение ИКАО', first), period: String(trend.startYear)},
      {...guideValue('P₁', 'Последнее наблюдение ИКАО', last), period: String(trend.endYear)},
      yearsApart('n', 'Между наблюдениями', trend.endYear, trend.startYear),
    ] : undefined;
    const trendGuide = recordedTrend ? {
      symbolic: 'P₁ × (P₁ ÷ P₀)^(h ÷ n)',
      legend: [...trendLegend, yearsApart('h', 'От последнего наблюдения до прогноза', year, trend.endYear)],
    } : undefined;
    const annualGrowthGuide = recordedTrend ? {symbolic: '(P₁ ÷ P₀)^(1 ÷ n) − 1', legend: trendLegend} : undefined;
    const inMillions = value => text(quantity(value, undefined, {scale: 'million'}));
    const trendIntro = recordedTrend ? 'Делим ' + inMillions(last) + ' (' + trend.endYear + ') на ' +
      inMillions(first) + ' (' + trend.startYear + '), чтобы узнать, во сколько раз изменились перевозки за ' + trend.intervals + ' ' +
      russianYearUnit(trend.intervals) + '.' : undefined;
    const trendNote = recordedTrend ? trendIntro + ' Степень ' + exponent + '/' + trend.intervals +
      ' переносит этот рост на ' + exponent + ' ' + russianYearUnit(exponent) + ', с ' + trend.endYear + ' по ' +
      year + ' год. Умножаем полученный множитель на объём ' + trend.endYear +
      ' года, предполагая, что среднегодовой темп сохранится (около ' + percent(factor - 1) + ').' : unverifiedTrendNote;
    const annualGrowthNote = recordedTrend ? trendIntro + ' Степень 1/' + trend.intervals +
      ' даёт множитель за один год при постоянном темпе. Вычитаем 1 и выражаем годовой рост в процентах.' :
      unverifiedTrendNote;
    const shares = provenance.regionalShares;
    const shareFor = (region, row) => {
      const record = shares?.regions?.[region];
      const part = record?.localBusiness?.[year];
      const whole = shares?.world?.[year];
      const ratio = part / whole;
      const verified = part > 0 && whole > 0 && record.m49 === series.regions[region].m49 &&
        Math.abs(world.reference * ratio - row.reference) < 0.005;
      if (horizon) return {value: row.reference / world.reference, verified: false,
        note: 'Доля из общей модели спроса и парка за выбранный год.'};
      return {value: verified ? ratio : row.reference / world.reference, verified, part, whole,
        note: verified ? 'Доля сверена со строками local_business из v0.1 за тот же год.' :
          (part > 0 && whole > 0 ? 'Архивные строки доли не воспроизводят выпуск. ' : 'Архивные строки доли недоступны. ') +
          'Доля восстановлена из сохранённых итогов v0.2.'};
    };
    const activeRegion = byRegion.has(state.focusRegion) ? state.focusRegion :
      byRegion.has(state.region) ? state.region : undefined;
    const activeRegionLabel = activeRegion && series.regions[activeRegion].ru;
    const activeShare = activeRegion && shareFor(activeRegion, byRegion.get(activeRegion));
    const regionalSource = shares?.evidence;
    const shareTerms = (share, row) => share.verified
      ? format(share.part) + ' ÷ ' + format(share.whole)
      : format(row.reference) + ' ÷ ' + format(world.reference);
    const displayShare = (value) => {
      const gap = value - 1;
      return gap !== 0 && Math.abs(gap) < 0.0005
        ? {prefix: percent(1) + (gap < 0 ? ' − ' : ' + '), result: percentage(Math.abs(gap))}
        : {prefix: '', result: percentage(value)};
    };
    const ratioLine = (trips, residents) => residents > 0
      ? line(format(trips) + ' ÷ ' + format(residents), quantity(trips / residents, 'perCapita', {scale: 'none'}))
      : undefined;
    const holdout = (row, regional) => (row.holdout?.windows || []).map(test => {
      const n = regional ? ' · ' + format(test.n) + ' пар' : '';
      return [test.year + ' · ' + test.horizon + ' лет',
        percent(test.error_pct / 100, {signed: true}) + ' · факт ' + text(compact(test.actual)) + n];
    });
    const section = (id, fields, opts = {}) => {
      const details = !opts.withoutArchivedEvidence && window.FlightCostForecastMapEvidence?.forNode?.(opts.evidence || id, {
        core, year, region: opts.region || 'world', verifiedTrend: recordedTrend, lang, numbers,
      }) || {};
      const referencesForStep = (details.sources?.length ? details.sources : fields.sources) || [];
      const directReference = opts.directReference;
      const official = (directReference ? [directReference, ...referencesForStep] : referencesForStep)
        .filter((source, i, all) => source.url && all.findIndex(item => item.url === source.url) === i);
      const inputs = [...(fields.inputs || [])];
      for (const source of (id === 'world' ? [] : official)) {
        const documentUrl = source.url.split('#')[0];
        const sourceId = 'source:' + encodeURIComponent(documentUrl);
        if (!nodes[sourceId]) {
          const trendDocument = recordedTrend && trend.evidence?.url?.split('#')[0] === documentUrl;
          nodes[sourceId] = {
            id: sourceId, kind: 'source', label: source.title,
            description: source.detail || 'Источник опубликованных данных для этого показателя.',
            math: math(source.detail || 'Проверить строки, период и единицы по документу.', trendDocument ?
              trend.startYear + ' = ' + count(first, 'passengers', {scale: 'million'}) + ' · ' +
              trend.endYear + ' = ' + count(last, 'passengers', {scale: 'million'}) : undefined,
              undefined, source),
            sources: [],
          };
        }
        const references = nodes[sourceId].sources;
        const reference = references.find(item => item.url === source.url);
        if (!reference) {
          references.push({ ...source });
        } else if (source.detail && !reference.detail?.includes(source.detail)) {
          reference.detail = [reference.detail, source.detail].filter(Boolean).join(' ');
        }
        if (!inputs.some(input => input.id === sourceId)) {
          const role = source === directReference ? 'input' : opts.sourceRole || 'context';
          inputs.push(edge(sourceId, role === 'input' ? 'Данные для расчёта' : 'Источник', role));
        }
      }
      const rows = [...(fields.rows || []), ...(details.rows || [])];
      const links = [...(fields.links || []), ...(details.links || [])];
      const display = fields.display;
      nodes[id] = {
        ...details, ...fields, id, inputs, sources: official,
        value: display && [display.number, display.scale].filter(Boolean).join(' '),
        unit: display && display.unit,
        math: fields.math || math(fields.formula || details.formula, undefined, undefined, official[0]),
        description: fields.description || details.description,
        methodNote: fields.description && details.description && details.description !== fields.description
          ? details.description : undefined,
        rows: rows.filter(([label], i) => rows.findIndex(([key]) => key === label) === i),
        links: links.filter((link, i) => links.findIndex(item => item.url === link.url) === i),
      };
    };
    const parts = [
      [releaseLabel, world.reference],
      ['Поправка спроса', world.casePax - world.reference],
      ['Поправка событий', world.shock],
      ['Инвестиционная добавка', world.investment],
    ];
    const chosenEvents = eventTypes.filter(([kind]) =>
      scenario.regions.some(region => scenario.settings(region, year, selected, kind).active));
    const trendOnly = recordedTrend && parts.slice(1).every(([, value]) => value === 0);
    const worldTrendGuide = trendGuide && {
      symbolic: trendGuide.symbolic + ' + ΔD + ΔE + ΔI',
      legend: [...trendGuide.legend,
        {...guideValue('ΔD', 'Поправка спроса по ВВП', parts[1][1], true),
          status: demand === 'base' ? 'Базовый сценарий без сдвига ВВП' : caseNames[demand] + ' сценарий'},
        {...guideValue('ΔE', 'Влияние событий', parts[2][1], true),
          status: chosenEvents.length ? chosenEvents.map(([, , label]) => label).join(' · ') : 'События не выбраны'},
        {...guideValue('ΔI', 'Прирост перевозок от инвестиций', parts[3][1], true),
          status: world.investment > 0 ? 'Ручная оценка из сценария' : 'Ручная оценка не задана'}],
    };
    const anchor = joint?.icao_anchor;
    const iata = joint?.iata_inputs.at(-1);
    const arc = joint?.arc;
    const elapsed = horizon && year - joint.forecast_year;
    const weight = joint?.weight;
    const jointTerm = horizon && format(anchor.segments / 1e6) + ' × (1 + ' +
      percent(iata.rpk_ytd_yoy_pct / 100) + ') × (1 + ' + percent(joint.growth_after_forecast_year) +
      ')^' + elapsed + ' + ' + percent(weight) + ' × (' + format(horizon.covered_route / 1e6) +
      ' − ' + format(horizon.covered_base / 1e6) + ')';
    const jointLegend = horizon && {
      symbolic: 'P × (1 + r) × (1 + g)^h + λ × (R − B)',
      legend: [
        {...guideValue('P', 'Факт ИКАО', anchor.segments), period: String(anchor.year)},
        {symbol: 'r', meaning: 'Рост RPK по IATA', value: percent(iata.rpk_ytd_yoy_pct / 100), period: iata.period},
        {symbol: 'g', meaning: 'Долгосрочный темп ИКАО', value: percent(joint.growth_after_forecast_year)},
        yearsApart('h', 'Лет после оценки IATA', year, joint.forecast_year),
        {symbol: 'λ', meaning: 'Вес маршрутов', value: percent(weight)},
        guideValue('R', 'Прогноз покрытых маршрутов', horizon.covered_route),
        guideValue('B', 'База тех же маршрутов', horizon.covered_base),
      ],
    };
    const activeDeltas = horizon ? ['ΔD', 'ΔE', 'ΔI'].map((symbol, i) => {
      const [meaning, value] = parts[i + 1];
      return {symbol, meaning, value};
    }).filter(delta => nonzero(delta.value)) : [];
    const jointWorldGuide = jointLegend && {
      symbolic: jointLegend.symbolic + activeDeltas.map(delta => ' + ' + delta.symbol).join(''),
      legend: [...jointLegend.legend, ...activeDeltas.map(delta =>
        guideValue(delta.symbol, delta.meaning, delta.value, true))],
    };
    const roundedNote = 'Темпы и объёмы в формуле округлены для показа. Итог рассчитан с полной точностью.';
    section('world', {
      label: 'Мировой прогноз', kind: 'result', display: compact(worldValue, horizon ? 'annualSegments' : 'annualPassengers'),
      description: horizon ? 'Базовый мировой прогноз складывается из оценки от ИКАО и IATA и поправки по наблюдаемым маршрутам. Сдвиг ВВП, события и инвестиции меняют выбранный сценарий.' :
        (trendOnly ? 'В выпуске v0.2 перевозки уже восстановились после пандемии. Для выбранного года модель продолжает темп ИКАО.' :
        'К мировым перевозкам по модели v0.2 прибавляются сценарные поправки по субрегионам.') +
        ' Население нужно для расчёта перевозок на жителя. По истории перевозок проверяют точность прогноза на прошлых годах.',
      links: [icaoDefinition],
      formula: 'Мировая база + поправка спроса + эффект событий + инвестиционная добавка.',
      math: horizon
        ? math(undefined, sumLine([world.reference, ...activeDeltas.map(delta => delta.value)], worldValue,
          {scale: 'million', leading: jointTerm}), roundedNote, undefined, jointWorldGuide)
        : math(undefined, sumLine(parts.map(([, value]) => value), worldValue,
          {unit: 'passengers', scale: 'million', leading: trendTerm}), trendNote,
          recordedTrend ? {title: 'ИКАО · таблица 1, стр. 1', url: trend.evidence.url} : undefined, worldTrendGuide),
      rows: [['Год', String(year)], ['Сценарий спроса', caseNames[demand]],
        ...parts.filter(([, value], i) => i === 0 || nonzero(value))
          .map(([label, value], i) => countRow(label, value, 'passengers', {signed: i !== 0})),
        countRow('Итог', worldValue, 'passengers'),
        ['Что считает ИКАО', 'На регулярных рейсах пассажира, как правило, учитывают один раз под одним номером рейса. При сочетании внутренних и международных участков его учитывают в обеих категориях.']],
      inputs: [
        edge('macroReference', releaseLabel, 'input'),
        edge('macroDemand', 'Поправка спроса', 'input'),
        edge('macroEvents', 'Поправка событий', 'input'),
        edge('macroInvestment', 'Добавка инвестиций', 'input'),
        edge('geography', 'Распределение по субрегионам', 'breakdown'),
        edge('population', 'Контекст и показатель на жителя', 'context'),
        edge('historyWorld', 'Исторические данные и проверка', 'context'),
      ],
    });
    if (horizon) {
      const icaoAnchor = {title: 'ИКАО · Safety Report 2026', url: anchor.source_url,
        detail: 'График 1, с. 5. Число пассажиров на регулярных коммерческих рейсах.'};
      const iataSource = {title: 'IATA · Air Passenger Market Analysis', url: iata.source_url,
        detail: 'Строка Total Market, накопленный рост RPK к тому же периоду предыдущего года.'};
      const arcSource = {title: 'ИКАО · ARC 2024', url: arc.source_url,
        detail: 'Таблица 1, сопоставимые мировые перевозки, число пассажиров в миллионах.'};
      const evidence = new URL(joint.evidence_url, window.location.href);
      if (/^\/(?:(?:ru|en|de)\/)?forecast$/.test(evidence.pathname)) evidence.pathname = '/' + lang + '/forecast';
      if (new URLSearchParams(window.location.search).getAll('probe').includes('dev')) {
        evidence.searchParams.set('probe', 'dev');
      }

      section('macroReference', {
        label: releaseLabel, kind: 'model', display: compact(world.reference, 'annualSegments'),
        description: 'От оценки за ' + joint.forecast_year + ' год продолжаем долгосрочный темп ИКАО. ' +
          'На выбранном горизонте добавляем взвешенное отличие маршрутного прогноза.',
        math: math(undefined, line(jointTerm, quantity(world.reference, 'segments', {scale: 'million'})),
          roundedNote, icaoAnchor, jointLegend),
        rows: [countRow('Оценка на ' + joint.forecast_year + ' год', joint.forecast_year_segments),
          countRow('Прогноз до маршрутной поправки', horizon.v02_rebased),
          signedRow('Маршрутная поправка', horizon.route_adjustment),
          countRow('Базовый прогноз на ' + year + ' год', world.reference)],
        inputs: [edge('joint:icao-anchor', 'Исходный объём', 'input'),
          edge('joint:iata', 'Рост в ' + joint.forecast_year + ' году', 'input'),
          edge('joint:icao-trend', 'Долгосрочный темп', 'input'),
          edge('joint:routes', 'Маршрутная поправка', 'input')],
      }, {withoutArchivedEvidence: true});

      section('joint:icao-anchor', {
        label: 'Перевозки ИКАО за ' + anchor.year + ' год', kind: 'input', display: compact(anchor.segments, 'annualSegments'),
        description: 'Мировой итог регулярных коммерческих рейсов самолётов с максимальной взлётной массой свыше 5 700 кг.',
        rows: [countRow('Пассажирские сегменты', anchor.segments), ['Дата публикации ИКАО', anchor.published_on]],
        sources: [icaoAnchor],
      }, {sourceRole: 'input'});

      section('joint:iata', {
        label: 'Рост RPK по IATA', kind: 'input', display: percentage(iata.rpk_ytd_yoy_pct / 100, {signed: true}),
        description: 'Накопленное изменение мировых платных пассажиро-километров с начала года по ' +
          iata.period + '. Для оценки годового числа сегментов принимаем тот же темп в оставшиеся месяцы ' +
          'и постоянную среднюю дальность сегмента.',
        math: math('Сегменты в ' + anchor.year + ' × (1 + накопленный рост RPK)',
          line(format(anchor.segments / 1e6) + ' × (1 + ' + percent(iata.rpk_ytd_yoy_pct / 100) + ')',
            quantity(joint.forecast_year_segments, 'segments', {scale: 'million'})), undefined, iataSource),
        sources: [iataSource],
      }, {sourceRole: 'input'});

      section('joint:icao-trend', {
        label: 'Долгосрочный темп ИКАО', kind: 'input',
        display: percentage(joint.growth_after_forecast_year, {perYear: true}),
        description: 'Среднегодовой темп по двум крайним наблюдениям одной таблицы ARC. ' +
          'Сохраняем его после ' + joint.forecast_year + ' года.',
        math: math('(Последнее наблюдение ÷ первое наблюдение)^(1 ÷ число лет) − 1',
          line('(' + format(arc.last / 1e6) + ' ÷ ' + format(arc.first / 1e6) + ')^(1 ÷ ' +
            (arc.endYear - arc.startYear) + ') − 1', percentage(joint.growth_after_forecast_year)), undefined, arcSource),
        rows: [countRow(String(arc.startYear), arc.first), countRow(String(arc.endYear), arc.last)],
        sources: [arcSource],
      }, {sourceRole: 'input'});

      section('joint:routes', {
        label: 'Поправка по маршрутам', kind: 'input',
        display: quantity(horizon.route_adjustment, 'annualSegments', {signed: true}),
        description: 'На покрытых линиях доля отдельного прогноза маршрута составляет ' + percent(weight) +
          '. Данные группируются по стране вылета и складываются до мира. Для непокрытого остатка действует прогноз от ИКАО и IATA.',
        math: math('Вес × (прогноз по маршрутам − базовый поток тех же маршрутов)',
          line(percent(weight) + ' × (' + format(horizon.covered_route / 1e6) + ' − ' +
            format(horizon.covered_base / 1e6) + ')', quantity(horizon.route_adjustment, 'segments', {scale: 'million', signed: true}))),
        rows: [countRow('Отдельный прогноз покрытых маршрутов', horizon.covered_route),
          countRow('Базовый поток покрытых маршрутов', horizon.covered_base),
          countRow('Базовый поток вне покрытия', horizon.uncovered),
          signedRow('Мировая поправка', horizon.route_adjustment)],
        links: [{label: 'Данные выпуска и проверка', url: evidence.href}],
        inputs: [edge('routeCoverage', 'Охват и список маршрутов', 'breakdown')],
      });
    } else {
      section('macroReference', {
        label: releaseLabel, kind: 'model', display: compact(world.reference, 'annualPassengers'),
        description: recordedTrend ? 'Модель v0.2 учитывает восстановление после известного мирового спада. В этом выпуске перевозки 2024 года уже превысили уровень 2019-го. Два наблюдения из таблицы ИКАО задают темп дальнейшего роста.'
          : 'Значение взято из опубликованного выпуска. Связь с исходным рядом в этой копии проверить не удалось.',
        formula: recordedTrend ? trendFormula : undefined,
        math: math(undefined, trendLine, trendNote, recordedTrend ? trend.evidence : undefined, trendGuide),
        rows: [countRow('Опорный год модели ' + series.issue_year, world.base, 'passengers'),
          countRow('Прогноз v0.2 на ' + year + ' год', world.reference, 'passengers')],
        links: [icaoDefinition],
        inputs: [edge('assumption:trend', 'Темп перевозок ИКАО', 'input'),
          edge('assumption:regime', 'Правило восстановления v0.2', 'input')],
      }, { sourceRole: 'input' });
    }
    const demandDelta = world.casePax - world.reference;
    section('macroDemand', {
      label: 'ВВП и спрос', kind: 'input', display: nonzero(demandDelta) ? compact(demandDelta, 'annualSegments') : undefined,
      description: 'В альтернативных сценариях модель применяет региональные множители спроса при изменении годового темпа реального ВВП на один процентный пункт. В базовом сценарии эти множители равны единице.',
      formula: 'Изменение спроса в мире = сумма разностей между сценарием и базовым прогнозом каждого субрегиона.',
      math: math('Σ (спрос по сценарию субрегиона − его базовый прогноз).',
        deltaLine(world.casePax, world.reference, demandDelta),
        'В базовом сценарии множители равны 1. В альтернативных сценариях они отражают сдвиг темпа ВВП.'),
      rows: [['Выбранный сценарий', caseNames[demand]],
        nonzero(demandDelta) ? signedRow('Вклад в мировой прогноз', demandDelta) :
          ['Вклад в мировой прогноз', count(0) + (demand === 'base' ? ' · базовый сценарий использует множитель 1' :
            ' · выбранный сценарий сохранил базовый объём')]],
      inputs: [edge('assumption:gdp', 'Допущение о сценариях ВВП', 'input')],
    }, { sourceRole: 'input' });
    section('macroEvents', {
      label: 'События', kind: 'input', display: nonzero(world.shock) ? compact(world.shock, 'annualSegments') : undefined,
      description: 'Сценарий использует охват и оценку эффекта событий для выбранных субрегионов. Несколько событий применяются последовательно. Отрицательный эффект пандемии и финансового кризиса после окончания спада ослабевает.',
      formula: 'Мировая поправка событий = сумма рассчитанных региональных поправок.',
      math: math('Δ война + Δ пандемия + Δ финансовый кризис по всем субрегионам.',
        sumLine(eventTypes.map(([event]) => world.events[event]), world.shock),
        'События применяются последовательно к потоку после предыдущих поправок.'),
      rows: [nonzero(world.shock) ? signedRow('Вклад в мировой прогноз', world.shock) :
        ['Вклад в мировой прогноз', count(0) + (chosenEvents.length ? ' · суммарный эффект равен нулю' : ' · ни одно событие не включено')]],
      inputs: [...eventTypes.map(([, id, label]) => edge(id, label, 'breakdown')),
        edge('assumption:shock', 'Правило охвата и восстановления', 'input')],
    }, { sourceRole: 'input' });
    for (const [event, id, label] of eventTypes) {
      const value = world.events[event];
      section(id, {
        label, kind: 'input', display: nonzero(value) ? compact(value, 'annualSegments') : undefined,
        description: 'Эффект рассчитывается в сценарии по историческому аналогу и охвату каждого затронутого субрегиона.',
        math: math('Σ поправок события «' + label + '» по субрегионам.',
          sumOf([...byRegion.values()].map(row => row.events[event]).filter(nonzero), value)),
        rows: [...byRegion].filter(([, row]) => nonzero(row.events[event])).map(([region, row]) =>
          signedRow(series.regions[region].ru, row.events[event])),
        inputs: [edge('assumption:shock', 'Как применяется эффект', 'input')],
      }, { sourceRole: 'input' });
    }
    section('macroInvestment', {
      label: 'Инвестиции', kind: 'input',
      display: nonzero(world.investment) ? compact(world.investment, 'annualSegments') : undefined,
      description: 'Эту поправку задают в файле автономного сценария как дополнительное число пассажирских сегментов в субрегионе к целевому году. Модель распределяет заданный прирост по годам линейно.',
      formula: 'Мировая добавка = сумма инвестиционных добавок субрегионов.',
      math: math('Σ инвестиционных добавок на горизонт.',
        sumOf([...byRegion.values()].map(row => row.investment).filter(nonzero), world.investment),
        'Ручной ввод в эквиваленте единицы модели, не измеренные рейсовые сегменты.'),
      rows: [nonzero(world.investment) ? signedRow('Вклад в мировой прогноз', world.investment) :
        ['Вклад в мировой прогноз', count(0) + ' · инвестиционная добавка не задана'],
      ...[...byRegion].filter(([, row]) => nonzero(row.investment)).map(([region, row]) =>
        signedRow(series.regions[region].ru, row.investment))],
      inputs: [edge('assumption:investment', 'Когда появляется добавка', 'input')],
    });
    const people = population?.world?.[year];
    const populationSource = window.FlightCostForecastMapEvidence?.forNode?.('population', {core, year, lang, numbers})
      ?.sources?.[0] || sources.population;
    const populationFormula = 'Население = округлить(PopTotal ООН × ' + format(1000) + '). Перевозок на жителя = прогноз ÷ население.';
    const populationNote = 'ООН WPP 2024, средний вариант на 1 июля. В выпуске FlightCost сохранена численность после пересчёта из тысяч человек.';
    section('population', {
      label: 'Население', kind: 'context', display: compact(people, 'inhabitants'),
      description: 'Население используется как знаменатель для показателя перевозок на жителя.',
      math: math(populationFormula, ratioLine(worldValue, people), populationNote, populationSource),
      rows: Number.isFinite(people) && people > 0 ?
        [countRow('Население в ' + year + ' году', people, 'inhabitants'),
          countRow('Перевозок на жителя', worldValue / people, '')] : [],
      inputs: [edge('assumption:population', 'Что означает показатель на жителя', 'context')],
    }, { sourceRole: 'input' });
    const comparison = (worldSeries.holdout?.windows || []).filter(test => test.horizon === year - series.issue_year && test.actual > 0)
      .sort((a, b) => b.year - a.year)[0];
    section('historyWorld', {
      label: 'История перевозок', kind: 'context',
      description: 'Мировые отчёты ИКАО служат для сравнения ретроспективы и прогноза. У выпусков ARC и Safety отличаются охват и степень готовности данных.' +
        (horizon ? ' Приведённые расчёты ошибки относятся к архивному выпуску v0.2.' : ''),
      math: math('Ошибка = (архивный прогноз − наблюдение ИКАО) ÷ наблюдение × 100%.', comparison ?
        line('(' + difference(comparison.forecast, comparison.actual) + ') ÷ ' + format(comparison.actual),
          percentage(comparison.error_pct / 100)) : undefined,
        comparison ? 'Пример ретропроверки на ' + comparison.year + ' год. Ряды ARC и Safety различаются по охвату.' : undefined),
      rows: holdout(worldSeries, false),
      sources: [...new Set(Object.values(worldSeries.fact_meta || {}).map(row => row.source).filter(Boolean))].map(url =>
        ({ title: url.includes('Safety') || url.includes('ICAO_SR') ? 'Отчёт ИКАО по безопасности' : 'Таблица перевозок ИКАО',
          url, detail: 'Публикация, которую использует исторический мировой ряд.' })),
    });

    const partition = groups.map(([id, label, codes]) => [id, label,
      [...byRegion.keys()].filter(region => codes.includes(series.regions[region].m49))])
      .filter(([, , members]) => members.length);
    const assigned = new Set(partition.flatMap(([, , members]) => members));
    const other = [...byRegion.keys()].filter(region => !assigned.has(region));
    if (other.length) partition.push(['other', 'Другие субрегионы', other]);
    const groupTotals = new Map(partition.map(([id, , members]) =>
      [id, members.reduce((sum, region) => sum + byRegion.get(region).total, 0)]));
    section('geography', {
      label: 'Субрегионы', kind: 'group',
      description: horizon ? regionalMethod : 'Мировые перевозки по модели v0.2 распределены по долям 22 субрегионов. Мировой итог складывается из региональных потоков после поправок.',
      math: math('Мир = ' + partition.map(([, label]) => label).join(' + '),
        sumLine([...groupTotals.values()], worldValue, {unit: 'trips', scale: 'million'}),
        'В сумму включены все субрегионы выбранного сценария. Число субрегионов — ' + byRegion.size + '.'),
      inputs: [edge('regionalReference', 'Метод распределения', 'context'),
        ...partition.map(([id, label]) => edge('group:' + id, label, 'breakdown')),
        edge('routeCoverage', 'Маршрутные данные и охват', 'context')],
      sources: [sources.m49],
    }, {withoutArchivedEvidence: Boolean(horizon)});
    section('regionalReference', {
      label: 'Как распределён прогноз', kind: 'context',
      description: regionalMethod,
      formula: 'Поток субрегиона = мировой базовый прогноз × годовая доля субрегиона.',
      math: math(horizon ? 'Мировой базовый прогноз × доля в расчёте парка.' : 'Мир v0.2 × доля субрегиона в v0.1 за тот же год.', activeShare ?
        line(activeRegionLabel + ' · ' + format(world.reference) + ' × (' +
          shareTerms(activeShare, byRegion.get(activeRegion)) + ')',
        quantity(byRegion.get(activeRegion).reference, 'segments', {scale: 'none'}))
        : undefined, activeShare?.note, activeShare?.verified ? regionalSource : undefined),
      inputs: [edge('assumption:regional-shares', 'Как определены доли', 'input')],
    }, {region: activeRegion, withoutArchivedEvidence: Boolean(horizon)});
    section('routeCoverage', {
      label: 'Маршрутные данные', kind: 'context',
      description: 'Маршрутные исследования используют аэропортовые сегменты, билетные поездки и оценки пропусков.',
      math: math('Открыть расчёт сети или рейтинг по выбранному году и географии.',
        undefined, horizon ? 'Сетевые сценарии и рейтинг линий служат отдельными расчётами. В мировую базу входит поправка по собственной выборке потоков.' : 'Числа берутся из отдельной маршрутной выборки и не складываются в этот мировой прогноз.'),
      links: routeLinks(core, state, year, activeRegion || 'world'),
    });
    section('assumption:trend', {
      label: 'Продолжение темпа ИКАО', kind: 'assumption',
      description: 'В обычном режиме v0.2 продолжает среднегодовой рост из одной сопоставимой таблицы ИКАО. При известном спаде модель применяет исторический темп к восстановленному объёму с ожидаемого года возврата.',
      formula: recordedTrend ? 'Годовой темп = (перевезено в 2024 ÷ перевезено в 2015)^(1 ÷ 9) − 1.' : undefined,
      math: math(undefined, recordedTrend ?
        line('(' + format(last / 1e6) + ' ÷ ' + format(first / 1e6) + ')^(1 ÷ ' + trend.intervals + ') − 1',
          percentage(factor - 1, {perYear: true})) : undefined, annualGrowthNote,
        recordedTrend ? trend.evidence : undefined, annualGrowthGuide),
      rows: [countRow('2015 · Table 1', worldSeries.fact[2015], 'passengers'),
        countRow('2024 · Table 1', worldSeries.fact[2024], 'passengers')],
      sources: [sources.icao],
    }, { evidence: 'macroReference', sourceRole: 'input' });
    const recoveryExample = worldSeries.holdout?.annual?.find(row => row.issue_date === '2020-06-30' && row.year === 2023);
    section('assumption:regime', {
      label: 'Восстановление после спада', kind: 'assumption',
      description: 'При известном мировом спаде v0.2 берёт объём перевозок до спада и ожидаемый год возврата из публикации, доступной на дату прогноза. До возврата модель допускает геометрическую интерполяцию от текущей оценки ИКАО. С года возврата рост продолжается от восстановленного объёма прежним темпом.',
      math: math(recordedTrend ? 'На дату этого выпуска перевозки снова превысили уровень до пандемии.' : 'Режим мирового прогноза определяется на дату выпуска.',
        recordedTrend ? line(difference(last / 1e6, prePandemic / 1e6),
          quantity(last - prePandemic, 'passengers', {scale: 'million'})) : undefined,
        recordedTrend ? 'Разница между 2024 и 2019 годами в одной таблице ИКАО. Выпуск продолжает обычный темп от наблюдения 2024 года.' : unverifiedTrendNote,
        recordedTrend ? trend.evidence : undefined),
      rows: [...[2019, 2023, 2024].filter(y => Number.isFinite(worldSeries.fact[y])).map(y => countRow(String(y), worldSeries.fact[y], 'passengers')),
        ...(Number.isFinite(recoveryExample?.v02) ? [countRow('Прогноз от 30.06.2020 на год возврата, 2023', recoveryExample.v02, 'passengers')] : [])],
      links: [
        {label: 'Правило восстановления · протокол v0.2', url: '/outputs/forecast-v02-trial/world/protocol.ru.txt'},
        {label: 'Даты и источники прогноза возврата · recovery.csv в архиве v0.2', url: '/outputs/forecast-releases/FlightCost-forecast-v0.2.zip'},
      ],
      sources: [sources.icao],
    }, { sourceRole: 'input' });
    section('assumption:gdp', {
      label: 'Сдвиг роста ВВП', kind: 'assumption',
      description: 'Для чувствительности темп роста реального ВВП каждого прогнозного года смещается на один процентный пункт вверх или вниз. Сохраняются коэффициент модели, пределы изменения, население и прочие предикторы архивной оценки.',
      formula: 'Региональный сценарий спроса = базовый поток × архивный множитель соответствующего года.',
      sources: [sources.weo],
    }, { evidence: 'macroDemand', sourceRole: 'input' });
    section('assumption:shock', {
      label: 'Охват и восстановление', kind: 'assumption',
      description: 'Эффект события применяется только к заданной доле потока. Отрицательный эффект пандемии и финансового кризиса после последнего года спада уменьшается вдвое каждые два года. Несколько событий применяются в фиксированном порядке.',
      formula: 'Поправка одного события = поток после предыдущих событий × эффект по аналогу × охват × множитель восстановления.',
    }, { evidence: 'macroEvents', sourceRole: 'input' });
    section('assumption:investment', {
      label: 'Линейный рост добавки', kind: 'assumption',
      description: 'В сценарии задаются дополнительные пассажирские сегменты, которые появятся к выбранному горизонту. Расчёт стартует после базового года.',
      formula: 'Добавка = сегменты к целевому году × доля времени от базы до цели, максимум 100%.',
    }, { evidence: 'macroInvestment' });
    section('assumption:population', {
      label: 'Население как знаменатель', kind: 'assumption',
      description: 'Оценка населения берётся на середину календарного года в среднем варианте ООН. Она применяется к тому же субрегиону и году, что и расчётный пассажиропоток.',
      formula: 'Перевозок на жителя = годовой расчётный пассажиропоток ÷ население.',
      sources: [sources.population],
    }, { evidence: 'population', sourceRole: 'input' });
    const activeShareDisplay = activeShare && displayShare(activeShare.value);
    section('assumption:regional-shares', {
      label: horizon ? 'Годовые доли расчёта парка' : 'Годовые доли FlightCost v0.1', kind: 'assumption',
      description: horizon ? regionalMethod : 'Для распределения базового уровня берём долю субрегиона из расчёта v0.1 того же года. Географические опоры v0.1 относятся к месту вылета, а часть пробелов оценена по данным о стране регистрации перевозчика. В карточке субрегиона долю можно сверить по сохранённым базовым уровням.',
      formula: 'Доля = базовый поток субрегиона ÷ базовый мировой поток того же года.',
      math: math(horizon ? 'Поток субрегиона ÷ мировой поток.' : 'local_business субрегиона ÷ local_business мира, год одинаковый.',
        activeShare ? line(activeRegionLabel + ' · ' + shareTerms(activeShare, byRegion.get(activeRegion)),
          activeShareDisplay.result, ' ≈ ' + activeShareDisplay.prefix) : undefined,
        activeShare?.note, activeShare?.verified ? regionalSource : undefined),
    }, { evidence: 'regionalReference', region: activeRegion, withoutArchivedEvidence: Boolean(horizon), directReference: horizon ? undefined : {
      title: 'Замороженный сценарий FlightCost v0.1',
      url: '/outputs/forecast-releases/FlightCost-forecast-v0.1.zip',
      detail: 'outputs/forecast-global-calibration/regional/scenario-annual.csv, поле local_business для строк мира и субрегиона. Год определяется полем target, география полем m49.',
    } });

    for (const [id, label, members] of partition) {
      section('group:' + id, {
        label, kind: 'group', description: 'Сумма сценарных прогнозов входящих субрегионов за ' + year + ' год.',
        display: compact(groupTotals.get(id), 'annualTrips'),
        math: math(label + ' = ' + members.map(region => series.regions[region].ru).join(' + '),
          sumLine(members.map(region => byRegion.get(region).total), groupTotals.get(id), {unit: 'trips', scale: 'million'}),
          'Коды субрегионов по классификации ООН M49 — ' + members.map(region => series.regions[region].m49).join(', ') + '.',
          sources.m49),
        inputs: members.map(region => edge('region:' + region, series.regions[region].ru, 'breakdown')),
      });
      for (const region of members) {
        const row = byRegion.get(region);
        const regionSeries = series.regions[region];
        const value = scenario.forecast(region, year, selected);
        const regionId = 'region:' + region;
        const share = shareFor(region, row);
        const shareDisplay = displayShare(share.value);
        const shareLabel = share.verified ? 'Доля v0.1' : 'Подразумеваемая доля';
        const regionalTerms = [row.reference, row.casePax - row.reference, row.shock, row.investment];
        const regionalTrend = share.verified ? format(world.reference) + ' × (' + shareTerms(share, row) + ')' : undefined;
        section(regionId, {
          label: regionSeries.ru, kind: 'region', display: compact(value, 'annualSegments'),
          description: 'Сценарный поток субрегиона по долям v0.1. Маршрутная проверка охватывает только пары с доступными наблюдениями.',
          formula: 'Мировой базовый прогноз × годовая доля субрегиона + поправки спроса, событий и инвестиций.',
          math: math('Мировая база × доля субрегиона + Δ спроса + Δ событий + Δ инвестиций.',
            sumLine(regionalTerms, value, {leading: regionalTrend}),
            share.note + ' Поправки заданы в эквиваленте единицы модели.',
            share.verified ? regionalSource : undefined),
          rows: [
            countRow('Базовый поток субрегиона', row.reference),
            shareDisplay.prefix ? [shareLabel, shareDisplay.prefix + text(shareDisplay.result)] :
              valueRow(shareLabel, shareDisplay.result, ''),
            ...[['Поправка спроса', row.casePax - row.reference], ['События', row.shock],
              ['Инвестиции', row.investment]].filter(([, part]) => nonzero(part))
              .map(([name, part]) => signedRow(name, part)),
            countRow('Итог', value),
          ],
          inputs: [
            edge('macroReference', releaseLabel, 'input'),
            edge('regionalReference', 'Доля субрегиона', 'input'),
            edge(regionId + ':demand', 'Региональная поправка спроса', 'input'),
            edge(regionId + ':events', 'События в субрегионе', 'input'),
            edge(regionId + ':investment', 'Инвестиции в субрегионе', 'input'),
            edge(regionId + ':population', 'Население и перевозки на жителя', 'context'),
          ],
          links: routeLinks(core, state, year, region),
        }, {region, evidence: 'regionalReference', withoutArchivedEvidence: Boolean(horizon)});

        const demandChange = row.casePax - row.reference;
        section(regionId + ':demand', {
          label: 'Поправка спроса', kind: 'input',
          display: nonzero(demandChange) ? compact(demandChange, 'annualSegments') : undefined,
          description: 'Поправка для этого субрегиона и года. Региональные множители рассчитаны на одном наборе архивных допущений.',
          formula: 'Поправка = спрос по сценарию − базовый прогноз.',
          math: math('Сценарный спрос − базовый прогноз субрегиона.',
            deltaLine(row.casePax, row.reference, demandChange)),
          rows: [['Сценарий', caseNames[demand]],
            percentRow('Изменение к базовому прогнозу', demandChange / row.reference, {signed: true})],
          inputs: [edge('assumption:gdp', 'Откуда взят множитель', 'input')],
        }, { region });

        const activeEvents = eventTypes.map(([event, , name]) =>
          [event, name, scenario.settings(region, year, selected, event)])
          .filter(([, , settings]) => settings.active);
        section(regionId + ':events', {
          label: 'События', kind: 'input',
          display: nonzero(row.shock) ? compact(row.shock, 'annualSegments') : undefined,
          description: 'Эффекты событий из настроек этого субрегиона в порядке применения модели.',
          math: math('Δ война + Δ пандемия + Δ финансовый кризис.',
            sumLine(eventTypes.map(([event]) => row.events[event]), row.shock)),
          rows: activeEvents.flatMap(([event, name, settings]) => [
            signedRow(name, row.events[event]),
            percentRow(name + ' · охват', settings.coverage / 100),
            percentRow(name + ' · эффект на шаге', scenario.impact(region, event, year, selected), {signed: true}),
            ...(event === 'war' ? [] : [[name + ' · последний год спада', String(settings.end)]]),
          ]),
          inputs: [edge('assumption:shock', 'Правило региональной поправки', 'input')],
        }, { region });

        section(regionId + ':investment', {
          label: 'Инвестиции', kind: 'input',
          display: nonzero(row.investment) ? compact(row.investment, 'annualSegments') : undefined,
          description: 'Дополнительный поток, заданный для этого субрегиона на выбранном горизонте.',
          math: math('Пользовательский ввод × min(1, доля времени от базы до цели).',
            line(format(row.investment) + ' × 1', quantity(row.investment, 'segments', {scale: 'none'})),
            'Показан целевой год. Для него доля времени равна 1.'),
          rows: nonzero(row.investment) ? [signedRow('Добавка к ' + year, row.investment)] : [],
          inputs: [edge('assumption:investment', 'Порядок начисления добавки', 'input')],
        }, { region });

        const residents = population?.[region]?.[year];
        section(regionId + ':population', {
          label: 'Население', kind: 'context', display: compact(residents, 'inhabitants'),
          description: 'Знаменатель при расчёте интенсивности перевозок в этом субрегионе и году.',
          math: math(populationFormula, ratioLine(value, residents), populationNote, populationSource),
          rows: Number.isFinite(residents) && residents > 0 ?
            [countRow('Население в ' + year + ' году', residents, 'inhabitants'),
              countRow('Перевозок на жителя', value / residents, '')] : [],
          inputs: [edge('assumption:population', 'Источник численности', 'context')],
        }, { region });
      }
    }

    return { root: 'world', nodes };
  }

  window.ForecastMapModel = { build };
})();
