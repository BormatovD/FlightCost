// Localize the report's presentation. Model identifiers, inputs, downloads and calculator drafts retain their original values.
(() => {
  'use strict';
  const messages = JSON.parse(document.getElementById('forecast-messages').textContent);
  const lang = document.documentElement.lang;
  const words = messages.text;
  const patterns = messages.patterns.map(([source, replacement]) => [new RegExp(source, 'gu'), replacement]);
  const normalize = text => text.replace(/[\s\u00a0\u202f]+/gu, ' ').trim();
  const labels = new Map(Object.entries(words).map(([key, value]) => [normalize(key), value]));
  const escape = key => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const phrases = [...labels.keys()].filter(Boolean).sort((a,b) => b.length-a.length);
  const fragment = new RegExp(phrases.map(key => {
    const left = /^[\p{L}\p{N}]/u.test(key) ? '(?<![\\p{L}\\p{N}])' : '';
    const right = /[\p{L}\p{N}]$/u.test(key) ? '(?![\\p{L}\\p{N}])' : '';
    return left + escape(key) + right;
  }).join('|'), 'gu');
  const hasRussian = /[А-Яа-яЁё]/;
  // Old report renderers use Russian number formatting. Convert only numbers still copied from their output.
  const russianNumbers = /(?<![\d.,])\d+(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?(?!\d)|(?<![\d.,])\d+,\d+(?!\d|[.,]\d)/gu;
  const memo = new Map();
  function text(value) {
    const raw = String(value ?? '');
    const source = normalize(raw);
    if (!source) return raw;
    let out = memo.get(source);
    if (out === undefined) {
      if (labels.has(source)) {
        out = labels.get(source);
      } else {
        out = source;
        if (hasRussian.test(out)) {
          for (const [pattern, translated] of patterns) out = out.replace(pattern, translated);
          if (hasRussian.test(out)) out = out.replace(fragment, match => labels.get(match));
        }
        const numbers = new Set(source.match(russianNumbers));
        if (numbers.size) out = out.replace(russianNumbers, match => {
          if (!numbers.has(match)) return match;
          let [integer, fraction] = match.split(',');
          integer = integer.replace(/\s/gu, lang === 'de' ? '.' : ',');
          return fraction === undefined ? integer : integer + (lang === 'de' ? ',' : '.') + fraction;
        });
      }
      if (memo.size >= 8192) memo.clear();
      memo.set(source, out);
    }
    return raw.slice(0,raw.length - raw.trimStart().length) + out + raw.slice(raw.trimEnd().length);
  }
  window.ForecastLanguage = {text};
  const attributes = ['title','aria-label','aria-description','aria-valuetext','placeholder','alt','label'];
  const ignored = 'script,style,noscript,textarea,code,pre,[translate="no"]';
  const writtenText = new WeakMap();
  const writtenAttributes = new WeakMap();
  function visit(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.parentElement?.closest(ignored)) return;
      const old = node.data;
      if (writtenText.get(node) === old) return;
      const translated = text(old);
      if (old !== translated) {
        // The value of an option without its own value attribute comes from its label.
        const parent = node.parentElement;
        if (parent?.tagName === 'OPTION' && !parent.hasAttribute('value')) parent.value = parent.value;
        writtenText.set(node, translated);
        node.data = translated;
      }
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || node.matches(ignored)) return;
    for (const name of attributes) {
      if (node.hasAttribute(name)) {
        const old = node.getAttribute(name);
        if (writtenAttributes.get(node)?.[name] === old) continue;
        const translated = text(old);
        if (old !== translated) {
          if (!writtenAttributes.has(node)) writtenAttributes.set(node, {});
          writtenAttributes.get(node)[name] = translated;
          node.setAttribute(name, translated);
        }
      }
    }
    for (const child of node.childNodes) visit(child);
  }
  function start() {
    const report = document.querySelector('main');
    if (!report) return;
    const observer = new MutationObserver(changes => {
      const added = new Set();
      for (const change of changes) {
        if (change.type === 'childList') for (const node of change.addedNodes) added.add(node);
        else added.add(change.target);
      }
      for (const node of added) if (node.isConnected && !added.has(node.parentNode)) visit(node);
    });
    visit(report);
    observer.observe(report, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:attributes});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();
