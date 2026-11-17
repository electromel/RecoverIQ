// Connexion Garmin, synchronisation, données enregistrées et journal.
import { api } from "../api.js";
import { badge, escapeHtml, fmtDate, fmtDateTime } from "../format.js";

const POLL_MS = 3000;

const AUTH_LABELS = {
  not_configured: "Non configurée", connecting: "Connexion en cours…", connected: "Connecté",
  mfa_required: "Code de vérification requis", error: "Erreur",
};
const RUN_STATUS = {
  running: ["En cours", "muted"], success: ["Réussie", "ok"], partial: ["Partielle", "warn"],
  failed: ["Échec", "err"], interrupted: ["Interrompue", "warn"],
};
const TRIGGERS = {
  manual: "Manuelle", scheduler: "Planifiée", login: "Connexion", restore: "Démarrage", startup: "Démarrage",
};
const METRIC_STATE = {
  available: ["Disponible", "ok"], not_provided: ["Non fourni par la montre", "muted"],
  unknown: ["Pas encore interrogé", "muted"],
};

const TEMPLATE = `
  <h1>Synchronisation</h1>
  <section class="card">
    <h2>Connexion Garmin</h2>
    <p data-el="auth-status" class="status">Chargement…</p>
    <form data-el="login-form" hidden>
      <label>E-mail Garmin<input type="email" name="email" autocomplete="username" required></label>
      <label>Mot de passe<input type="password" name="password" autocomplete="current-password" required></label>
      <p class="small muted">Le mot de passe est stocké dans le Gestionnaire d'identifiants Windows, jamais en clair.</p>
      <button type="submit">Se connecter</button>
    </form>
    <form data-el="mfa-form" hidden>
      <label>Code de vérification (MFA)<input name="code" inputmode="numeric" autocomplete="one-time-code" required></label>
      <button type="submit">Valider</button>
    </form>
    <button data-el="logout-btn" class="secondary" hidden>Se déconnecter</button>
  </section>
  <section class="card">
    <div class="page-head">
      <h2>Synchronisation</h2>
      <div class="toolbar">
        <button data-el="sync-now-btn">Synchroniser maintenant</button>
        <button data-el="backfill-btn" class="secondary">Reprendre l'import historique</button>
      </div>
    </div>
    <p data-el="sync-message" class="status"></p>
    <p data-el="sync-live" class="status"></p>
    <div data-el="backfill-block">
      <div class="progress"><div data-el="backfill-bar"></div></div>
      <p data-el="backfill-text" class="muted"></p>
    </div>
  </section>
  <section class="card table-wrap">
    <h2>Données enregistrées</h2>
    <table><thead><tr><th>Indicateur</th><th>État</th><th class="num">Jours</th><th>Du</th><th>Au</th></tr></thead>
      <tbody data-el="overview-body"></tbody></table>
  </section>
  <section class="card table-wrap">
    <h2>Journal des synchronisations</h2>
    <table><thead><tr><th>Début</th><th>Type</th><th>Origine</th><th>Statut</th><th class="num">Jours</th>
      <th class="num">Appels</th><th class="num">Erreurs</th><th>Message</th></tr></thead>
      <tbody data-el="runs-body"></tbody></table>
  </section>`;

export async function render(view, _params, ctx) {
  view.innerHTML = TEMPLATE;
  const $ = (name) => view.querySelector(`[data-el="${name}"]`);

  function renderAuth(status) {
    const who = status.display_name || status.email;
    let text = AUTH_LABELS[status.state] ?? status.state;
    if (status.state === "connected" && who) text += ` (${who})`;
    if (status.message && status.state !== "not_configured") text += ` : ${status.message}`;
    $("auth-status").textContent = text;
    $("login-form").hidden = !["not_configured", "error"].includes(status.state);
    $("mfa-form").hidden = status.state !== "mfa_required";
    $("logout-btn").hidden = !["connected", "error"].includes(status.state) || !status.email;
    if (status.email && !$("login-form").email.value) $("login-form").email.value = status.email;
  }

  async function withButton(form, action) {
    const button = form.querySelector("button");
    button.disabled = true;
    try { return await action(); } finally { button.disabled = false; }
  }

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    $("auth-status").textContent = "Connexion à Garmin…";
    try {
      const status = await withButton(form, () => api.login(form.email.value, form.password.value));
      form.password.value = "";
      renderAuth(status);
    } catch (err) {
      $("auth-status").textContent = `Erreur : ${err.message}`;
    }
  });

  $("mfa-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      const status = await withButton(form, () => api.mfa(form.code.value));
      form.code.value = "";
      renderAuth(status);
    } catch (err) {
      $("auth-status").textContent = `Erreur : ${err.message}`;
    }
  });

  $("logout-btn").addEventListener("click", async () => {
    if (!confirm("Supprimer la session et le mot de passe Garmin enregistrés ? Les données déjà importées sont conservées.")) return;
    renderAuth(await api.logout());
  });

  function renderSync(status) {
    if (status.running) {
      const kind = status.kind === "backfill" ? "Import historique" : "Synchronisation";
      $("sync-live").textContent = `${kind} en cours : ${status.current ?? "…"} (${status.days_done} jour(s), ${status.errors} erreur(s))`;
    } else {
      const last = status.last_synced_date ? `Dernière synchronisation : ${fmtDate(status.last_synced_date)}.` : "Aucune synchronisation pour l'instant.";
      $("sync-live").textContent = last + (status.queued.length ? " En attente…" : "");
    }
    const bf = status.backfill;
    if (bf.start_date && bf.days_total) {
      const pct = Math.min(100, Math.round((100 * bf.days_done) / bf.days_total));
      $("backfill-bar").style.width = `${pct}%`;
      let text = `Import historique depuis le ${fmtDate(bf.start_date)} : ${bf.complete ? "terminé" : `${pct} %`} (${bf.days_done} / ${bf.days_total} jours)`;
      if (bf.pending_errors) text += `, ${bf.pending_errors} appel(s) à retenter`;
      $("backfill-text").textContent = text;
      $("backfill-block").hidden = false;
    } else {
      $("backfill-block").hidden = true;
    }
  }

  async function trigger(action) {
    try {
      const { message } = await action();
      $("sync-message").textContent = message;
      refresh();
    } catch (err) {
      $("sync-message").textContent = `Erreur : ${err.message}`;
    }
  }
  $("sync-now-btn").addEventListener("click", () => trigger(api.syncNow));
  $("backfill-btn").addEventListener("click", () => trigger(api.backfill));

  function renderOverview(rows) {
    $("overview-body").innerHTML = rows.map((r) => `<tr>
      <td>${escapeHtml(r.label)}</td>
      <td>${badge(...(METRIC_STATE[r.state] ?? [r.state, "muted"]))}</td>
      <td class="num">${r.rows}</td><td>${fmtDate(r.first_date)}</td><td>${fmtDate(r.last_date)}</td></tr>`).join("");
  }

  function renderRuns(runs) {
    if (!runs.length) {
      $("runs-body").innerHTML = `<tr><td colspan="8" class="muted">Aucune synchronisation enregistrée.</td></tr>`;
      return;
    }
    $("runs-body").innerHTML = runs.map((r) => {
      const errors = r.errors.length
        ? `<details><summary>${r.errors.length} détail(s)</summary><ul>${r.errors.map((e) =>
          `<li>${escapeHtml(e.date)} · ${escapeHtml(e.fetcher)} : ${escapeHtml(e.message)}</li>`).join("")}</ul></details>`
        : "";
      return `<tr>
        <td>${fmtDateTime(r.started_at)}</td>
        <td>${r.kind === "backfill" ? "Historique" : "Incrémentale"}</td>
        <td>${escapeHtml(TRIGGERS[r.trigger] ?? r.trigger)}</td>
        <td>${badge(...(RUN_STATUS[r.status] ?? [r.status, "muted"]))}</td>
        <td class="num">${r.days_processed}</td><td class="num">${r.api_calls}</td><td class="num">${r.errors_count}</td>
        <td>${escapeHtml(r.message)}${errors}</td></tr>`;
    }).join("");
  }

  let refreshing = false;
  async function refresh() {
    if (refreshing || !ctx.isCurrent()) return;
    refreshing = true;
    try {
      const [auth, sync, overview, runs] = await Promise.all([api.authStatus(), api.syncStatus(), api.overview(), api.runs()]);
      if (!ctx.isCurrent()) return;
      // Ne pas écraser le formulaire pendant la saisie.
      if (!view.contains(document.activeElement) || document.activeElement.tagName !== "INPUT") renderAuth(auth);
      renderSync(sync);
      renderOverview(overview);
      renderRuns(runs);
    } catch (err) {
      $("sync-live").textContent = `Serveur injoignable : ${err.message}`;
    } finally {
      refreshing = false;
    }
  }

  await refresh();
  const timer = setInterval(refresh, POLL_MS);
  ctx.onCleanup(() => clearInterval(timer));
}
