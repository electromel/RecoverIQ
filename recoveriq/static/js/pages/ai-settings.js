// Réglages de l'analyse IA : fournisseurs (activation, clé, modèle, tarifs, test) et options générales.
// Les clés API sont envoyées une seule fois au serveur local, qui les range dans le
// Gestionnaire d'identifiants Windows ; elles ne sont jamais relues par la page.
import { api } from "../api.js";
import { escapeHtml, fmtDateTime } from "../format.js";

export const WEEKDAY_LABELS = {
  mon: "Lundi", tue: "Mardi", wed: "Mercredi", thu: "Jeudi", fri: "Vendredi", sat: "Samedi", sun: "Dimanche",
};
export const periodLabel = (d) => (d === 365 ? "1 an" : `${d} j`);

// Lien externe (création de clé, tarifs). Le clic est confié au serveur local, qui ouvre la
// page dans le navigateur par défaut de Windows : cela fonctionne même quand l'appli est
// affichée dans une fenêtre qui bloque les nouveaux onglets. href reste en secours.
const extLink = (url, text, provider, kind) =>
  `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" data-provider="${provider}"
     data-kind="${kind}">${escapeHtml(text)} ↗</a>`;

async function openExternal(link) {
  try {
    await api.aiOpenLink(link.dataset.provider, link.dataset.kind);
  } catch {
    window.open(link.href, "_blank", "noopener,noreferrer");
  }
}

const numOrNull = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

function providerCard(p, onSaved) {
  const card = document.createElement("section");
  card.className = "card provider-card";
  card.dataset.id = p.id;
  const id = `p-${p.id}`;
  card.innerHTML = `
    <div class="page-head">
      <h2 style="margin:0">${escapeHtml(p.label)}</h2>
      <label class="switch" title="Pris en compte immédiatement">
        <input type="checkbox" name="enabled" ${p.enabled ? "checked" : ""}> Activé</label>
    </div>
    <div class="row">
      <label>Clé API${p.needs_key ? "" : " (facultative)"}
        <input type="password" name="api_key" autocomplete="off" spellcheck="false"
          placeholder="${p.has_key ? "•••••••• enregistrée — saisir pour remplacer" : "non enregistrée"}">
        <span class="small muted">${escapeHtml(p.key_help)}
          ${p.key_url ? ` ${extLink(p.key_url, p.id === "custom" ? "Utiliser Ollama" : "Créer ou gérer mes clés", p.id, "key")}` : ""}</span>
      </label>
      <label>Modèle
        <input name="model" list="${id}-models" value="${escapeHtml(p.model ?? "")}" spellcheck="false"
          placeholder="Tester la connexion pour lister les modèles">
        <datalist id="${id}-models"></datalist>
      </label>
    </div>
    <div class="row">
      <label>Adresse de l'API${p.needs_base_url ? "" : " (par défaut si vide)"}
        <input name="base_url" value="${escapeHtml(p.base_url ?? "")}" spellcheck="false"
          placeholder="${escapeHtml(p.default_base_url ?? "http://localhost:11434/v1")}">
      </label>
      <label>Tarif entrée ($ / million de jetons)
        <input name="price_in" type="number" min="0" step="0.01" value="${p.price_in ?? ""}" placeholder="non renseigné">
      </label>
      <label>Tarif sortie ($ / million de jetons)
        <input name="price_out" type="number" min="0" step="0.01" value="${p.price_out ?? ""}" placeholder="non renseigné">
        ${p.pricing_url ? `<span class="small muted">${extLink(p.pricing_url, "Voir les tarifs", p.id, "pricing")}</span>` : ""}
      </label>
    </div>
    <div class="actions">
      <button type="button" data-action="save">Enregistrer</button>
      <button type="button" class="secondary" data-action="test">Tester la connexion</button>
      ${p.has_key ? `<button type="button" class="secondary" data-action="delete-key">Supprimer la clé</button>` : ""}
      <span class="small" data-role="result" aria-live="polite"></span>
    </div>`;

  const field = (name) => card.querySelector(`[name="${name}"]`);
  const result = card.querySelector('[data-role="result"]');
  const show = (text, cls = "muted") => { result.className = `small ${cls}`; result.textContent = text; };

  // La case « Activé » est enregistrée dès qu'on la coche : c'est elle qui décide si le
  // fournisseur est interrogé, elle ne doit pas dépendre d'un clic sur « Enregistrer ».
  field("enabled").addEventListener("change", async (ev) => {
    const enabled = ev.target.checked;
    try {
      await api.aiSaveProvider(p.id, { enabled });
      p.enabled = enabled;
      const noKey = enabled && p.needs_key && !p.has_key && !field("api_key").value.trim();
      if (noKey) show("✔ Activé — mais aucune clé enregistrée : saisis-la puis « Enregistrer ».", "warn");
      else show(enabled ? "✔ Activé" : "Désactivé : ne sera plus interrogé.", enabled ? "good" : "muted");
    } catch (err) {
      ev.target.checked = !enabled;
      show(`✖ ${err.message}`, "bad");
    }
  });

  // Signale les saisies pas encore enregistrées (clé, modèle, adresse, tarifs).
  card.addEventListener("input", (ev) => {
    if (ev.target.name && ev.target.name !== "enabled") show("Modifications non enregistrées", "warn");
  });

  async function save(extra = {}) {
    const priceIn = numOrNull(field("price_in").value);
    const priceOut = numOrNull(field("price_out").value);
    const body = {
      enabled: field("enabled").checked,
      model: field("model").value,
      base_url: field("base_url").value,
      ...extra,
    };
    if (priceIn === null && priceOut === null) body.clear_prices = true;
    else Object.assign(body, { price_in: priceIn ?? 0, price_out: priceOut ?? 0 });
    const key = field("api_key").value.trim();
    if (key && !extra.delete_key) body.api_key = key;
    const settings = await api.aiSaveProvider(p.id, body);
    field("api_key").value = "";
    onSaved(settings, p.id);
  }

  card.addEventListener("click", async (ev) => {
    const link = ev.target.closest("a[data-kind]");
    if (link) {
      ev.preventDefault();      // évite aussi que le clic dans le <label> active le champ
      ev.stopPropagation();
      await openExternal(link);
      return;
    }
    const action = ev.target.closest("button")?.dataset.action;
    if (!action) return;
    const button = ev.target.closest("button");
    button.disabled = true;
    try {
      if (action === "save") {
        await save();
      } else if (action === "delete-key") {
        if (confirm(`Supprimer la clé ${p.label} du Gestionnaire d'identifiants Windows ?`)) {
          await save({ delete_key: true });
        }
      } else if (action === "test") {
        show("Test en cours…");
        const res = await api.aiTestProvider(p.id, {
          api_key: field("api_key").value || null,
          model: field("model").value || null,
          base_url: field("base_url").value || null,
        });
        card.querySelector("datalist").innerHTML =
          res.models.map((m) => `<option value="${escapeHtml(m)}">`).join("");
        show(`${res.ok ? "✔" : "✖"} ${res.message} (${res.duration_ms} ms)`, res.ok ? "good" : "bad");
      }
    } catch (err) {
      show(`✖ ${err.message}`, "bad");
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  });
  return card;
}

function globalCard(s, onSaved) {
  const card = document.createElement("section");
  card.className = "card ai-global";
  card.dataset.id = "global";
  const agg = [["auto", "Automatique (premier fournisseur ayant répondu)"], ["", "Aucun : comparaison simple"],
    ...s.provider_list.map((p) => [p.id, p.label])];
  const w = s.weekly;
  card.innerHTML = `
    <h2>Options générales</h2>
    <div class="provider-card"><div class="row">
      <label>Agrégateur (synthèse multi-modèles)
        <select name="aggregator">${agg.map(([v, l]) =>
          `<option value="${v}" ${v === s.aggregator ? "selected" : ""}>${escapeHtml(l)}</option>`).join("")}</select>
      </label>
      <label>Délai maximal par fournisseur (s)
        <input name="timeout_s" type="number" min="10" max="600" value="${s.timeout_s}">
      </label>
    </div>
    <h3 style="margin-top:6px">Rapport hebdomadaire automatique</h3>
    <div class="row">
      <label class="switch"><input type="checkbox" name="weekly_enabled" ${w.enabled ? "checked" : ""}> Activé</label>
      <label>Jour
        <select name="weekly_day">${s.weekdays.map((d) =>
          `<option value="${d}" ${d === w.day ? "selected" : ""}>${WEEKDAY_LABELS[d]}</option>`).join("")}</select>
      </label>
      <label>Heure <input name="weekly_time" type="time" value="${escapeHtml(w.time)}"></label>
      <label>Période analysée
        <select name="weekly_period">${s.periods.map((d) =>
          `<option value="${d}" ${d === w.period_days ? "selected" : ""}>${periodLabel(d)}</option>`).join("")}</select>
      </label>
    </div>
    <div class="actions">
      <button type="button" data-action="save">Enregistrer</button>
      <span class="small" data-role="result" aria-live="polite"></span>
    </div></div>`;
  const f = (n) => card.querySelector(`[name="${n}"]`);
  const result = card.querySelector('[data-role="result"]');
  card.querySelector('[data-action="save"]').addEventListener("click", async () => {
    try {
      const saved = await api.aiSaveSettings({
        aggregator: f("aggregator").value,
        timeout_s: Number(f("timeout_s").value),
        weekly: {
          enabled: f("weekly_enabled").checked, day: f("weekly_day").value,
          time: f("weekly_time").value, period_days: Number(f("weekly_period").value),
        },
      });
      onSaved(saved, "global");
    } catch (err) {
      result.className = "small bad";
      result.textContent = `✖ ${err.message}`;
    }
  });
  return card;
}

export async function render(view, _params, ctx) {
  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Fournisseurs IA</h1><a class="button secondary" href="#/ai">Analyse IA →</a>`;
  const intro = document.createElement("p");
  intro.className = "muted";
  intro.innerHTML = `Activez un ou plusieurs fournisseurs : ils sont interrogés en parallèle. Les clés sont rangées dans le
    <b>Gestionnaire d'identifiants Windows</b>, jamais en clair ni dans la base. Seul un résumé statistique agrégé leur est
    envoyé, jamais les données journalières. Les tarifs (page « Pricing » de chaque fournisseur) servent à estimer le coût.`;
  const body = document.createElement("div");
  body.className = "grid";
  view.append(head, intro, body);

  const next = document.createElement("p");
  next.className = "small muted";
  async function refreshNextRun() {
    const status = await api.aiStatus();
    next.textContent = status.next_weekly_run
      ? `Prochain rapport automatique : ${fmtDateTime(status.next_weekly_run)}` : "Rapport automatique désactivé.";
  }

  const build = (settings, id) => (id === "global"
    ? globalCard(settings, onSaved)
    : providerCard(settings.provider_list.find((p) => p.id === id), onSaved));

  // Après un enregistrement, seule la carte concernée est redessinée : les saisies en cours
  // dans les autres cartes sont conservées.
  async function onSaved(settings, id) {
    if (!ctx.isCurrent()) return;
    const card = build(settings, id);
    body.querySelector(`[data-id="${id}"]`).replaceWith(card);
    const flash = card.querySelector('[data-role="result"]');
    flash.className = "small good";
    flash.textContent = "✔ Enregistré";
    if (id === "global") await refreshNextRun();
  }

  const settings = await api.aiSettings();
  await refreshNextRun();
  body.append(build(settings, "global"), next, ...settings.provider_list.map((p) => build(settings, p.id)));
}
