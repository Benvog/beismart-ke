// Where the data comes from. One interface, two sources:
//   "api"    the live FastAPI app (the local app on this PC)
//   "static" exported JSON files in data/ with the same shapes (the public demo on GitHub Pages)
// Screens only call the functions below and never know which source answered.
// ?source=api or ?source=static overrides the choice (remembered for the visit).

// The local app: this PC, or this PC opened from a phone on the same home network.
function isLocalHost(host) {
  return host === "localhost" || host === "127.0.0.1" || host.endsWith(".local")
    || /^(10|192\.168)\.\d+\.\d+(\.\d+)?$/.test(host) || /^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$/.test(host);
}

function chooseSource() {
  const asked = new URLSearchParams(location.search).get("source");
  try {
    if (asked === "api" || asked === "static") sessionStorage.setItem("beismart-source", asked);
    const saved = sessionStorage.getItem("beismart-source");
    if (saved) return saved;
  } catch { /* storage blocked: fall through */ }
  if (asked === "api" || asked === "static") return asked;
  return isLocalHost(location.hostname) ? "api" : "static";
}

export const source = chooseSource();
export const canRefresh = source === "api";   // re-scraping needs the local app
export const canEmail = source === "api";     // so do email alerts

// Same rule as beismart.store.normalize_query, plus a file-safe slug for the exported files.
export function normalizeQuery(q) {
  return q.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}
export function querySlug(q) {
  return normalizeQuery(q).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export class DataError extends Error {
  constructor(message, kind = "error") {
    super(message);
    this.kind = kind;   // "not_exported" | "unavailable" | "error"
  }
}

async function getJson(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch {
    throw new DataError("Could not reach the BeiSmart server.", "unavailable");
  }
  if (res.status === 404) return null;
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new DataError(typeof detail === "string" ? detail : `Request failed (${res.status}).`);
  }
  return res.json();
}

const api = {
  // show_hidden is always on: the screen decides whether to show the hidden junk.
  async search(q) {
    const params = new URLSearchParams({ q, limit: "200", show_hidden: "true" });
    return getJson(`api/search?${params}`);
  },
  async history(ids) {
    return getJson(`api/history?ids=${ids.join(",")}`);
  },
  async stores() {
    return (await getJson("api/stores")) || [];
  },
  async refresh(q) {
    return getJson(`api/refresh?q=${encodeURIComponent(q)}`, { method: "POST" });
  },
  async queries() {
    return null;   // the live app can search anything that was refreshed once
  },
  async drops() {
    return (await getJson("api/drops?limit=12")) || [];
  },
  async popular() {
    return (await getJson("api/popular")) || [];
  },
  // An email price alert (confirmation email first). body: { query, target_price, email, product_key?, label? }
  async watch(body) {
    return getJson("api/watches", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  },
};

const files = {
  async search(q) {
    const data = await getJson(`data/search/${querySlug(q)}.json`);
    if (!data) throw new DataError(`"${q}" is not in this demo.`, "not_exported");
    return data;
  },
  async history(ids) {
    return getJson(`data/history/${ids.slice().sort((a, b) => a - b).join("-")}.json`);
  },
  async stores() {
    return (await getJson("data/stores.json")) || [];
  },
  async refresh() {
    throw new DataError("Refreshing prices needs the local app.", "unavailable");
  },
  async queries() {
    const index = await getJson("data/index.json");
    return index ? index.queries : [];
  },
  async watch() {
    throw new DataError("Email alerts need the local app.", "unavailable");
  },
  async drops() {
    return (await getJson("data/drops.json")) || [];
  },
  async popular() {
    return files.queries();                     // the demo suggests the searches it holds
  },
};

const impl = source === "static" ? files : api;

export const search = (q) => impl.search(q);
export const history = (ids) => impl.history(ids);
export const stores = () => impl.stores();
export const refresh = (q) => impl.refresh(q);
export const queries = () => impl.queries();
export const watch = (body) => impl.watch(body);
export const drops = () => impl.drops();          // products whose best price fell this week, each with its search
export const popular = () => impl.popular();      // searches to suggest
