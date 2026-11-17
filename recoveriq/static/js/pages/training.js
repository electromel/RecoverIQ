// Vue charge d'entraînement : aiguë vs chronique, ratio et zones, focus de charge, volume hebdo.
import { api, exportUrl } from "../api.js";
import { colors, timeChart, viewFrom } from "../charts.js";
import {
  escapeHtml, exportLink, fmtDate, fmtNum, focusFeedbackLabel, loadPref, periodSelector, trainingStatusLabel,
  latestOnly, STALE,
} from "../format.js";

function zoneColor(c, id) {
  return c.zone[id];
}

function focusHtml(focus) {
  if (!focus) return `<p class="muted">Focus de charge non fourni par votre montre.</p>`;
  const scaleMax = Math.max(...focus.items.map((i) => Math.max(i.value ?? 0, i.max ?? 0))) * 1.1 || 1;
  const pct = (v) => `${Math.min(100, (100 * (v ?? 0)) / scaleMax)}%`;
  const rows = focus.items.map((i) => {
    const target = i.min !== null && i.max !== null
      ? `<div class="focus-target" style="left:${pct(i.min)};width:calc(${pct(i.max)} - ${pct(i.min)})" title="Plage cible ${fmtNum(i.min)} – ${fmtNum(i.max)}"></div>`
      : "";
    return `<div class="focus-row">
        <span>${escapeHtml(i.label)}</span>
        <div class="focus-track">${target}<div class="focus-bar" style="width:${pct(i.value)}"></div></div>
        <span class="num">${fmtNum(i.value)}</span>
      </div>`;
  }).join("");
  const feedback = focusFeedbackLabel(focus.feedback);
  return `${rows}<p class="small muted">Charge des 4 dernières semaines au ${fmtDate(focus.date)} ; zone en pointillé = plage cible Garmin.
    ${feedback ? `<br>Bilan Garmin : <b>${escapeHtml(feedback)}</b>` : ""}</p>`;
}

export async function render(view, _params, ctx) {
  const latest = latestOnly();
  let period = loadPref("period", "90");

  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Charge d'entraînement</h1>`;
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  const exportA = exportLink(exportUrl.training(period));
  toolbar.append(periodSelector(period, (p) => { period = p; exportA.href = exportUrl.training(p); draw(); }), exportA);
  head.append(toolbar);

  const body = document.createElement("div");
  body.className = "grid";
  view.append(head, body);

  let charts = [];
  ctx.onCleanup(() => charts.forEach((c) => c.destroy()));

  // Historique complet pour les courbes ; la période fixe la vue de départ et les synthèses.
  let history = null;

  async function draw() {
    const result = await latest(Promise.all([api.training(period), history ?? api.training("all")]));
    if (result === STALE || !ctx.isCurrent()) return;
    const [data, all] = result;
    history = all;
    charts.forEach((c) => c.destroy());
    charts = [];

    if (!data.daily.length) {
      body.innerHTML = `<div class="notice">Pas de donnée de charge sur cette période (non fournie par la montre ou pas encore importée).</div>`;
      return;
    }
    const c = colors();
    const status = data.current_status;
    const zoneTotal = Object.values(data.zone_days).reduce((a, b) => a + b, 0) || 1;
    const chips = data.zones.map((z) => `
      <div class="zone-chip" style="background:${zoneColor(c, z.id)}">
        <span class="small">${escapeHtml(z.label)} (${fmtNum(z.min, 1)}${z.max !== null ? ` – ${fmtNum(z.max, 1)}` : " +"})</span>
        <b>${data.zone_days[z.id]} j</b><span class="small muted">${fmtNum((100 * data.zone_days[z.id]) / zoneTotal)} %</span>
      </div>`).join("");
    const timeline = data.status_timeline.slice(-8).reverse().map((t) =>
      `<li>${fmtDate(t.date)} : ${escapeHtml(trainingStatusLabel(t.status))}</li>`).join("");

    body.innerHTML = `
      <div class="card">
        <h2>Charge aiguë vs chronique</h2>
        <div class="chart-box"><canvas id="load-chart" role="img" aria-label="Charge aiguë et chronique"></canvas></div>
      </div>
      <div class="card">
        <h2>Ratio aiguë / chronique</h2>
        <div class="chart-box small"><canvas id="acwr-chart" role="img" aria-label="Ratio aiguë sur chronique avec zones"></canvas></div>
        <div class="zone-chips" style="margin-top:10px">${chips}</div>
        <p class="small muted">Zones d'après Gabbett (2016) : 0,8 – 1,3 = zone optimale ; au-delà de 1,5, risque de blessure accru.
          Le statut ACWR propre à Garmin figure dans l'export CSV.</p>
      </div>
      <div class="grid two">
        <div class="card"><h2>Focus de charge</h2>${focusHtml(data.focus)}</div>
        <div class="card"><h2>Statut d'entraînement</h2>
          <p>Actuel : <b>${escapeHtml(trainingStatusLabel(status?.status))}</b>${status ? ` depuis le ${fmtDate(status.date)}` : ""}</p>
          ${timeline ? `<h3>Derniers changements</h3><ul>${timeline}</ul>` : ""}
        </div>
      </div>
      <div class="card">
        <h2>Volume hebdomadaire (activités)</h2>
        <div class="chart-box small"><canvas id="volume-chart" role="img" aria-label="Volume hebdomadaire"></canvas></div>
      </div>`;

    const dates = all.daily.map((d) => d.date);
    const col = (k) => all.daily.map((d) => d[k]);
    const dailyView = viewFrom(dates, data.daily[0].date);
    charts.push(timeChart(body.querySelector("#load-chart"), dates, [
      { label: "Plage chronique basse", data: col("chronic_min"), color: "transparent", kind: "band", hideInLegend: true },
      { label: "Plage optimale Garmin", data: col("chronic_max"), color: c.band, kind: "band", fillTo: "-1" },
      { label: "Charge aiguë", data: col("acute_load"), color: c.ma7 },
      { label: "Charge chronique", data: col("chronic_load"), color: c.value },
    ], { view: dailyView }));

    const acwr = col("acwr");
    const maxAcwr = Math.max(2, ...acwr.filter((v) => v !== null));
    charts.push(timeChart(body.querySelector("#acwr-chart"), dates, [
      { label: "Ratio A/C", data: acwr, color: c.value, points: true },
    ], {
      view: dailyView,
      decimals: 2,
      y: { min: 0, max: Math.ceil(maxAcwr * 10) / 10 },
      zones: data.zones.map((z) => ({ min: z.min, max: z.max, color: zoneColor(c, z.id) })),
    }));

    const weeks = all.weekly_volume;
    if (data.weekly_volume.length) {
      charts.push(timeChart(body.querySelector("#volume-chart"), weeks.map((w) => w.week), [
        { label: "Heures", data: weeks.map((w) => w.hours), color: c.value, kind: "bar" },
        { label: "Charge", data: weeks.map((w) => w.load), color: c.ma7, yAxisID: "y2", points: true },
      ], {
        decimals: 1, y: { title: { display: true, text: "h" } }, y2: { title: { display: true, text: "Charge" } },
        view: viewFrom(weeks.map((w) => w.week), data.weekly_volume[0].week),
      }));
    } else {
      body.querySelector("#volume-chart").parentElement.innerHTML = `<p class="muted">Aucune activité sur la période.</p>`;
    }
  }

  await draw();
}
