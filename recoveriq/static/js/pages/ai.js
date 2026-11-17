// Analyse IA : lancement, suivi en direct, archives et lecture des rapports.
import { api } from "../api.js";
import { badge, escapeHtml, fmtDate, fmtDateTime, fmtNum, loadPref, savePref } from "../format.js";
import { periodLabel } from "./ai-settings.js";

const SEVERITY = { low: ["Faible", "muted"], medium: ["Modérée", "warn"], high: ["Élevée", "err"] };
const DIRECTION = { up: "↗ hausse", down: "↘ baisse", stable: "→ stable" };
const STATUS = {
  running: ["En cours", "muted"], success: ["Terminé", "ok"], partial: ["Partiel", "warn"], failed: ["Échec", "err"],
  ok: ["OK", "ok"], error: ["Erreur", "err"], timeout: ["Délai dépassé", "err"], invalid: ["Format invalide", "err"],
  pending: ["En attente", "muted"],
};
const MODE = {
  single: "Un seul fournisseur : rapport affiché tel quel.",
  llm: "Synthèse produite par l'agrégateur, complétée par la comparaison automatique.",
  fallback: "Comparaison automatique des rapports (synthèse par l'agrégateur indisponible).",
};

const statusBadge = (s) => badge(...(STATUS[s] ?? [s, "muted"]));
const severityBadge = (s) => badge(...(SEVERITY[s] ?? [s, "muted"]));

function fmtCost(cost, complete = true) {
  if (cost === null || cost === undefined) return "coût non estimé (tarifs non renseignés)";
  if (cost === 0 && complete) return "gratuit";
  const v = cost < 0.01 ? fmtNum(cost, 4) : fmtNum(cost, 2);
  return complete ? `≈ ${v} $` : `≥ ${v} $ (tarifs incomplets)`;
}

function list(items, render) {
  return items?.length ? `<ul>${items.map(render).join("")}</ul>` : `<p class="muted small">Aucun.</p>`;
}

function suggestionsHtml(items) {
  if (!items?.length) return `<p class="muted small">Aucune suggestion.</p>`;
  return `<ol class="suggestions">${items.map((s) =>
    `<li><div><b>${escapeHtml(s.title)}</b>${s.detail ? `<br><span class="muted">${escapeHtml(s.detail)}</span>` : ""}</div></li>`,
  ).join("")}</ol>`;
}

/** Rapport individuel au format imposé. */
function reportHtml(rep, metric) {
  const alerts = rep.alerts.length
    ? rep.alerts.map((a) => `<div class="alert-item ${a.severity}">
        ${severityBadge(a.severity)} <b>${escapeHtml(a.title)}</b> <span class="small muted">· ${escapeHtml(metric(a.metric))}</span>
        ${a.detail ? `<div class="small">${escapeHtml(a.detail)}</div>` : ""}</div>`).join("")
    : `<p class="muted small">Aucune alerte.</p>`;
  return `
    <div class="ai-section"><h3>Points clés</h3>${list(rep.highlights, (h) => `<li>${escapeHtml(h)}</li>`)}</div>
    <div class="ai-section"><h3>Tendances</h3>${list(rep.trends, (t) =>
      `<li><b>${escapeHtml(metric(t.metric))}</b> : ${DIRECTION[t.direction]}${t.comment ? ` — ${escapeHtml(t.comment)}` : ""}</li>`)}</div>
    <div class="ai-section"><h3>Alertes</h3>${alerts}</div>
    <div class="ai-section"><h3>Suggestions</h3>${suggestionsHtml(rep.suggestions)}</div>`;
}

function comparisonHtml(cmp, providerName, metric) {
  if (!cmp) return "";
  const who = (providers, withSeverity) => Object.entries(providers).map(([pid, v]) =>
    `${escapeHtml(providerName(pid))}${withSeverity ? ` ${severityBadge(v.severity)}` : ""}`).join(", ");
  const table = (rows, title, empty) => `<h3>${title}</h3>${rows.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Indicateur</th><th>Fournisseurs et sévérité</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${who(r.providers, true)}</td></tr>`).join("")}</tbody>
    </table></div>` : `<p class="muted small">${empty}</p>`}`;
  const trendRows = cmp.trends.filter((t) => Object.keys(t.providers).length > 1 || t.agreement === "conflict");
  const agreement = { agree: badge("Accord", "ok"), conflict: badge("Contradiction", "err"), partial: badge("Partiel", "muted") };
  return `<section class="card ai-section">
      <h2>Comparaison des modèles</h2>
      ${table(cmp.consensus_alerts, "Alertes partagées (consensus)", "Aucune alerte partagée par la majorité des modèles.")}
      ${table(cmp.severity_differences, "Écarts de sévérité", "Aucun écart de sévérité.")}
      ${table(cmp.isolated_alerts, "Alertes signalées par un seul modèle", "Aucune alerte isolée.")}
      <h3>Tendances</h3>
      ${trendRows.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Indicateur</th>${cmp.providers.map((p) => `<th>${escapeHtml(providerName(p))}</th>`).join("")}<th></th></tr></thead>
        <tbody>${trendRows.map((t) => `<tr><td>${escapeHtml(t.label ?? metric(t.metric))}</td>
          ${cmp.providers.map((p) => `<td>${t.providers[p] ? DIRECTION[t.providers[p]] : "–"}</td>`).join("")}
          <td>${agreement[t.agreement]}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted small">Pas de tendance citée par plusieurs modèles.</p>`}
    </section>`;
}

function resultDetails(r, providerName, metric, open) {
  const tokens = r.input_tokens !== null && r.input_tokens !== undefined
    ? ` · ${fmtNum(r.input_tokens)} + ${fmtNum(r.output_tokens)} jetons` : "";
  const timing = r.duration_ms ? ` · ${fmtNum(r.duration_ms / 1000, 1)} s` : "";
  const cost = r.status === "ok" || r.input_tokens ? ` · ${fmtCost(r.cost)}` : "";
  return `<details class="card" ${open ? "open" : ""}>
      <summary><b>${escapeHtml(providerName(r.provider))}</b> ${statusBadge(r.status)}
        <span class="small">${escapeHtml(r.model ?? "")}${timing}${tokens}${cost}</span></summary>
      ${r.error ? `<p class="bad small">${escapeHtml(r.error)}</p>` : ""}
      ${r.warnings?.length ? `<p class="small muted">Format corrigé : ${escapeHtml(r.warnings.join(" ; "))}</p>` : ""}
      ${r.report ? reportHtml(r.report, metric) : ""}
      ${!r.report && r.raw_text ? `<details><summary>Réponse brute</summary><pre class="json">${escapeHtml(r.raw_text)}</pre></details>` : ""}
    </details>`;
}

function reportDetailHtml(rep, providerName) {
  const metric = (k) => rep.metric_labels[k] ?? k;
  const ok = rep.results.filter((r) => r.status === "ok");
  const header = `<section class="card">
      <div class="page-head">
        <h2 style="margin:0">Rapport du ${fmtDate(rep.period_start)} au ${fmtDate(rep.period_end)}</h2>
        <div class="toolbar">${statusBadge(rep.status)}
          <button type="button" class="secondary" data-action="delete">Supprimer</button></div>
      </div>
      <p class="small muted">Créé le ${fmtDateTime(rep.created_at)} (${rep.trigger === "scheduler" ? "rapport hebdomadaire" : "à la demande"})
        · ${rep.period_days} jours · ${fmtCost(rep.total_cost, rep.cost_complete)}
        ${rep.synthesis_mode ? `<br>${MODE[rep.synthesis_mode]}` : ""}
        ${rep.aggregator_error ? `<br><span class="bad">Agrégateur ${escapeHtml(providerName(rep.aggregator))} : ${escapeHtml(rep.aggregator_error)}</span>` : ""}
        ${rep.error ? `<br><span class="bad">${escapeHtml(rep.error)}</span>` : ""}</p>
    </section>`;

  let main = "";
  if (rep.synthesis) {
    const s = rep.synthesis;
    main = `<section class="card ai-section">
        <h2>Synthèse <span class="small muted">par ${escapeHtml(providerName(rep.aggregator))} · ${escapeHtml(rep.aggregator_model ?? "")}</span></h2>
        <p>${escapeHtml(s.summary)}</p>
        <h3>Consensus</h3>${list(s.consensus, (c) => `<li>${escapeHtml(c)}</li>`)}
        <h3>Divergences</h3>${list(s.divergences, (d) => `<li>${escapeHtml(d)}</li>`)}
        <h3>Suggestions</h3>${suggestionsHtml(s.suggestions)}
      </section>`;
  } else if (ok.length === 1) {
    main = `<section class="card ai-section"><h2>${escapeHtml(providerName(ok[0].provider))}
      <span class="small muted">${escapeHtml(ok[0].model ?? "")}</span></h2>${reportHtml(ok[0].report, metric)}</section>`;
  }
  const individual = rep.results.length
    ? `<h2>Rapports individuels</h2>${rep.results.map((r) =>
      resultDetails(r, providerName, metric, rep.results.length === 1 && !r.report)).join("")}` : "";
  const sent = rep.summary ? `<details class="card"><summary>Données envoyées aux modèles (résumé agrégé)</summary>
      <pre class="json">${escapeHtml(JSON.stringify(rep.summary, null, 2))}</pre></details>` : "";
  return header + main + comparisonHtml(rep.comparison, providerName, metric) + individual + sent;
}

export async function render(view, params, ctx) {
  const settings = await api.aiSettings();
  const names = Object.fromEntries(settings.provider_list.map((p) => [p.id, p.label]));
  const providerName = (pid) => names[pid] ?? pid ?? "";
  const enabled = settings.provider_list.filter((p) => p.enabled);
  let period = Number(loadPref("aiPeriod", "7"));
  if (!settings.periods.includes(period)) period = 7;
  let selected = params[0] ? Number(params[0]) : null;

  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Analyse IA</h1>`;
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  const seg = document.createElement("div");
  seg.className = "segmented";
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", "Période analysée");
  for (const d of settings.periods) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = periodLabel(d);
    b.classList.toggle("active", d === period);
    b.addEventListener("click", () => {
      period = d;
      savePref("aiPeriod", String(d));
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
    });
    seg.append(b);
  }
  const runBtn = document.createElement("button");
  runBtn.type = "button";
  runBtn.textContent = "Analyser maintenant";
  toolbar.append(seg, runBtn);
  head.append(toolbar);

  const disclaimer = document.createElement("div");
  disclaimer.className = "notice disclaimer";
  disclaimer.textContent = settings.disclaimer;

  const providersInfo = document.createElement("p");
  providersInfo.className = "small muted";
  providersInfo.innerHTML = enabled.length
    ? `Fournisseurs actifs : ${enabled.map((p) => `<b>${escapeHtml(p.label)}</b> (${escapeHtml(p.model || "modèle ?")})`).join(", ")}
       · <a href="#/ai-settings">modifier</a>`
    : (() => {
      // Fournisseur configuré (clé ou adresse saisie) mais case « Activé » non cochée.
      const ready = settings.provider_list.filter((p) => p.has_key || (p.needs_base_url && p.base_url));
      return ready.length
        ? `${ready.map((p) => `<b>${escapeHtml(p.label)}</b>`).join(", ")} : configuré mais pas activé. Coche
           « Activé » sur la page <a href="#/ai-settings">Fournisseurs IA</a>.`
        : `Aucun fournisseur actif. <a href="#/ai-settings">Configurer un fournisseur</a> pour lancer une analyse.`;
    })();
  runBtn.disabled = !enabled.length;

  const live = document.createElement("div");
  const layout = document.createElement("div");
  layout.className = "ai-layout";
  const listCard = document.createElement("nav");
  listCard.className = "card";
  listCard.setAttribute("aria-label", "Rapports archivés");
  const detail = document.createElement("div");
  detail.className = "grid";
  layout.append(listCard, detail);
  view.append(head, disclaimer, providersInfo, live, layout);

  async function drawList() {
    const reports = await api.aiReports();
    if (!ctx.isCurrent()) return reports;
    listCard.innerHTML = `<h2>Archives</h2>` + (reports.length
      ? `<ul class="report-list">${reports.map((r) => `<li><a href="#/ai/${r.id}" class="${r.id === selected ? "active" : ""}">
          ${fmtDate(r.period_start)} → ${fmtDate(r.period_end)} ${statusBadge(r.status)}
          <div class="meta">${fmtDateTime(r.created_at)} · ${r.trigger === "scheduler" ? "hebdo" : "manuel"}
            · ${r.providers.map((p) => escapeHtml(providerName(p.provider))).join(", ") || "—"}</div></a></li>`).join("")}</ul>`
      : `<p class="muted small">Aucun rapport pour l'instant.</p>`);
    return reports;
  }

  async function drawDetail() {
    if (!selected) {
      detail.innerHTML = `<p class="muted">Lancez une analyse ou choisissez un rapport archivé.</p>`;
      return;
    }
    let rep;
    try {
      rep = await api.aiReport(selected);
    } catch (err) {
      detail.innerHTML = `<div class="notice">${escapeHtml(err.message)}</div>`;
      return;
    }
    if (!ctx.isCurrent()) return;
    if (rep.status === "running") {
      detail.innerHTML = `<p class="muted">Analyse en cours…</p>`;
      return;
    }
    detail.innerHTML = reportDetailHtml(rep, providerName);
    detail.querySelector('[data-action="delete"]')?.addEventListener("click", async () => {
      if (!confirm("Supprimer définitivement ce rapport archivé ?")) return;
      try {
        await api.aiDeleteReport(rep.id);
        location.hash = "#/ai";
      } catch (err) {
        alert(err.message);
      }
    });
  }

  // Suivi d'une analyse en cours (interrogation toutes les 2 s).
  let timer = null;
  let watching = false;   // vrai tant qu'une analyse suivie n'est pas terminée
  ctx.onCleanup(() => clearTimeout(timer));
  async function poll() {
    let st;
    try { st = await api.aiStatus(); } catch { st = { running: false }; }
    if (!ctx.isCurrent()) return;
    runBtn.disabled = st.running || !enabled.length;
    if (st.running) {
      watching = true;
      const steps = { summary: "préparation du résumé", providers: "interrogation des modèles", synthesis: "synthèse" };
      live.innerHTML = `<div class="card"><b>Analyse en cours</b> (${periodLabel(st.period_days)}) : ${steps[st.step] ?? ""}
        <div class="provider-states" style="margin-top:8px">${Object.entries(st.providers).map(([pid, s]) =>
          `<span>${escapeHtml(providerName(pid))} ${s === "running" ? badge("En cours…", "muted") : statusBadge(s)}</span>`).join("")}</div></div>`;
      timer = setTimeout(poll, 2000);
    } else if (watching) {
      // Fin d'analyse : on affiche le rapport qui vient d'être produit.
      watching = false;
      live.innerHTML = "";
      if (st.report_id) {
        if (selected === st.report_id) { await drawList(); await drawDetail(); }
        else location.hash = `#/ai/${st.report_id}`;
      }
    }
  }

  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    try {
      const { report_id: id } = await api.aiAnalyze(period);
      live.innerHTML = `<div class="card"><b>Analyse lancée…</b></div>`;
      watching = true;
      selected = id;
      await drawList();
      detail.innerHTML = `<p class="muted">Analyse en cours…</p>`;
      history.replaceState(null, "", `#/ai/${id}`);
      poll();
    } catch (err) {
      live.innerHTML = `<div class="notice bad">${escapeHtml(err.message)}</div>`;
      runBtn.disabled = false;
    }
  });

  const reports = await drawList();
  if (!selected && reports.length) {
    selected = reports[0].id;
    listCard.querySelector(`a[href="#/ai/${selected}"]`)?.classList.add("active");
  }
  await drawDetail();
  await poll();   // reprend le suivi si une analyse tourne déjà
}
