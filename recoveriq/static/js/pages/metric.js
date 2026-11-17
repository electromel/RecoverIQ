// Vue par indicateur : historique, moyennes mobiles 7 j / 28 j, bande de normalité.
import { api, exportUrl } from "../api.js";
import { colors, timeChart, viewFrom } from "../charts.js";
import {
  escapeHtml, exportLink, fmtDate, fmtSigned, fmtValue, loadPref, periodSelector,
  latestOnly, STALE,
} from "../format.js";

let catalogCache = null;

function seriesSelect(catalog, current, onChange) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Indicateur");
  const groups = new Map();
  for (const s of catalog.series) {
    if (!groups.has(s.group)) groups.set(s.group, []);
    groups.get(s.group).push(s);
  }
  for (const [group, items] of groups) {
    const og = document.createElement("optgroup");
    og.label = group;
    for (const s of items) {
      const opt = new Option(s.available ? s.label : `${s.label} (non disponible)`, s.key, false, s.key === current);
      og.append(opt);
    }
    select.append(og);
  }
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function tile(label, value) {
  return `<div class="stat-tile"><div class="label">${escapeHtml(label)}</div><div class="v">${value}</div></div>`;
}

export async function render(view, params, ctx) {
  const latest = latestOnly();
  const key = params[0] || "hrv";
  let period = loadPref("period", "90");
  catalogCache ??= await api.catalog();
  if (!ctx.isCurrent()) return;

  const head = document.createElement("div");
  head.className = "page-head";
  const title = document.createElement("h1");
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  const exportA = exportLink(exportUrl.series(key, period));
  toolbar.append(
    seriesSelect(catalogCache, key, (k) => { location.hash = `#/metric/${encodeURIComponent(k)}`; }),
    periodSelector(period, (p) => { period = p; exportA.href = exportUrl.series(key, p); draw(); }),
    exportA,
  );
  head.append(title, toolbar);

  const tiles = document.createElement("div");
  tiles.className = "stat-tiles";
  const chartCard = document.createElement("div");
  chartCard.className = "card";
  chartCard.innerHTML = `<div class="chart-box"><canvas role="img"></canvas></div>
    <p class="small muted">Cliquer sur une mesure (point bleu) ouvre le détail des 3 jours autour.
    La période choisie fixe la vue de départ et les statistiques ; tout l'historique reste accessible :
    glisser pour se déplacer dans le temps, molette pour zoomer, double-clic pour voir tout l'historique.</p>
    <p class="small muted">Bande de normalité : moyenne des 30 jours précédents ± 1 écart type (au moins 10 valeurs).
    Les jours sans mesure ne sont pas interpolés.</p>`;
  view.append(head, tiles, chartCard);

  let chart = null;
  ctx.onCleanup(() => chart?.destroy());
  // Historique complet (courbe) chargé une fois ; la période ne sert qu'aux statistiques
  // et à la plage affichée au départ.
  let history = null;

  async function draw() {
    const result = await latest(Promise.all([api.series(key, period), history ?? api.series(key, "all")]));
    if (result === STALE || !ctx.isCurrent()) return;
    const [data, all] = result;
    history = all;
    const m = data.meta;
    title.textContent = m.label;
    chart?.destroy();
    chart = null;

    if (!data.available || !data.points.length) {
      tiles.innerHTML = "";
      chartCard.querySelector(".chart-box").innerHTML =
        `<div class="notice">Pas de donnée pour cet indicateur : non fourni par votre montre, ou pas encore importé sur cette période.</div>`;
      return;
    }
    if (!chartCard.querySelector("canvas")) {
      chartCard.querySelector(".chart-box").innerHTML = `<canvas role="img"></canvas>`;
    }
    const st = data.stats;
    const fv = (v) => fmtValue(v, m.unit, m.decimals);
    const trend = st.trend_per_week === null ? "–"
      : `${fmtSigned(st.trend_per_week, m.decimals + 1)}${m.unit ? ` ${escapeHtml(m.unit)}` : ""} / sem.`;
    tiles.innerHTML = [
      tile(`Dernière valeur (${fmtDate(st.latest_date)})`, fv(st.latest)),
      tile("Moyenne de la période", fv(st.mean)),
      tile("Écart type", fmtValue(st.std, m.unit, m.decimals + 1)),
      tile("Min / max", `${fv(st.min)} / ${fv(st.max)}`),
      tile("Tendance", trend),
      tile("Jours mesurés", String(st.n)),
    ].join("");

    const c = colors();
    const dates = all.points.map((p) => p.date);
    const col = (name) => all.points.map((p) => p[name]);
    const canvas = chartCard.querySelector("canvas");
    canvas.setAttribute("aria-label", `${m.label} : historique, moyennes mobiles et bande de normalité`);
    chart = timeChart(canvas, dates, [
      { label: "Bande basse", data: col("band_low"), color: "transparent", kind: "band", hideInLegend: true },
      { label: "Bande de normalité", data: col("band_high"), color: c.band, kind: "band", fillTo: "-1" },
      { label: "Ligne de base 30 j", data: col("baseline"), color: c.baseline, dashed: true, width: 1.5, spanGaps: false },
      { label: m.label, data: col("value"), color: c.value, points: true, width: 1.2, spanGaps: false, showLine: "auto", clickable: true },
      { label: "Moyenne 7 j", data: col("ma7"), color: c.ma7, width: 2 },
      { label: "Moyenne 28 j", data: col("ma28"), color: c.ma28, width: 2 },
    ], {
      decimals: m.decimals,
      view: viewFrom(dates, data.points[0].date),
      onPointClick: (iso) => { location.hash = `#/day/${iso}/${encodeURIComponent(key)}`; },
    });
  }

  await draw();
}
