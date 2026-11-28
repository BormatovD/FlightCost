(() => {
  const section = document.getElementById("forecast-accuracy");
  if (!section) return;

  const color = (styles, value) => styles.getPropertyValue(value.slice(4, -1)).trim();
  const stepFor = (spread, divisions) => {
    const roughStep = spread / divisions;
    const power = 10 ** Math.floor(Math.log10(roughStep));
    const multiplier = [1, 2, 5, 10].find(n => n * power >= roughStep);
    return power * multiplier;
  };

  for (const figure of section.querySelectorAll("[data-fa-chart]")) {
    const canvas = figure.querySelector("canvas");
    const context = canvas.getContext("2d");
    if (!context) continue;
    const {lang, quarterly, observedKey, rows, series} = JSON.parse(figure.querySelector("script").textContent);
    const lastObservation = rows.findLastIndex(row => Number.isFinite(row[observedKey]));
    const format = new Intl.NumberFormat(lang, {maximumFractionDigits: 1});
    const values = series.flatMap(({key}) => rows.map(row => row[key]).filter(Number.isFinite));
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);

    function draw() {
      const {width, height} = canvas.getBoundingClientRect();
      if (width < 90 || height < 100) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);

      const styles = getComputedStyle(figure);
      const step = Math.max(0.1, stepFor(Math.max(maximum - minimum, Math.abs(maximum) * 0.05, 1), 5));
      const low = Math.floor(minimum / step) * step;
      const high = Math.max(low + step, Math.ceil(maximum / step) * step);
      context.font = `12px ${styles.getPropertyValue("--sans").trim() || "sans-serif"}`;
      const left = Math.ceil(Math.max(context.measureText(format.format(low)).width,
                                     context.measureText(format.format(high)).width)) + 12;
      const right = width - 28;
      const top = 12;
      const bottom = height - 26;
      const x = i => rows.length === 1 ? (left + right) / 2 : left + (right - left) * i / (rows.length - 1);
      const y = value => bottom - (value - low) / (high - low) * (bottom - top);

      context.strokeStyle = color(styles, "var(--line)");
      context.fillStyle = color(styles, "var(--dim)");
      context.lineWidth = 1;
      context.textAlign = "right";
      context.textBaseline = "middle";
      for (let tick = 0; tick <= Math.round((high - low) / step); tick++) {
        const value = low + tick * step;
        const position = y(value);
        context.beginPath();
        context.moveTo(left, position);
        context.lineTo(right, position);
        context.stroke();
        context.fillText(format.format(value), left - 7, position);
      }

      const labelInterval = Math.max(1, Math.ceil((rows.length - 1) / Math.max(1, Math.floor((right - left) / 55))));
      context.textAlign = "center";
      context.textBaseline = "top";
      rows.forEach(({label}, i) => {
        const last = rows.length - 1;
        if (i === last || (i % labelInterval === 0 && last - i >= labelInterval)) {
          context.fillText(label, x(i), bottom + 6);
        }
      });

      for (const {key, color: token, dash} of series) {
        context.strokeStyle = context.fillStyle = color(styles, token);
        context.lineWidth = 2;
        const firstForecast = key !== observedKey && lastObservation >= 0
          ? rows.findIndex((row, i) => i > lastObservation && Number.isFinite(row[key]))
          : -1;
        if (firstForecast >= 0) {
          context.setLineDash([3, 4]);
          context.beginPath();
          context.moveTo(x(lastObservation), y(rows[lastObservation][observedKey]));
          context.lineTo(x(firstForecast), y(rows[firstForecast][key]));
          context.stroke();
        }
        context.setLineDash(dash);
        context.beginPath();
        let contiguous = false;
        rows.forEach((row, i) => {
          const value = row[key];
          if (!Number.isFinite(value)) {
            contiguous = false;
            return;
          }
          if (contiguous && i !== firstForecast) context.lineTo(x(i), y(value));
          else context.moveTo(x(i), y(value));
          contiguous = true;
        });
        context.stroke();
        context.setLineDash([]);
        rows.forEach((row, i) => {
          if (!Number.isFinite(row[key])) return;
          const isolated = !Number.isFinite(rows[i - 1]?.[key]) && !Number.isFinite(rows[i + 1]?.[key]);
          if (quarterly || isolated) {
            context.beginPath();
            context.arc(x(i), y(row[key]), 2.5, 0, 2 * Math.PI);
            if (row.status === "preview") context.stroke();
            else context.fill();
          }
        });
      }
    }

    figure.hidden = false;
    draw();
    if (typeof ResizeObserver === "function") new ResizeObserver(draw).observe(canvas);
    else window.addEventListener("resize", draw);
    if (document.fonts) document.fonts.ready.then(draw);
  }
})();
