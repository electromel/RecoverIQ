// Accueil : cartes du jour comparées à la ligne de base sur 30 jours.
import { api, exportUrl } from "../api.js";
import { sparkline } from "../charts.js";
import {
  badge, escapeHtml, exportLink, fmtDate, fmtNum, fmtSigned, fmtValue, trainingStatusLabel,
} from "../format.js";

const STATUS = {
  normal: ["Dans la normale", "muted"],
  above: ["Au-dessus de la normale", null],
  below: ["En dessous de la normale", null],
  insufficient: ["Ligne de base insuffisante", "muted"],
};

function comparisonHtml(m) {
  const cmp = m.comparison;
  if (!cmp || cmp.status === "insufficient") {
    return `<div class="small muted">Ligne de base 30 j : pas encore assez de jours</div>`;
  }
  const [label, fixedCls] = STATUS[cmp.status];
  const cls = fixedCls ?? (cmp.favorable === true ? "ok" : cmp.favorable === false ? "err" : "warn");
  const pct = cmp.delta_pct !== null ? ` (${fmtSigned(cmp.delta_pct, 1)} %)` : "";
  return `
    <div>${badge(label, cls)}</div>
    <div class="small muted">Base 30 j : ${fmtValue(cmp.baseline, m.unit, m.decimals)}
      · écart ${fmtSigned(cmp.delta, m.decimals)}${pct}</div>`;
}

function cardHtml(card) {
  const m = card.main;
  if (!m.available) {
    return `<div class="card metric-card"><h3>${escapeHtml(card.title)}</h3>
      <div class="muted">Non fourni par votre montre ou pas encore importé.</div></div>`;
  }
  const valueHtml = m.unit === "h"
    ? fmtValue(m.value, m.unit)
    : `${fmtNum(m.value, m.decimals)}<span class="unit">${escapeHtml(m.unit)}</span>`;
  const when = m.stale ? `<span class="badge warn">au ${fmtDate(m.date)}</span>` : `<span class="small muted">${fmtDate(m.date)}</span>`;
  const secondary = card.secondary.filter((s) => s.available).map((s) => `
    <dt>${escapeHtml(s.label)}</dt><dd>${fmtValue(s.value, s.unit, s.decimals)}</dd>`).join("");
  return `
    <a class="card metric-card" href="#/metric/${encodeURIComponent(m.key)}" title="${escapeHtml(m.description ? `${m.description}

Cliquer pour voir l'historique.` : "Voir l'historique")}">
      <div class="page-head"><h3>${escapeHtml(card.title)}</h3>${when}</div>
      <div class="small muted">${escapeHtml(m.label)}</div>
      <div class="value">${valueHtml}</div>
      ${comparisonHtml(m)}
      <div class="spark"><canvas data-spark="${card.id}" aria-label="Évolution sur 14 jours" role="img"></canvas></div>
      ${secondary ? `<dl>${secondary}</dl>` : ""}
    </a>`;
}

export async function render(view, _params, ctx) {
  const data = await api.home();
  if (!ctx.isCurrent()) return;

  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<div><h1>Aujourd'hui</h1><div class="muted">${fmtDate(data.today)} · comparaison aux 30 jours précédents</div></div>`;
  head.append(exportLink(exportUrl.home()));

  const grid = document.createElement("div");
  grid.className = "grid cards";
  grid.innerHTML = data.cards.map(cardHtml).join("");

  view.append(head, grid);

  if (data.training) {
    const t = data.training;
    const strip = document.createElement("a");
    strip.className = "card";
    strip.href = "#/training";
    strip.style.textDecoration = "none";
    strip.style.color = "inherit";
    strip.innerHTML = `
      <div class="page-head"><h3>Entraînement</h3><span class="small muted">${fmtDate(t.date)}</span></div>
      <div>Statut : <b>${escapeHtml(trainingStatusLabel(t.status_phrase))}</b>
        · Charge aiguë ${fmtNum(t.acute_load)} / chronique ${fmtNum(t.chronic_load)}
        · Ratio ${fmtNum(t.acwr, 2)}</div>`;
    view.append(strip);
  }

  for (const card of data.cards) {
    const canvas = grid.querySelector(`[data-spark="${card.id}"]`);
    if (canvas && card.main.sparkline) ctx.track(sparkline(canvas, card.main.sparkline));
  }
}
