/* Shared display formatting for the forecast map. Values remain in their original units. */
(function () {
  'use strict';

  const scales = { billion: 1e9, million: 1e6, thousand: 1e3, none: 1 };
  const locales = {
    ru: { locale: 'ru-RU', billion: 'млрд', million: 'млн', thousand: 'тыс.', passengers: 'перевезённых пассажиров',
      annualPassengers: 'перевезённых пассажиров за год', segments: 'сегментов', annualSegments: 'сегментов в год',
      trips: 'перевозок', annualTrips: 'перевозок за год', inhabitants: 'человек', perCapita: 'перевозок на жителя',
      basisPoints: 'б.п.', perYear: 'в год' },
    en: { locale: 'en-US', billion: 'billion', million: 'million', thousand: 'thousand', passengers: 'passengers carried',
      annualPassengers: 'passengers carried per year', segments: 'segments', annualSegments: 'segments per year',
      trips: 'trips', annualTrips: 'trips per year', inhabitants: 'people', perCapita: 'trips per person',
      basisPoints: 'bp', perYear: 'per year' },
    de: { locale: 'de-DE', billion: 'Mrd.', million: 'Mio.', thousand: 'Tsd.', passengers: 'beförderte Fluggäste',
      annualPassengers: 'beförderte Fluggäste pro Jahr', segments: 'Segmente', annualSegments: 'Segmente pro Jahr',
      trips: 'Beförderungen', annualTrips: 'Beförderungen pro Jahr', inhabitants: 'Personen', perCapita: 'Beförderungen pro Person',
      basisPoints: 'Bp.', perYear: 'pro Jahr' },
  };

  function create(lang) {
    const labels = Object.hasOwn(locales, lang) ? locales[lang] : locales.ru;
    const decimals = new Intl.NumberFormat(labels.locale, { maximumFractionDigits: 1, useGrouping: true });
    function format(value, {signed = false} = {}) {
      if (!Number.isFinite(value)) return '';
      const magnitude = Math.abs(value);
      const sign = value < 0 ? '−' : signed && value > 0 ? '+' : '';
      if (magnitude && magnitude < 0.05) {
        const [coefficient, exponent] = magnitude.toExponential(1).split('e');
        return sign + decimals.format(Number(coefficient)) + ' × 10^(' + exponent.replace('-', '−') + ')';
      }
      return sign + decimals.format(magnitude);
    }

    const text = (display) => [display?.number, display?.unit].filter(Boolean).join(' ');
    function quantity(value, unitKey, {scale = 'auto', signed = false} = {}) {
      if (!Number.isFinite(value)) return undefined;
      if (scale === 'auto') scale = Object.keys(scales).find(key => Math.abs(value) >= scales[key]) || 'none';
      const symbol = labels[scale] || '';
      return {number: format(value / scales[scale], {signed}), scale: symbol, unit: [symbol, labels[unitKey]].filter(Boolean).join(' ')};
    }

    function percentage(value, {signed = false, perYear = false} = {}) {
      if (!Number.isFinite(value)) return undefined;
      const magnitude = Math.abs(value);
      const scale = magnitude && magnitude < 0.00005 ? 1e4 : magnitude && magnitude < 0.0005 ? 1e3 : 100;
      const symbol = scale === 1e4 ? labels.basisPoints : scale === 1e3 ? '‰' : '%';
      return {number: format(value * scale, {signed}), scale: '', unit: perYear ? symbol + ' ' + labels.perYear : symbol};
    }

    const percent = (value, options) => {
      const result = percentage(value, options);
      return result ? text(result) : '';
    };
    return {format, quantity, percentage, percent, text};
  }

  window.ForecastMapNumbers = {create};
})();
