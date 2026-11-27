/* Localized technical appendix figures, using the same payload–range points as the tables. */
window.forecastPayloadChart = (() => {
  const chartCache = new WeakMap();
  const aircraftNames = {B752: '757-200', 'A21N-XLR': 'A321XLR', T214: 'Tu-214'};
  const labels = {
    en: {payload: 'Payload, t', range: 'Maximum range, thousands of km', base: 'Baseline', modernized: 'Moderate upgrade', deep: 'Extensive upgrade', calibration: 'Calibration point'},
    de: {payload: 'Nutzlast, t', range: 'Maximale Reichweite, Tsd. km', base: 'Ausgangsversion', modernized: 'Moderate Modernisierung', deep: 'Umfassende Modernisierung', calibration: 'Kalibrierpunkt'},
  };
  const colors = {base: '#68baff', modernized: '#d9afea', deep: '#72deb9'};

  function figure(model, family, variant, text, limits, compact) {
    const width = compact ? 415 : 720;
    const height = compact ? 300 : 400;
    const left = compact ? 44 : 54, right = width - 20;
    const top = compact ? 80 : 90, bottom = height - (compact ? 51 : 57);
    const x = km => left + km / limits.range * (right - left);
    const y = kg => bottom - kg / limits.payload * (bottom - top);
    const textAt = (xp, yp, value, anchor = 'start', size = 13, ink = '#e2e9ed') =>
      '<text x="' + xp + '" y="' + yp + '" text-anchor="' + anchor + '" fill="' + ink + '" font-size="' + size + '">' + value + '</text>';
    const line = (x1, y1, x2, y2, stroke, weight, dash = '') =>
      '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" stroke="' + stroke + '" stroke-width="' + weight + '"' + (dash ? ' stroke-dasharray="' + dash + '"' : '') + '/>';
    const title = aircraftNames[model] + ' · ' + text.payload;
    const art = ['<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="' + title + '" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" font-family="IBM Plex Sans,Arial,sans-serif"><title>' + title + '</title><rect width="100%" height="100%" fill="#15191c"/>',
      textAt(16, 27, title, 'start', compact ? 17 : 19)];
    for (const [i, key] of ['base',variant].entries()) {
      const xp = i === 0 ? 16 : compact ? 168 : 195;
      art.push(line(xp,52,xp+27,52,colors[key],2.5,i ? '8 4' : ''),textAt(xp+34,56,text[key],'start',compact ? 13 : 14));
    }
    for (let km = 0; km <= limits.range; km += 2000) {
      art.push(line(x(km),top,x(km),bottom,'#394046',0.8),textAt(x(km),bottom+19,km/1000,'middle'));
    }
    for (let kg = 0; kg <= limits.payload; kg += 5000) {
      art.push(line(left,y(kg),right,y(kg),'#394046',0.8),textAt(left-8,y(kg)+4,kg/1000,'end'));
    }
    art.push(line(left,y(20000),right,y(20000),'#99a9b4',1.2,'2 3'));
    for (const row of family.curves.filter(row => row.scenario === 'base' || row.scenario === variant)) {
      const points = row.points.map(p => [p.range_km, p.total_payload_kg]);
      const last = points[points.length-1];
      const plateau = row.verified_plateau_left_km;
      if (Number.isFinite(plateau) && plateau >= 0 && plateau < last[0]) points.push([plateau,last[1]]);
      const coords = points.map(([km,kg]) => x(km).toFixed(2) + ',' + y(kg).toFixed(2)).join(' ');
      art.push('<polyline fill="none" stroke="' + colors[row.scenario] + '" stroke-width="2.5" ' + (row.scenario === variant ? 'stroke-dasharray="8 4" ' : '') + 'points="' + coords + '"/>');
      const mission = row.points.find(p => p.total_payload_kg === 20000);
      if (mission) art.push('<circle cx="' + x(mission.range_km) + '" cy="' + y(20000) + '" r="3.5" fill="' + colors[row.scenario] + '" stroke="#15191c"/>');
    }
    const calibration = family.working_calibration;
    if (calibration) {
      const cx = x(calibration.modeled_range_km), cy = y(calibration.payload_kg);
      art.push('<rect x="' + (cx-3) + '" y="' + (cy-3) + '" width="6" height="6" transform="rotate(45 ' + cx + ' ' + cy + ')" fill="' + colors.base + '"/>',
        textAt(cx,cy-11,text.calibration,'middle',12));
    }
    art.push(textAt((left+right)/2,height-10,text.range,'middle',compact?15:16),'</svg>');
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(art.join(''));
  }

  return function forecastPayloadChart(design, model, variant, language) {
    const lang = String(language || '').split('-')[0];
    const family = design?.payload_range?.[model];
    if (!labels[lang] || !aircraftNames[model] || !['deep','modernized'].includes(variant) || !family) return null;
    if (!chartCache.has(design)) chartCache.set(design,new Map());
    const cache = chartCache.get(design), key = [lang,model,variant].join('/');
    if (!cache.has(key)) {
      const points = Object.values(design.payload_range).flatMap(f => f.curves.flatMap(c => c.points));
      const limits = {
        range: Math.ceil((Math.max(...points.map(p=>p.range_km))+125)/2000)*2000,
        payload: Math.ceil((Math.max(...points.map(p=>p.total_payload_kg))+1000)/5000)*5000,
      };
      cache.set(key,{
        desktop: figure(model,family,variant,labels[lang],limits,false),
        mobile: figure(model,family,variant,labels[lang],limits,true),
      });
    }
    return cache.get(key);
  };
})();
