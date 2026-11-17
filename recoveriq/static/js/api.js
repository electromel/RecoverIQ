// Client HTTP minimal pour l'API RecoverIQ.

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch { /* corps non JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

const q = (period) => `period=${encodeURIComponent(period)}`;

export const api = {
  // Connexion et synchronisation
  authStatus: () => request("GET", "/api/auth/status"),
  login: (email, password) => request("POST", "/api/auth/login", { email, password }),
  mfa: (code) => request("POST", "/api/auth/mfa", { code }),
  logout: () => request("POST", "/api/auth/logout"),
  syncStatus: () => request("GET", "/api/sync/status"),
  syncNow: () => request("POST", "/api/sync/now"),
  backfill: () => request("POST", "/api/sync/backfill"),
  runs: (limit = 30) => request("GET", `/api/sync/runs?limit=${limit}`),
  overview: () => request("GET", "/api/data/overview"),
  // Tableau de bord
  catalog: () => request("GET", "/api/catalog"),
  home: () => request("GET", "/api/home"),
  series: (key, period) => request("GET", `/api/series/${encodeURIComponent(key)}?${q(period)}`),
  day: (iso) => request("GET", `/api/day/${encodeURIComponent(iso)}`),
  training: (period) => request("GET", `/api/training?${q(period)}`),
  activities: (period) => request("GET", `/api/activities?${q(period)}`),
  correlations: (period) => request("GET", `/api/correlations?${q(period)}`),
  devices: () => request("GET", "/api/devices"),
  // Analyse IA
  aiSettings: () => request("GET", "/api/ai/settings"),
  aiSaveSettings: (body) => request("PUT", "/api/ai/settings", body),
  aiSaveProvider: (id, body) => request("PUT", `/api/ai/providers/${encodeURIComponent(id)}`, body),
  aiTestProvider: (id, body) => request("POST", `/api/ai/providers/${encodeURIComponent(id)}/test`, body),
  aiAnalyze: (periodDays) => request("POST", "/api/ai/analyze", { period_days: periodDays }),
  aiStatus: () => request("GET", "/api/ai/status"),
  aiReports: (limit = 50) => request("GET", `/api/ai/reports?limit=${limit}`),
  aiReport: (id) => request("GET", `/api/ai/reports/${id}`),
  aiDeleteReport: (id) => request("DELETE", `/api/ai/reports/${id}`),
  aiOpenLink: (provider, kind) => request("POST", "/api/ai/open-link", { provider, kind }),
  aiSummary: (periodDays) => request("GET", `/api/ai/summary?period_days=${periodDays}`),
};

// Liens d'export CSV (téléchargement direct par le navigateur).
export const exportUrl = {
  home: () => "/api/export/home.csv",
  series: (key, period) => `/api/export/series/${encodeURIComponent(key)}.csv?${q(period)}`,
  training: (period) => `/api/export/training.csv?${q(period)}`,
  activities: (period) => `/api/export/activities.csv?${q(period)}`,
  correlations: (period) => `/api/export/correlations.csv?${q(period)}`,
  devices: () => "/api/export/devices.csv",
};
