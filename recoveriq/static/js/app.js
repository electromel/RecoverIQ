// Routeur monopage (hash) : chaque vue est un module de ./pages exposant render(view, params, ctx).
import { api } from "./api.js";
import { escapeHtml, fmtDate } from "./format.js";

const ROUTES = {
  "": () => import("./pages/home.js"),
  metric: () => import("./pages/metric.js"),
  day: () => import("./pages/day.js"),
  training: () => import("./pages/training.js"),
  activities: () => import("./pages/activities.js"),
  correlations: () => import("./pages/correlations.js"),
  sync: () => import("./pages/sync.js"),
  ai: () => import("./pages/ai.js"),
  "ai-settings": () => import("./pages/ai-settings.js"),
};

const view = document.getElementById("view");
let cleanups = [];
let renderToken = 0;

/** Contexte passé aux pages : enregistre graphiques et minuteries à libérer au changement de vue. */
function makeContext(token) {
  return {
    track(chart) { cleanups.push(() => chart.destroy()); return chart; },
    onCleanup(fn) { cleanups.push(fn); },
    isCurrent: () => token === renderToken,
  };
}

async function route() {
  const [name = "", ...params] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const loader = ROUTES[name] ?? ROUTES[""];

  cleanups.forEach((fn) => { try { fn(); } catch { /* déjà libéré */ } });
  cleanups = [];
  const token = ++renderToken;

  document.querySelectorAll(".nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === ((name === "day" ? "metric" : name) || "home"));
  });
  view.innerHTML = `<p class="muted">Chargement…</p>`;
  try {
    const page = await loader();
    if (token !== renderToken) return;
    view.innerHTML = "";
    await page.render(view, params, makeContext(token));
  } catch (err) {
    if (token !== renderToken) return;
    view.innerHTML = `<div class="notice">Erreur d'affichage : ${escapeHtml(err.message)}</div>`;
    console.error(err);
  }
}

// Badge d'état de synchronisation (bas de la barre latérale).
async function refreshBadge() {
  const el = document.getElementById("sync-badge");
  try {
    const [auth, sync] = await Promise.all([api.authStatus(), api.syncStatus()]);
    const parts = [];
    if (auth.state !== "connected") parts.push("⚠ Garmin non connecté");
    if (sync.running) {
      parts.push(sync.kind === "backfill" ? "Import historique en cours" : "Synchronisation en cours");
    } else if (sync.last_synced_date) {
      parts.push(`Synchronisé le ${fmtDate(sync.last_synced_date)}`);
    }
    const bf = sync.backfill;
    if (bf.days_total && !bf.complete) {
      parts.push(`Historique : ${Math.min(100, Math.round((100 * bf.days_done) / bf.days_total))} %`);
    }
    el.innerHTML = parts.map((p) => `<div>${escapeHtml(p)}</div>`).join("");
  } catch {
    el.textContent = "Serveur injoignable";
  }
}

window.addEventListener("hashchange", route);
route();
refreshBadge();
setInterval(refreshBadge, 10000);
