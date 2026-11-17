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
  Chart.register(zonesPlugin);
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

/** Axe X par dates (catégories). */
function dateAxis(dates) {
  const ticks = calendarTicks(dates);
  if (!ticks) {
    return {
      type: "category",
      ticks: { autoSkip: true, maxRotation: 0, maxTicksLimit: 8, callback: (_v, i) => fmtShortDate(dates[i]) },
      grid: { display: false },
    };
  }
  return {
    type: "category",
    // Toutes les catégories sont évaluées ; seules celles du plan reçoivent une étiquette.
    // Renvoyer null masque à la fois l'étiquette et la ligne de grille correspondante.
    ticks: { autoSkip: false, maxRotation: 0, callback: (_v, i) => ticks.get(i) ?? null },
    grid: { display: true },
  };
}

/** Graphique temporel. ``series`` = [{label, data, color, kind: line|bar|band, dashed, fillTo, yAxisID, points}] */
export function timeChart(canvas, dates, series, { decimals = 0, zones = null, y = {}, y2 = null } = {}) {
  configure();
  const datasets = series.map((s) => {
    const base = {
      label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.color,
      yAxisID: s.yAxisID ?? "y", spanGaps: s.spanGaps ?? true, order: s.order ?? 0,
      hideInLegend: s.hideInLegend ?? false,
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
  const scales = { x: dateAxis(dates), y: { ...y, ticks: { callback: (v) => fmtNum(v, decimals) } } };
  if (y2) scales.y2 = { position: "right", grid: { display: false }, ...y2 };
  return new Chart(canvas, {
    type: "line",
    data: { labels: dates, datasets },
    options: {
      interaction: { mode: "index", intersect: false },
      scales,
      plugins: {
        zones: { items: zones },
        legend: { labels: { boxWidth: 12, filter: (item, data) => !data.datasets[item.datasetIndex].hideInLegend } },
        tooltip: {
          filter: (item) => item.raw !== null && !item.dataset.hideInLegend,
          callbacks: {
            title: (items) => (items[0] ? new Date(`${dates[items[0].dataIndex]}T00:00:00`).toLocaleDateString("fr-CH") : ""),
            label: (item) => `${item.dataset.label} : ${fmtNum(item.raw, decimals)}`,
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
