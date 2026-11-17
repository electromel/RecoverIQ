// Matériel : montres ayant enregistré les activités, de la plus ancienne à la plus récente.
import { api, exportUrl } from "../api.js";
import { activityTypeLabel, escapeHtml, exportLink, fmtDate, fmtDuration, fmtNum } from "../format.js";

export async function render(view, _params, ctx) {
  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Matériel</h1>`;
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  toolbar.append(exportLink(exportUrl.devices()));
  head.append(toolbar);

  const card = document.createElement("div");
  card.className = "card table-wrap";
  const note = document.createElement("p");
  note.className = "small muted";
  note.textContent = "Garmin donne l'identifiant de la montre avec chaque activité ; le nom du modèle vient du statut "
    + "d'entraînement. Certaines activités anciennes n'indiquent aucune montre, et l'identifiant 0 ne désigne pas de montre réelle.";
  view.append(head, card, note);

  const rows = await api.devices();
  if (!ctx.isCurrent()) return;
  if (!rows.length) {
    card.innerHTML = `<p class="muted">Aucune activité importée.</p>`;
    return;
  }
  const period = (r) => {
    if (!r.first_date) return "–";
    return r.first_date === r.last_date ? fmtDate(r.first_date) : `${fmtDate(r.first_date)} – ${fmtDate(r.last_date)}`;
  };
  const types = (r) => r.types.slice(0, 4)
    .map((t) => `${escapeHtml(activityTypeLabel(t.type))} (${t.count})`).join(", ")
    + (r.types.length > 4 ? `, <span class="muted">+${r.types.length - 4} autres</span>` : "");
  card.innerHTML = `<table>
    <thead><tr><th>Montre</th><th>Période</th><th class="num">Activités</th><th class="num">Durée</th>
      <th class="num">Distance</th><th class="num">D+</th><th>Principaux types</th><th class="num">Identifiant Garmin</th></tr></thead>
    <tbody>${rows.map((r) => `<tr>
      <td>${r.name ? `<strong>${escapeHtml(r.label)}</strong>` : `<span class="muted">${escapeHtml(r.label)}</span>`}</td>
      <td>${period(r)}</td>
      <td class="num">${fmtNum(r.activities)}</td>
      <td class="num">${r.duration_s ? fmtDuration(r.duration_s) : "–"}</td>
      <td class="num">${r.distance_m ? `${fmtNum(r.distance_m / 1000)} km` : "–"}</td>
      <td class="num">${r.elev_gain_m ? `${fmtNum(r.elev_gain_m)} m` : "–"}</td>
      <td>${types(r) || "–"}</td>
      <td class="num muted">${r.device_id ?? "–"}</td>
    </tr>`).join("")}</tbody></table>`;
}
