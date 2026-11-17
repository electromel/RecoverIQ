// Liste des activités, filtrable par type.
import { api, exportUrl } from "../api.js";
import {
  activityTypeLabel, escapeHtml, exportLink, fmtDateTime, fmtDuration, fmtNum, loadPref, periodSelector,
  latestOnly, STALE,
} from "../format.js";

export async function render(view, _params, ctx) {
  const latest = latestOnly();
  let period = loadPref("period", "90");
  let typeFilter = "";
  let rows = [];

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
    card.innerHTML = `<table>
      <thead><tr><th>Date</th><th>Type</th><th>Nom</th><th class="num">Durée</th><th class="num">Distance</th>
        <th class="num">D+</th><th class="num">FC moy / max</th><th class="num">Charge</th><th class="num">Effet aér. / anaér.</th></tr></thead>
      <tbody>${shown.map((r) => `<tr>
        <td>${fmtDateTime(r.start_local?.replace(" ", "T"))}</td>
        <td>${escapeHtml(activityTypeLabel(r.type))}</td>
        <td>${escapeHtml(r.name)}</td>
        <td class="num">${fmtDuration(r.duration_s)}</td>
        <td class="num">${r.distance_m ? `${fmtNum(r.distance_m / 1000, 2)} km` : "–"}</td>
        <td class="num">${r.elev_gain_m ? `${fmtNum(r.elev_gain_m)} m` : "–"}</td>
        <td class="num">${fmtNum(r.avg_hr)} / ${fmtNum(r.max_hr)}</td>
        <td class="num">${fmtNum(r.training_load)}</td>
        <td class="num">${fmtNum(r.aerobic_te, 1)} / ${fmtNum(r.anaerobic_te, 1)}</td>
      </tr>`).join("")}</tbody></table>`;
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
