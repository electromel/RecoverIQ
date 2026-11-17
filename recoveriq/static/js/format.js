// Mise en forme (paramètres régionaux fr-CH) et petits utilitaires d'interface.

const LOCALE = "fr-CH";

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

export function fmtNum(value, decimals = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString(LOCALE, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function fmtSigned(value, decimals = 0) {
  if (value === null || value === undefined) return "–";
  // Une valeur qui s'arrondit à zéro s'affiche « 0 » (et non « -0,0 »).
  if (Math.abs(value) < 0.5 * 10 ** -decimals) return fmtNum(0, decimals);
  return (value > 0 ? "+" : "") + fmtNum(value, decimals);
}

export const fmtDate = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(LOCALE) : "–");
export const fmtShortDate = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" }) : "–");
export const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" }) : "");

/** Secondes → « 1 h 05 » ou « 42 min ». */
export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  const totalMin = Math.round(seconds / 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
}

/** Heures décimales → « 7 h 24 ». */
export const fmtHours = (hours) => (hours === null || hours === undefined ? "–" : fmtDuration(hours * 3600));

/** Minutes décimales → « 5:40 » (allure, temps de course). */
export function fmtPace(minutes) {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "–";
  const total = Math.round(minutes * 60);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Secondes → « 4:07 » ou « 1:02:15 » (chronos). */
export function fmtChrono(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** Valeur d'un indicateur dans son unité (les heures sont affichées en h/min, les allures en m:ss). */
export function fmtValue(value, unit, decimals = 0) {
  if (value === null || value === undefined) return "–";
  if (unit === "h") return fmtHours(value);
  if (unit === "min/km") return `${fmtPace(value)} /km`;
  return fmtNum(value, decimals) + (unit ? ` ${unit}` : "");
}

/** Écart signé dans l'unité de l'indicateur (« +1 h 02 » pour les heures). */
export function fmtSignedValue(value, unit, decimals = 0) {
  if (value === null || value === undefined) return "–";
  if (unit === "h") return (value < 0 ? "−" : "+") + fmtHours(Math.abs(value));
  if (unit === "min/km") return (value < 0 ? "−" : "+") + fmtPace(Math.abs(value)) + " /km";
  return fmtSigned(value, decimals) + (unit ? ` ${unit}` : "");
}

export const badge =(text, cls = "muted") => `<span class="badge ${cls}">${escapeHtml(text)}</span>`;

// Libellés Garmin traduits ------------------------------------------------------

const TRAINING_STATUS = {
  PRODUCTIVE: "Productif", MAINTAINING: "Maintien", RECOVERY: "Récupération",
  UNPRODUCTIVE: "Improductif", DETRAINING: "Désentraînement", OVERREACHING: "Surmenage",
  PEAKING: "Pic de forme", STRAINED: "Sous tension", NO_STATUS: "Aucun statut", PAUSED: "En pause",
};
export const trainingStatusLabel = (code) =>
  code ? (TRAINING_STATUS[code] ?? code.replaceAll("_", " ").toLowerCase()) : "–";

const FOCUS_FEEDBACK = {
  BALANCED: "Équilibré",
  ANAEROBIC_SHORTAGE: "Manque d'anaérobie",
  AEROBIC_HIGH_SHORTAGE: "Manque d'aérobie haute",
  AEROBIC_LOW_SHORTAGE: "Manque d'aérobie basse",
  ANAEROBIC_FOCUS: "Focus anaérobie",
  AEROBIC_HIGH_FOCUS: "Focus aérobie haute",
  AEROBIC_LOW_FOCUS: "Focus aérobie basse",
  NO_DATA: "Pas assez de données",
};
export const focusFeedbackLabel = (code) =>
  code ? (FOCUS_FEEDBACK[code] ?? code.replaceAll("_", " ").toLowerCase()) : "";

const ACTIVITY_TYPES = {
  running: "Course", trail_running: "Trail", treadmill_running: "Course sur tapis", track_running: "Piste",
  cycling: "Vélo", road_biking: "Vélo de route", mountain_biking: "VTT", gravel_cycling: "Gravel",
  indoor_cycling: "Home trainer", virtual_ride: "Vélo virtuel", e_bike_mountain: "VTT électrique",
  hiking: "Randonnée", walking: "Marche", mountaineering: "Alpinisme",
  lap_swimming: "Natation", open_water_swimming: "Eau libre",
  strength_training: "Renforcement", cardio: "Cardio", hiit: "HIIT", yoga: "Yoga", pilates: "Pilates",
  resort_skiing_snowboarding_ws: "Ski alpin", backcountry_skiing: "Ski de randonnée",
  cross_country_skiing_ws: "Ski de fond", skate_skiing_ws: "Ski skating", snow_shoe_ws: "Raquettes",
  rowing: "Aviron", indoor_rowing: "Rameur", multi_sport: "Multisport", other: "Autre",
};
export const activityTypeLabel = (key) =>
  key ? (ACTIVITY_TYPES[key] ?? key.replaceAll("_", " ")) : "–";

// Préférences locales (sélecteur de période) : facultatives, jamais bloquantes.
export function loadPref(key, fallback) {
  try { return localStorage.getItem(`recoveriq.${key}`) ?? fallback; } catch { return fallback; }
}
export function savePref(key, value) {
  try { localStorage.setItem(`recoveriq.${key}`, value); } catch { /* stockage indisponible */ }
}

/**
 * Ne garde que la dernière requête : si l'utilisateur change de période pendant un
 * chargement, une réponse ancienne arrivée en retard est ignorée.
 * Usage : const latest = latestOnly(); … const data = await latest(api.x(p)); if (data === STALE) return;
 */
export const STALE = Symbol("stale");
export function latestOnly() {
  let seq = 0;
  return async (promise) => {
    const mine = ++seq;
    const result = await promise;
    return mine === seq ? result : STALE;
  };
}

/** Sélecteur de période commun à toutes les vues. */
export const PERIODS = [["30", "30 j"], ["90", "90 j"], ["365", "1 an"], ["all", "Tout"]];

export function periodSelector(current, onChange) {
  const el = document.createElement("div");
  el.className = "segmented";
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "Période");
  for (const [value, label] of PERIODS) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.classList.toggle("active", value === current);
    b.addEventListener("click", () => {
      el.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      savePref("period", value);
      onChange(value);
    });
    el.append(b);
  }
  return el;
}

export function exportLink(href) {
  const a = document.createElement("a");
  a.className = "button secondary";
  a.href = href;
  a.textContent = "Exporter CSV";
  return a;
}
