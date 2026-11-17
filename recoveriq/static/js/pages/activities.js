// Liste des activités, filtrable par type et triable par colonne (par défaut : date, plus récente d'abord).
import { api, exportUrl } from "../api.js";
import {
  activityTypeLabel, escapeHtml, exportLink, fmtChrono, fmtDateTime, fmtDuration, fmtNum, loadPref, periodSelector,
  latestOnly, STALE,
} from "../format.js";

// text : tri alphabétique (croissant au premier clic) ; sinon numérique (décroissant au premier clic,
// croissant pour les chronos : asc).
const dash = (v, f) => (v === null || v === undefined || v === 0 ? "–" : f(v));
const COLUMNS = [
  { key: "date", label: "Date", value: (r) => r.start_local, text: true,
    cell: (r) => fmtDateTime(r.start_local?.replace(" ", "T")) },
  { key: "type", label: "Type", value: (r) => activityTypeLabel(r.type), text: true,
    cell: (r) => escapeHtml(activityTypeLabel(r.type)) },
  { key: "name", label: "Nom", value: (r) => r.name, text: true, cell: (r) => escapeHtml(r.name) },
  { key: "duration", label: "Durée", num: true, value: (r) => r.duration_s, cell: (r) => fmtDuration(r.duration_s) },
  { key: "moving", label: "En mouvement", num: true, value: (r) => r.moving_s, cell: (r) => dash(r.moving_s, fmtDuration) },
  { key: "distance", label: "Distance", num: true, value: (r) => r.distance_m || null,
    cell: (r) => dash(r.distance_m, (v) => `${fmtNum(v / 1000, 2)} km`) },
  { key: "elev", label: "D+", num: true, value: (r) => r.elev_gain_m || null, cell: (r) => dash(r.elev_gain_m, (v) => `${fmtNum(v)} m`) },
  { key: "elev_loss", label: "D−", num: true, value: (r) => r.elev_loss_m || null, cell: (r) => dash(r.elev_loss_m, (v) => `${fmtNum(v)} m`) },
  { key: "hr", label: "FC moy / max", num: true, value: (r) => r.avg_hr, cell: (r) => `${fmtNum(r.avg_hr)} / ${fmtNum(r.max_hr)}` },
  { key: "calories", label: "Calories", num: true, value: (r) => r.calories || null, cell: (r) => dash(r.calories, (v) => `${fmtNum(v)} kcal`) },
  { key: "load", label: "Charge", num: true, value: (r) => r.training_load, cell: (r) => fmtNum(r.training_load) },
  { key: "te", label: "Effet aér. / anaér.", num: true, value: (r) => r.aerobic_te,
    cell: (r) => `${fmtNum(r.aerobic_te, 1)} / ${fmtNum(r.anaerobic_te, 1)}` },
  { key: "vo2max", label: "VO2 max", num: true, value: (r) => r.vo2max || null, cell: (r) => dash(r.vo2max, (v) => fmtNum(v, 1)),
    help: "VO2 max estimée par Garmin à l'issue de la séance (course ou vélo avec capteur de puissance)." },
  { key: "best1", label: "1 km", num: true, asc: true, value: (r) => r.best_1k_s, cell: (r) => fmtChrono(r.best_1k_s),
    help: "Meilleur temps sur 1 km pendant l'activité (tronçon le plus rapide, calculé par Garmin)." },
  { key: "best5", label: "5 km", num: true, asc: true, value: (r) => r.best_5k_s, cell: (r) => fmtChrono(r.best_5k_s),
    help: "Meilleur temps sur 5 km pendant l'activité." },
  { key: "best10", label: "10 km", num: true, asc: true, value: (r) => r.best_10k_s, cell: (r) => fmtChrono(r.best_10k_s),
    help: "Meilleur temps sur 10 km pendant l'activité." },
  { key: "recovery", label: "Récupération", num: true, value: (r) => r.recovery_time_min,
    cell: (r) => (r.recovery_time_min === null || r.recovery_time_min === undefined ? "–" : fmtDuration(r.recovery_time_min * 60)),
    help: "Temps de récupération estimé par Garmin juste après la séance, avant d'être pleinement récupéré pour un nouvel effort intense." },
];

export async function render(view, _params, ctx) {
  const latest = latestOnly();
  let period = loadPref("period", "90");
  let typeFilter = "";
  let rows = [];
  let sort = { key: "date", dir: -1 };   // -1 : décroissant

  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Activités</h1>`;
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  const typeSelect = document.createElement("select");
  typeSelect.setAttribute("aria-label", "Type d'activité");
  typeSelect.addEventListener("change", () => { typeFilter = typeSelect.value; renderTable(); });
  const exportA = exportLink(exportUrl.activities(period));
  toolbar.append(typeSelect, periodSelector(period, (p) => { period = p; exportA.href = exportUrl.activities(p); load(); }), exportA);
  head.append(toolbar);

  const summary = document.createElement("p");
  summary.className = "muted";
  const card = document.createElement("div");
  card.className = "card table-wrap";
  view.append(head, summary, card);

  function renderTable() {
    const shown = typeFilter ? rows.filter((r) => r.type === typeFilter) : rows;
    const totalH = shown.reduce((s, r) => s + (r.duration_s ?? 0), 0);
    const totalKm = shown.reduce((s, r) => s + (r.distance_m ?? 0), 0) / 1000;
    const totalUp = shown.reduce((s, r) => s + (r.elev_gain_m ?? 0), 0);
    summary.textContent = `${shown.length} activité(s) · ${fmtDuration(totalH)} · ${fmtNum(totalKm, 1)} km · ${fmtNum(totalUp)} m D+`;
    if (!shown.length) {
      card.innerHTML = `<p class="muted">Aucune activité sur cette période.</p>`;
      return;
    }
    const sorted = sortRows(shown);
    card.innerHTML = `<table>
      <thead><tr>${COLUMNS.map((c) => {
        const active = c.key === sort.key;
        const ariaSort = active ? (sort.dir === 1 ? "ascending" : "descending") : "none";
        const arrow = active ? (sort.dir === 1 ? "▲" : "▼") : "";
        return `<th${c.num ? ' class="num"' : ""} aria-sort="${ariaSort}"${c.help ? ` title="${escapeHtml(c.help)}"` : ""}>
          <button type="button" class="sort-btn${active ? " active" : ""}" data-key="${c.key}">${escapeHtml(c.label)}<span class="sort-arrow" aria-hidden="true">${arrow}</span></button></th>`;
      }).join("")}</tr></thead>
      <tbody>${sorted.map((r) => `<tr>${COLUMNS.map((c) => `<td${c.num ? ' class="num"' : ""}>${c.cell(r)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    card.querySelectorAll(".sort-btn").forEach((btn) => btn.addEventListener("click", () => {
      const col = COLUMNS.find((c) => c.key === btn.dataset.key);
      sort = sort.key === col.key ? { key: col.key, dir: -sort.dir } : { key: col.key, dir: col.text || col.asc ? 1 : -1 };
      renderTable();
      card.querySelector(`.sort-btn[data-key="${col.key}"]`)?.focus();
    }));
  }

  /** Tri stable ; les valeurs absentes restent en bas, quel que soit le sens. */
  function sortRows(list) {
    const col = COLUMNS.find((c) => c.key === sort.key);
    return list
      .map((r, i) => ({ r, i, v: col.value(r) }))
      .sort((a, b) => {
        const na = a.v === null || a.v === undefined || a.v === "";
        const nb = b.v === null || b.v === undefined || b.v === "";
        if (na || nb) return na === nb ? a.i - b.i : na ? 1 : -1;
        const cmp = col.text ? String(a.v).localeCompare(String(b.v), "fr", { sensitivity: "base" }) : a.v - b.v;
        return cmp * sort.dir || a.i - b.i;
      })
      .map((x) => x.r);
  }

  async function load() {
    const data = await latest(api.activities(period));
    if (data === STALE || !ctx.isCurrent()) return;
    rows = data;
    const types = [...new Set(rows.map((r) => r.type).filter(Boolean))]
      .sort((a, b) => activityTypeLabel(a).localeCompare(activityTypeLabel(b), "fr"));
    if (!types.includes(typeFilter)) typeFilter = "";
    typeSelect.innerHTML = `<option value="">Tous les types</option>` +
      types.map((t) => `<option value="${escapeHtml(t)}"${t === typeFilter ? " selected" : ""}>${escapeHtml(activityTypeLabel(t))}</option>`).join("");
    renderTable();
  }

  await load();
}
