/* Shared auth helpers — session token storage, authenticated fetch, profile cache.
   Included by landing.html, onboarding.html and index.html via <script src="/auth.js">. */

const DM_TOKEN_KEY = "dm_token";
const DM_CACHE_KEYS = [
  "user_profile",
  "wedding_project",
  "venue_statuses",
  "contacted_venues",
  "activity_feed",
  "dm_fresh_account",
];

function getToken() {
  return localStorage.getItem(DM_TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(DM_TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(DM_TOKEN_KEY);
}

// Drops the token and every cached server-derived key.
function clearAuthCache() {
  clearToken();
  DM_CACHE_KEYS.forEach(k => localStorage.removeItem(k));
}

// Writes a UserResponse payload (register/login/profile) into the localStorage
// cache so pages keep working offline; the server stays the source of truth.
function cacheProfile(data) {
  try {
    localStorage.setItem("user_profile", JSON.stringify({ name: data.name, email: data.email }));
    if (data.wedding_project) localStorage.setItem("wedding_project", JSON.stringify(data.wedding_project));
    localStorage.setItem("venue_statuses", JSON.stringify(data.venue_statuses || {}));
    localStorage.setItem("contacted_venues", JSON.stringify(data.contacted_venues || {}));
    localStorage.setItem("activity_feed", JSON.stringify(data.activity_feed || []));
  } catch (e) {}
}

// fetch() wrapper that injects the Bearer token. On 401 the session is gone:
// clear local state and send the user to the login tab — unless the caller
// opts out with { on401: "ignore" } (e.g. the landing page redirect check).
async function authFetch(url, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(url, Object.assign({}, opts, { headers }));

  if (res.status === 401 && opts.on401 !== "ignore") {
    clearAuthCache();
    const lang = localStorage.getItem("preferred_language") || localStorage.getItem("ob_lang") || "fr";
    window.location.href = `/onboarding.html?lang=${lang}&mode=login`;
    throw new Error("session_expired");
  }
  return res;
}
