// Détail d'une mesure : la veille, le jour et le lendemain, en intra-journalier.
// Route : #/day/<YYYY-MM-DD>[/<clé de l'indicateur d'origine>]
import { api } from "../api.js";
import { intradayChart, setXRange, withGaps } from "../charts.js";
import {
  activityTypeLabel, escapeHtml, fmtDuration, fmtNum, fmtValue,
} from "../format.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const MIN = 60_000;
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

const localMidnight = (iso) => new Date(`${iso}T00:00:00`).getTime();
const shiftIso = (iso, days) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const longDate = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("fr-CH", {
  weekday: "long", day: "numeric", month: "long", year: "numeric",
});
const headDate = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("fr-CH", {
  weekday: "short", day: "2-digit", month: "2-digit",
});
const fmtClock = (ms) => new Date(ms).toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit" });

/** Début (ms) d'une activité : « YYYY-MM-DD HH:MM:SS » à l'heure locale. */
const activityStart = (a) => (a.start_local ? new Date(a.start_local.replace(" ", "T")).getTime() : null);

const STAGES = [
  { level: 0, label: "Profond", color: "--c-stage-deep" },
  { level: 1, label: "Léger", color: "--c-stage-light" },
  { level: 2, label: "Paradoxal", color: "--c-stage-rem" },
  { level: 3, label: "Éveil", color: "--c-stage-awake" },
];

function stagePoints(stages) {
  const out = [];
  stages.forEach((s, i) => {
    if (i && s.start - stages[i - 1].end > 5 * MIN) out.push({ x: s.start - 1, y: null });
    out.push({ x: s.start, y: s.level }, { x: s.end, y: s.level });
  });
  return out;
}

export async function render(view, params, ctx) {
  const day = ISO_RE.test(params[0] ?? "") ? params[0] : null;
  const origin = params[1] ?? null;
  if (!day) {
    view.innerHTML = `<div class="notice">Date invalide.</div>`;
    return;
  }
  const data = await api.day(day);
  if (!ctx.isCurrent()) return;

  const dates = data.dates;
  const start = localMidnight(dates[0]);
  const end = localMidnight(shiftIso(dates[2], 1));
  const intr = data.intraday;
  const suffix = origin ? `/${encodeURIComponent(origin)}` : "";

  // --- En-tête --------------------------------------------------------------------
  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `
    <div>
      <h1>Détail du ${escapeHtml(longDate(day))}</h1>
      <p class="small muted" style="margin:2px 0 0">Veille, jour et lendemain · glisser pour se déplacer dans le temps,
        molette pour zoomer, double-clic pour revenir aux 3 jours.</p>
    </div>
    <div class="toolbar">
      ${origin ? `<a class="button secondary" href="#/metric/${encodeURIComponent(origin)}">← Retour à l'indicateur</a>` : ""}
      <a class="button secondary" href="#/day/${shiftIso(day, -1)}${suffix}" title="Jour précédent">‹ Jour précédent</a>
      <a class="button secondary" href="#/day/${shiftIso(day, 1)}${suffix}" title="Jour suivant">Jour suivant ›</a>
    </div>`;
  view.append(head);

  // --- Repères communs : jour sélectionné, nuits, activités, minuits -------------------
  const activitySpans = data.activities
    .map((a) => ({ a, start: activityStart(a) }))
    .filter((x) => x.start !== null)
    .map(({ a, start: s }) => ({ start: s, end: s + (a.duration_s ?? 0) * 1000, color: css("--c-activity") }));
  const markers = {
    spans: [
      { start: localMidnight(day), end: localMidnight(shiftIso(day, 1)), color: css("--c-day-selected") },
      ...intr.nights.map((n) => ({ start: n.start, end: n.end, color: css("--c-night") })),
      ...activitySpans,
    ],
    lines: [localMidnight(dates[1]), localMidnight(dates[2])],
    lineColor: css("--c-baseline"),
  };

  // --- Graphiques intra-journaliers ---------------------------------------------------
  const legend = document.createElement("div");
  legend.className = "legend-inline";
  legend.innerHTML = `<span><i style="background:${css("--c-day-selected")};border:1px solid var(--border)"></i>Jour sélectionné</span>
    <span><i style="background:${css("--c-night")};border:1px solid var(--border)"></i>Sommeil</span>
    <span><i style="background:${css("--c-activity")}"></i>Activité</span>`;
  const grid = document.createElement("div");
  grid.className = "day-grid";
  view.append(legend, grid);

  const charts = [];
  const sync = (source) => (range) => {
    for (const c of charts) if (c !== source.chart) setXRange(c, range);
  };

  const specs = [
    { key: "body_battery", title: "Body Battery", color: "--c-bb", gap: 9 * 60 * MIN, y: { min: 0, max: 100 }, fill: true },
    { key: "heart_rate", title: "Fréquence cardiaque (sommeil)", color: "--c-hr", unit: "bpm", gap: 20 * MIN },
    { key: "stress", title: "Stress (sommeil)", color: "--c-stress", gap: 20 * MIN, y: { min: 0, max: 100 } },
    { key: "hrv", title: "VFC (sommeil)", color: "--c-hrv", unit: "ms", gap: 30 * MIN },
    { key: "spo2", title: "SpO2 (sommeil)", color: "--c-spo2", unit: "%", gap: 20 * MIN },
    { key: "respiration", title: "Respiration (sommeil)", color: "--c-resp", unit: "rpm", gap: 20 * MIN, decimals: 1 },
  ];

  const addCard = (title, note = "") => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h2>${escapeHtml(title)}</h2><div class="chart-box"><canvas role="img"></canvas></div>${note}`;
    grid.append(card);
    const canvas = card.querySelector("canvas");
    canvas.setAttribute("aria-label", `${title} du ${headDate(dates[0])} au ${headDate(dates[2])}`);
    return canvas;
  };
  const track = (make) => {
    const holder = {};
    holder.chart = ctx.track(make(sync(holder)));
    charts.push(holder.chart);
  };

  let shown = 0;
  for (const s of specs) {
    const points = (intr[s.key] ?? []).filter(([t]) => t >= start && t <= end);
    if (!points.length) continue;
    shown++;
    const color = css(s.color);
    const canvas = addCard(s.title);
    track((onRangeChange) => intradayChart(canvas, [{
      label: s.title.replace(/ \(sommeil\)$/, ""), data: withGaps(points, s.gap), color,
      fill: s.fill ? `${color}22` : undefined,
    }], { min: start, max: end, unit: s.unit, decimals: s.decimals ?? 0, y: s.y ?? {}, markers, onRangeChange }));
  }

  const stages = (intr.sleep_stages ?? []).filter((st) => st.end >= start && st.start <= end);
  if (stages.length) {
    shown++;
    const stageColor = (level) => css(STAGES[level]?.color ?? "--c-baseline");
    const canvas = addCard("Phases de sommeil", `<div class="legend-inline">${STAGES.map((st) =>
      `<span><i style="background:${css(st.color)}"></i>${st.label}</span>`).join("")}</div>`);
    track((onRangeChange) => intradayChart(canvas, [{
      label: "Phase", data: stagePoints(stages), color: css("--c-stage-light"), stepped: "before", width: 4,
      segmentColor: stageColor,
    }], {
      min: start, max: end, markers, onRangeChange,
      y: { min: -0.5, max: 3.5, ticks: { stepSize: 1 } },
      yLabel: (v) => STAGES[Math.round(v)]?.label ?? "",
    }));
  }

  if (!shown) {
    grid.innerHTML = `<div class="notice">Aucune mesure détaillée disponible pour ces 3 jours.</div>`;
  } else {
    const note = document.createElement("p");
    note.className = "small muted";
    note.textContent = "Garmin fournit le détail minute par minute pendant le sommeil ; en journée, seuls quelques "
      + "points de Body Battery sont importés. Les valeurs journalières complètes figurent dans le tableau ci-dessous.";
    view.append(note);
  }

  // --- Activités -------------------------------------------------------------------
  const actCard = document.createElement("div");
  actCard.className = "card";
  if (!data.activities.length) {
    actCard.innerHTML = `<h2>Activités</h2><p class="muted">Aucune activité sur ces 3 jours.</p>`;
  } else {
    actCard.innerHTML = `<h2>Activités</h2><div class="activity-list">${data.activities.map((a) => {
      const s = activityStart(a);
      const facts = [
        fmtDuration(a.duration_s),
        a.distance_m ? `${fmtNum(a.distance_m / 1000, 2)} km` : null,
        a.elev_gain_m ? `${fmtNum(a.elev_gain_m)} m D+` : null,
        a.avg_hr ? `FC ${fmtNum(a.avg_hr)} / ${fmtNum(a.max_hr)} bpm` : null,
        a.training_load ? `charge ${fmtNum(a.training_load)}` : null,
        a.aerobic_te !== null ? `effet ${fmtNum(a.aerobic_te, 1)} / ${fmtNum(a.anaerobic_te, 1)}` : null,
      ].filter(Boolean);
      const when = s ? `${headDate(a.date)} ${fmtClock(s)}–${fmtClock(s + (a.duration_s ?? 0) * 1000)}` : headDate(a.date);
      return `<div class="activity-item"><span class="when">${escapeHtml(when)}</span>
        <strong>${escapeHtml(activityTypeLabel(a.type))}</strong><span>${escapeHtml(a.name ?? "")}</span>
        <span class="muted">${escapeHtml(facts.join(" · "))}</span></div>`;
    }).join("")}</div>`;
  }
  view.append(actCard);

  // --- Valeurs journalières de tous les indicateurs ---------------------------------
  const tableCard = document.createElement("div");
  tableCard.className = "card table-wrap";
  const selIdx = dates.indexOf(day);
  const th = dates.map((d, i) => `<th class="num${i === selIdx ? " selected" : ""}">${escapeHtml(headDate(d))}</th>`).join("");
  let group = null;
  const rows = data.daily.filter((r) => r.values.some((v) => v !== null)).map((r) => {
    const groupRow = r.group !== group ? `<tr class="group"><td colspan="4">${escapeHtml(r.group)}</td></tr>` : "";
    group = r.group;
    const cells = r.values.map((v, i) =>
      `<td class="num${i === selIdx ? " selected" : ""}">${fmtValue(v, r.unit, r.decimals)}</td>`).join("");
    return `${groupRow}<tr><td><a href="#/metric/${encodeURIComponent(r.key)}">${escapeHtml(r.label)}</a></td>${cells}</tr>`;
  }).join("");
  tableCard.innerHTML = `<h2>Valeurs journalières</h2>${rows
    ? `<table class="day-table"><thead><tr><th>Indicateur</th>${th}</tr></thead><tbody>${rows}</tbody></table>`
    : `<p class="muted">Aucune valeur journalière sur ces 3 jours.</p>`}`;
  view.append(tableCard);
}
