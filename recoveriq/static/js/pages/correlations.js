// Vue corrélations (calculées côté serveur).
import { api, exportUrl } from "../api.js";
import { scatterChart } from "../charts.js";
import {
  badge, escapeHtml, exportLink, fmtNum, fmtSigned, fmtSignedValue, fmtValue, loadPref, periodSelector,
  latestOnly, STALE,
} from "../format.js";

function pValue(p) {
  if (p === null || p === undefined) return "–";
  return p < 0.001 ? "< 0,001" : fmtNum(p, 3);
}

function statsHtml(s, minPairs) {
  if (!s.sufficient) {
    return `<p class="muted small">Données insuffisantes (${s.n} couple(s), minimum ${minPairs}).</p>`;
  }
  const significant = s.pearson_p !== null && s.pearson_p < 0.05;
  return `<p class="small">
      <b>r = ${fmtNum(s.pearson_r, 2)}</b> (${escapeHtml(s.strength)}) · p ${pValue(s.pearson_p)}
      ${significant ? badge("significatif", "ok") : badge("non significatif", "muted")}<br>
      <span class="muted">Spearman ρ = ${fmtNum(s.spearman_rho, 2)} · n = ${s.n}</span></p>`;
}

function pairCard(id, title, note, stats, minPairs) {
  return `<div class="card">
    <h3>${escapeHtml(title)}</h3>
    <div class="small muted">${escapeHtml(note)}</div>
    ${statsHtml(stats, minPairs)}
    ${stats.sufficient ? `<div class="chart-box small"><canvas data-pair="${id}" role="img" aria-label="${escapeHtml(title)}"></canvas></div>` : ""}
  </div>`;
}

export async function render(view, _params, ctx) {
  const latest = latestOnly();
  let period = loadPref("period", "365");

  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Corrélations</h1>`;
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  const exportA = exportLink(exportUrl.correlations(period));
  toolbar.append(periodSelector(period, (p) => { period = p; exportA.href = exportUrl.correlations(p); draw(); }), exportA);
  head.append(toolbar);

  const intro = document.createElement("div");
  intro.className = "notice";
  intro.innerHTML = `Une corrélation mesure une association, pas une cause.
    r : coefficient de Pearson (−1 à 1) ; ρ : Spearman, moins sensible aux valeurs extrêmes.
    Le sommeil est daté du jour du réveil.`;

  const body = document.createElement("div");
  body.className = "grid";
  view.append(head, intro, body);

  let charts = [];
  ctx.onCleanup(() => charts.forEach((c) => c.destroy()));

  async function draw() {
    const data = await latest(api.correlations(period));
    if (data === STALE || !ctx.isCurrent()) return;
    charts.forEach((c) => c.destroy());
    charts = [];

    const sections = [];
    for (const [groupId, groupTitle] of Object.entries(data.groups)) {
      if (groupId === "vo2_volume" || groupId === "weekday_weekend") continue;
      const pairs = data.pairs.filter((p) => p.group === groupId);
      sections.push(`<section class="grid"><h2>${escapeHtml(groupTitle)}</h2><div class="grid two">
        ${pairs.map((p) => pairCard(p.id, `${p.x.label} → ${p.y.label}`, p.note, p.stats, data.min_pairs)).join("")}
      </div></section>`);
    }

    const vo2 = data.vo2_volume;
    sections.push(`<section class="grid"><h2>${escapeHtml(data.groups.vo2_volume)}</h2><div class="grid two">
      ${pairCard("vo2_level", `Volume ${vo2.weeks} semaines → VO2 max`, "Heures d'activité sur les 4 semaines précédentes vs VO2 max en fin de semaine", vo2.level, data.min_pairs)}
      ${pairCard("vo2_change", `Volume ${vo2.weeks} semaines → variation de VO2 max`, "Heures sur 4 semaines vs évolution de la VO2 max sur ces mêmes 4 semaines", vo2.change, data.min_pairs)}
    </div></section>`);

    const ww = data.weekday_weekend;
    sections.push(`<section class="card table-wrap"><h2>${escapeHtml(data.groups.weekday_weekend)}</h2>
      <table><thead><tr><th>Indicateur</th><th class="num">Semaine (lun–ven)</th><th class="num">Week-end (sam–dim)</th>
        <th class="num">Écart</th><th class="num">p (Welch)</th><th class="num">d de Cohen</th><th></th></tr></thead>
      <tbody>${ww.map((w) => `<tr>
        <td>${escapeHtml(w.label)}</td>
        <td class="num">${fmtValue(w.weekday_mean, w.unit, w.decimals + 1)} <span class="muted small">n=${w.weekday_n}</span></td>
        <td class="num">${fmtValue(w.weekend_mean, w.unit, w.decimals + 1)} <span class="muted small">n=${w.weekend_n}</span></td>
        <td class="num">${w.difference === null ? "–" : `${fmtSignedValue(w.difference, w.unit, w.decimals + 1)} (${fmtSigned(w.difference_pct, 1)} %)`}</td>
        <td class="num">${pValue(w.p_value)}</td>
        <td class="num">${fmtNum(w.cohen_d, 2)}</td>
        <td>${w.p_value === null ? badge("données insuffisantes") : w.significant ? badge("significatif", "ok") : ""}</td>
      </tr>`).join("")}</tbody></table>
      <p class="small muted">Pour le sommeil, « week-end » = nuits de vendredi et samedi (datées du réveil).
        d de Cohen : 0,2 petit effet, 0,5 moyen, 0,8 grand.</p></section>`);

    body.innerHTML = sections.join("");

    const draws = [
      ...data.pairs.map((p) => [p.id, p.points, p.x, p.y, p.stats]),
      ["vo2_level", vo2.points.map((p) => ({ date: p.week_end, x: p.hours_4w, y: p.vo2max })),
        { label: "Heures sur 4 sem.", unit: "h" }, { label: "VO2 max", unit: "" }, vo2.level],
      ["vo2_change", vo2.points.filter((p) => p.vo2_change_4w !== null).map((p) => ({ date: p.week_end, x: p.hours_4w, y: p.vo2_change_4w })),
        { label: "Heures sur 4 sem.", unit: "h" }, { label: "Variation VO2 max", unit: "" }, vo2.change],
    ];
    for (const [id, points, x, y, stats] of draws) {
      const canvas = body.querySelector(`[data-pair="${id}"]`);
      if (!canvas) continue;
      const axis = (m) => (m.unit ? `${m.label} (${m.unit})` : m.label);
      charts.push(scatterChart(canvas, points, { xLabel: axis(x), yLabel: axis(y), slope: stats.slope, intercept: stats.intercept }));
    }
  }

  await draw();
}
