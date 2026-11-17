// Fabrique de graphiques Chart.js partageant le thème de l'application.
/* global Chart */

import { fmtNum, fmtShortDate } from "./format.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export const colors = () => ({
  value: css("--c-value"), ma7: css("--c-ma7"), ma28: css("--c-ma28"), baseline: css("--c-baseline"),
  band: css("--c-band"), text: css("--muted"), grid: css("--grid"),
  zone: {
    under: css("--c-zone-under"), optimal: css("--c-zone-optimal"),
    caution: css("--c-zone-caution"), risk: css("--c-zone-risk"),
  },
});

// Plugin : bandes horizontales colorées (zones du ratio aiguë / chronique).
const zonesPlugin = {
  id: "zones",
  beforeDatasetsDraw(chart, _args, options) {
    const zones = options?.items;
    if (!zones?.length) return;
    const { ctx, chartArea: area, scales: { y } } = chart;
    ctx.save();
    for (const z of zones) {
      const top = y.getPixelForValue(z.max ?? y.max);
      const bottom = y.getPixelForValue(z.min);
      ctx.fillStyle = z.color;
      ctx.fillRect(area.left, Math.max(top, area.top), area.right - area.left,
        Math.min(bottom, area.bottom) - Math.max(top, area.top));
    }
    ctx.restore();
  },
};

// Plugin : repères temporels des graphiques intra-journaliers (jour sélectionné, nuits,
// activités, minuits). Les instants sont en ms epoch, sur un axe X linéaire.
const markersPlugin = {
  id: "markers",
  beforeDatasetsDraw(chart, _args, options) {
    const { ctx, chartArea: area, scales: { x } } = chart;
    if (!x || !options) return;
    const px = (t) => Math.min(area.right, Math.max(area.left, x.getPixelForValue(t)));
    ctx.save();
    for (const s of options.spans ?? []) {
      const [l, r] = [px(s.start), px(s.end)];
      if (r - l < 0.5) continue;
      ctx.fillStyle = s.color;
      ctx.fillRect(l, area.top, r - l, area.bottom - area.top);
    }
    ctx.strokeStyle = options.lineColor ?? "rgba(128,128,128,.5)";
    ctx.setLineDash([4, 4]);
    for (const t of options.lines ?? []) {
      if (t <= x.min || t >= x.max) continue;
      const p = Math.round(x.getPixelForValue(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(p, area.top); ctx.lineTo(p, area.bottom); ctx.stroke();
    }
    ctx.restore();
  },
};

// --- Glisser pour se déplacer, molette pour zoomer --------------------------------
//
// Agit sur l'axe X (linéaire) uniquement, entre les bornes ``bounds`` du graphique :
// indices de date (graphiques journaliers) ou ms epoch (intra-journaliers). Les bornes
// restent fractionnaires : le déplacement suit la souris au pixel près.
// Double-clic : retour à la vue complète.

const ZOOM_STEP = 1.25;
const DRAG_THRESHOLD_PX = 4;


function applyView(chart, view, { notify = true } = {}) {
  const st = chart.$panZoom;
  const opts = st.opts;
  const full = opts.bounds;
  const fullWidth = full.max - full.min;
  let { min, max } = view ?? full;
  let width = Math.max(max - min, Math.min(opts.minRange ?? 4, fullWidth));
  if (width >= fullWidth) {
    st.view = null;
    chart.options.scales.x.min = full.min;
    chart.options.scales.x.max = full.max;
  } else {
    const center = (min + max) / 2;
    min = Math.min(Math.max(center - width / 2, full.min), full.max - width);
    max = min + width;
    st.view = { min, max };
    chart.options.scales.x.min = min;
    chart.options.scales.x.max = max;
  }
  chart.update("none");
  if (notify) opts.onChange?.(st.view);
}

/** Fixe la plage visible de l'axe X sans déclencher onChange (synchronisation). */
export function setXRange(chart, view) {
  if (chart.$panZoom) applyView(chart, view, { notify: false });
}

const panZoomPlugin = {
  id: "panZoom",
  defaults: { enabled: false },
  afterInit(chart, _args, opts) {
    if (!opts.enabled || !opts.bounds) return;
    const canvas = chart.canvas;
    const st = { opts, view: null, drag: null, dragged: false };
    chart.$panZoom = st;
    const current = () => st.view ?? opts.bounds;
    // Position dans le canevas (en pixels CSS, comme chartArea).
    const pos = (e) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const inArea = (e) => {
      const a = chart.chartArea;
      const { x, y } = pos(e);
      return a && x >= a.left && x <= a.right && y >= a.top && y <= a.bottom;
    };

    const onWheel = (e) => {
      if (!inArea(e)) return;
      e.preventDefault();
      const { min, max } = current();
      const a = chart.chartArea;
      const ratio = (pos(e).x - a.left) / (a.right - a.left);
      const center = min + ratio * (max - min);
      const factor = e.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
      applyView(chart, { min: center - (center - min) * factor, max: center + (max - center) * factor });
    };
    const onDown = (e) => {
      if (e.button !== 0 || !inArea(e)) return;
      st.drag = { x: e.clientX, ...current(), id: e.pointerId };
      st.dragged = false;
    };
    const onMove = (e) => {
      const d = st.drag;
      if (!d || e.pointerId !== d.id) return;
      const dx = e.clientX - d.x;
      if (!st.dragged && Math.abs(dx) < DRAG_THRESHOLD_PX) return;
      if (!st.dragged) {
        st.dragged = true;
        canvas.setPointerCapture?.(e.pointerId);
        canvas.style.cursor = "grabbing";
        chart.tooltip?.setActiveElements([], { x: 0, y: 0 });
      }
      const a = chart.chartArea;
      const shift = (-dx / (a.right - a.left)) * (d.max - d.min);
      applyView(chart, { min: d.min + shift, max: d.max + shift });
    };
    const onUp = (e) => {
      if (!st.drag || e.pointerId !== st.drag.id) return;
      st.drag = null;
      canvas.style.cursor = "";
      // Le « click » qui suit un glissement ne doit pas ouvrir un point.
      if (st.dragged) setTimeout(() => { st.dragged = false; }, 0);
    };
    const onDouble = (e) => { if (inArea(e)) applyView(chart, null); };

    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
    canvas.addEventListener("dblclick", onDouble);
    canvas.style.touchAction = "pan-y";   // défilement vertical de la page conservé sur écran tactile
    st.detach = () => {
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      canvas.removeEventListener("dblclick", onDouble);
    };
  },
  afterDestroy(chart) { chart.$panZoom?.detach?.(); },
};

let configured = false;
function configure() {
  if (configured) return;
  const c = colors();
  Chart.defaults.color = c.text;
  Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
  Chart.defaults.borderColor = c.grid;
  Chart.defaults.maintainAspectRatio = false;
  // Animations désactivées : inutiles pour un tableau de bord, et Chart.js lève
  // « this._fn is not a function » quand une propriété animée part d'une valeur
  // qu'il ne sait pas interpoler. Sans animation, aucun objet Animation n'est créé.
  Chart.defaults.animation = false;
  Chart.register(zonesPlugin, markersPlugin, panZoomPlugin);
  configured = true;
}

// --- Graduations calendaires de l'axe X ------------------------------------------
//
// L'échelle est choisie d'après l'étendue des dates affichées (et non d'après le
// bouton de période), pour s'appliquer aussi aux séries hebdomadaires :
//   ≤ 45 jours   : étiquettes jour par jour, espacées automatiquement (« 17.11 ») ;
//   ≤ 135 jours  : le 1er et le 15 de chaque mois (« 01.09 », « 15.09 ») ;
//   ≤ 400 jours  : le début de chaque mois (« 01.26 » pour janvier 2026) ;
//   au-delà      : le début de chaque année (« 2026 ») dès que l'étendue couvre au moins
//                  3 changements d'année, sinon le début des mois (un mois sur n, ≤ 12 étiquettes).
// Une étiquette est placée sur le premier point qui franchit la limite ; le premier point
// de la série n'est étiqueté que s'il tombe exactement sur une limite.

const DAY_MS = 86_400_000;
const pad = (n) => String(n).padStart(2, "0");
const parts = (iso) => ({ y: +iso.slice(0, 4), m: +iso.slice(5, 7), d: +iso.slice(8, 10) });

const SCALES = {
  halfMonth: {
    key: ({ y, m, d }) => `${y}-${m}-${d < 15 ? 0 : 1}`,
    exact: ({ d }) => d === 1 || d === 15,
    label: ({ m, d }) => `${pad(d)}.${pad(m)}`,
  },
  month: {
    key: ({ y, m }) => `${y}-${m}`,
    exact: ({ d }) => d === 1,
    label: ({ y, m }) => `${pad(m)}.${String(y).slice(2)}`,
  },
  year: {
    key: ({ y }) => `${y}`,
    exact: ({ m, d }) => m === 1 && d === 1,
    label: ({ y }) => `${y}`,
  },
};

/** Renvoie Map(index → étiquette), ou null pour l'espacement automatique. */
export function calendarTicks(dates) {
  if (dates.length < 2) return null;
  const span = (Date.parse(dates[dates.length - 1]) - Date.parse(dates[0])) / DAY_MS;
  if (span <= 45) return null;

  let scale;
  let keep = () => true;
  if (span <= 135) {
    scale = SCALES.halfMonth;
  } else if (span <= 400) {
    scale = SCALES.month;
  } else {
    const first = parts(dates[0]).y;
    const last = parts(dates[dates.length - 1]).y;
    if (last - first >= 3) {
      scale = SCALES.year;
      const step = Math.ceil((last - first + 1) / 12);          // ≤ 12 étiquettes
      keep = ({ y }) => y % step === 0;
    } else {
      scale = SCALES.month;
      const step = Math.ceil(span / 30.4 / 12);                  // ≤ 12 étiquettes
      keep = ({ y, m }) => (y * 12 + m - 1) % step === 0;
    }
  }

  const ticks = new Map();
  let previous = null;
  dates.forEach((iso, i) => {
    const p = parts(iso);
    const key = scale.key(p);
    const crosses = previous === null ? scale.exact(p) : key !== previous;
    if (crosses && keep(p)) ticks.set(i, scale.label(p));
    previous = key;
  });
  return ticks;
}

/**
 * Axe X par dates, continu : chaque date est placée à son indice (0, 1, 2…). Un axe
 * linéaire accepte des bornes fractionnaires, ce qui rend le glisser et le zoom fluides
 * (un axe par catégories saute d'une date à l'autre). Les graduations sont recalculées
 * sur la plage visible : passer de 1 an à 3 semaines ramène des étiquettes journalières.
 */
function dateAxis(dates, bounds) {
  let cacheKey = null;
  let labels = new Map();
  const plan = (scale) => {
    const lo = Math.max(0, Math.ceil(scale.min));
    const hi = Math.min(dates.length - 1, Math.floor(scale.max));
    const key = `${lo}:${hi}`;
    if (key !== cacheKey) {
      cacheKey = key;
      const visible = dates.slice(lo, hi + 1);
      const ticks = calendarTicks(visible);
      labels = new Map();
      if (ticks) {
        ticks.forEach((label, i) => labels.set(lo + i, label));
      } else {
        const step = Math.max(1, Math.ceil(visible.length / 8));
        for (let i = 0; i < visible.length; i += step) labels.set(lo + i, fmtShortDate(visible[i]));
      }
    }
    return labels;
  };
  return {
    type: "linear",
    min: bounds.min,
    max: bounds.max,
    afterBuildTicks: (scale) => { scale.ticks = [...plan(scale).keys()].map((value) => ({ value })); },
    ticks: { autoSkip: false, maxRotation: 0, callback: (value) => labels.get(value) ?? "" },
    grid: { display: true },
  };
}

/** Graphique temporel. ``series`` = [{label, data, color, kind: line|bar|band, dashed, fillTo, yAxisID, points}] */
export function timeChart(canvas, dates, series, { decimals = 0, zones = null, y = {}, y2 = null, onPointClick = null } = {}) {
  configure();
  const datasets = series.map((s) => {
    const base = {
      label: s.label, data: s.data.map((v, i) => ({ x: i, y: v ?? null })), borderColor: s.color, backgroundColor: s.color,
      yAxisID: s.yAxisID ?? "y", spanGaps: s.spanGaps ?? true, order: s.order ?? 0,
      hideInLegend: s.hideInLegend ?? false, clickable: Boolean(onPointClick && s.clickable),
      pointHitRadius: onPointClick && s.clickable ? 6 : 1,
    };
    if (s.kind === "bar") return { ...base, type: "bar", borderWidth: 0, order: 10 };
    if (s.kind === "band") {
      // Paire de jeux : borne basse invisible + borne haute remplie jusqu'à la basse.
      return {
        ...base, type: "line", borderWidth: 0, pointRadius: 0, backgroundColor: s.color,
        fill: s.fillTo ?? false, spanGaps: false, order: 20,
      };
    }
    return {
      ...base, type: "line", borderWidth: s.width ?? 2, borderDash: s.dashed ? [5, 4] : [],
      pointRadius: s.points ? (dates.length > 120 ? 1 : 2.5) : 0, pointHoverRadius: 4, tension: 0.25,
      fill: false, showLine: s.showLine ?? true,
    };
  });
  // Barres : une demi-case de marge de chaque côté pour ne pas couper la première et la dernière.
  const pad = series.some((s) => s.kind === "bar") ? 0.5 : 0;
  const bounds = { min: -pad, max: Math.max(1, dates.length - 1) + pad };
  const scales = { x: dateAxis(dates, bounds), y: { ...y, ticks: { callback: (v) => fmtNum(v, decimals) } } };
  if (y2) scales.y2 = { position: "right", grid: { display: false }, ...y2 };
  // Point cliquable (ex. mesure du jour) : le plus proche sous le curseur, hors glissement.
  const clickedPoint = (chart, event) => chart
    .getElementsAtEventForMode(event, "nearest", { intersect: true }, false)
    .find((el) => chart.data.datasets[el.datasetIndex].clickable && chart.data.datasets[el.datasetIndex].data[el.index].y !== null);
  return new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      interaction: { mode: "index", intersect: false },
      scales,
      onClick: onPointClick && ((event, _els, chart) => {
        if (chart.$panZoom?.dragged) return;
        const el = clickedPoint(chart, event);
        if (el) onPointClick(dates[el.index]);
      }),
      onHover: onPointClick && ((event, _els, chart) => {
        if (chart.$panZoom?.drag) return;
        chart.canvas.style.cursor = clickedPoint(chart, event) ? "pointer" : "";
      }),
      plugins: {
        panZoom: { enabled: true, bounds, minRange: 6 },
        zones: { items: zones },
        legend: { labels: { boxWidth: 12, filter: (item, data) => !data.datasets[item.datasetIndex].hideInLegend } },
        tooltip: {
          filter: (item) => item.parsed.y !== null && !item.dataset.hideInLegend,
          callbacks: {
            title: (items) => (items[0] ? new Date(`${dates[items[0].dataIndex]}T00:00:00`).toLocaleDateString("fr-CH") : ""),
            label: (item) => `${item.dataset.label} : ${fmtNum(item.parsed.y, decimals)}`,
          },
        },
      },
    },
  });
}

/** Mini-courbe sans axes pour les cartes d'accueil. */
export function sparkline(canvas, values) {
  configure();
  const c = colors();
  return new Chart(canvas, {
    type: "line",
    data: { labels: values.map((_, i) => i), datasets: [{ data: values, borderColor: c.value, borderWidth: 2, pointRadius: 0, tension: 0.3, spanGaps: true }] },
    options: {
      animation: false, events: [],
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

/** Nuage de points avec droite de régression. */
export function scatterChart(canvas, points, { xLabel, yLabel, slope, intercept, xDecimals = 1, yDecimals = 1 }) {
  configure();
  const c = colors();
  const datasets = [{
    type: "scatter", label: "Jours", data: points.map((p) => ({ x: p.x, y: p.y, date: p.date })),
    backgroundColor: c.value + "99", borderColor: c.value, pointRadius: 3,
  }];
  if (slope !== null && slope !== undefined && points.length) {
    const xs = points.map((p) => p.x);
    const [min, max] = [Math.min(...xs), Math.max(...xs)];
    datasets.push({
      type: "line", label: "Régression", data: [{ x: min, y: intercept + slope * min }, { x: max, y: intercept + slope * max }],
      borderColor: c.ma7, borderWidth: 2, pointRadius: 0,
    });
  }
  return new Chart(canvas, {
    type: "scatter",
    data: { datasets },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const p = item.raw;
              const when = p.date ? `${new Date(`${p.date}T00:00:00`).toLocaleDateString("fr-CH")} : ` : "";
              return `${when}${fmtNum(p.x, xDecimals)} ; ${fmtNum(p.y, yDecimals)}`;
            },
          },
        },
      },
      scales: {
        x: { type: "linear", title: { display: true, text: xLabel } },
        y: { title: { display: true, text: yLabel } },
      },
    },
  });
}

// --- Graphiques intra-journaliers (axe X en temps réel) -----------------------------

const HOUR_MS = 3_600_000;
const TIME_STEPS_H = [1, 2, 3, 6, 12, 24, 48];
const LOCALE = "fr-CH";

/** Graduations alignées sur l'heure locale (≤ 9 étiquettes), y compris aux changements d'heure. */
function hourTicks(scale) {
  const range = scale.max - scale.min;
  const stepH = TIME_STEPS_H.find((h) => range / (h * HOUR_MS) <= 9) ?? 48;
  const d = new Date(scale.min);
  d.setMinutes(0, 0, 0);
  if (stepH >= 24) d.setHours(0);
  else d.setHours(Math.floor(d.getHours() / stepH) * stepH);
  const ticks = [];
  while (d.getTime() <= scale.max && ticks.length < 50) {
    if (d.getTime() >= scale.min) ticks.push({ value: d.getTime() });
    if (stepH >= 24) d.setDate(d.getDate() + stepH / 24);
    else d.setHours(d.getHours() + stepH);
  }
  scale.ticks = ticks;
}

export function fmtTimeTick(ms) {
  const d = new Date(ms);
  if (d.getHours() === 0 && d.getMinutes() === 0) {
    return d.toLocaleDateString(LOCALE, { weekday: "short", day: "2-digit", month: "2-digit" });
  }
  return d.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" });
}

const fmtInstant = (ms) => new Date(ms).toLocaleString(LOCALE, {
  weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

/** Insère une coupure (y = null) quand deux mesures sont séparées de plus de ``maxGapMs``. */
export function withGaps(points, maxGapMs) {
  const out = [];
  points.forEach(([x, y], i) => {
    if (i && x - points[i - 1][0] > maxGapMs) out.push({ x: (x + points[i - 1][0]) / 2, y: null });
    out.push({ x, y });
  });
  return out;
}

/**
 * Graphique sur une fenêtre de temps [min, max] (ms). ``series`` = [{label, data:[{x,y}], color,
 * stepped, segmentColor, fill}]. ``markers`` = options du plugin de repères ; ``onRangeChange``
 * est appelé après un glisser / zoom (pour synchroniser les autres graphiques).
 */
export function intradayChart(canvas, series, {
  min, max, decimals = 0, unit = "", y = {}, markers = {}, onRangeChange = null, yLabel = null,
} = {}) {
  configure();
  const datasets = series.map((s) => ({
    label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.fill ?? s.color,
    borderWidth: s.width ?? 1.6, pointRadius: 0, pointHoverRadius: 3, spanGaps: false,
    stepped: s.stepped ?? false, tension: s.stepped ? 0 : 0.2, fill: s.fill ? "origin" : false,
    segment: s.segmentColor ? { borderColor: (ctx) => s.segmentColor(ctx.p0.parsed.y) } : undefined,
  }));
  return new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      parsing: false,
      normalized: true,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      scales: {
        x: {
          type: "linear", min, max, afterBuildTicks: hourTicks,
          ticks: { maxRotation: 0, autoSkip: false, callback: (v) => fmtTimeTick(v) },
        },
        y: { ...y, ticks: { callback: yLabel ?? ((v) => fmtNum(v, decimals)), ...(y.ticks ?? {}) } },
      },
      plugins: {
        panZoom: { enabled: true, bounds: { min, max }, minRange: 30 * 60_000, onChange: onRangeChange },
        markers,
        legend: { display: series.length > 1, labels: { boxWidth: 12 } },
        tooltip: {
          callbacks: {
            title: (items) => (items[0] ? fmtInstant(items[0].parsed.x) : ""),
            label: (item) => `${item.dataset.label} : ${yLabel ? yLabel(item.parsed.y) : fmtNum(item.parsed.y, decimals)}${unit ? ` ${unit}` : ""}`,
          },
        },
      },
    },
  });
}
