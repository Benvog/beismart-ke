// Small shared helpers: building elements safely, formatting, store colours, the browser watchlist.

// Build an element. Text always goes in as text (store titles are never treated as HTML).
// h("a", { class: "x", href: url, onclick: fn }, "text", childNode, [more, children])
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  append(el, children);
  return el;
}

// Replace an element's contents, skipping empty parts (null, false) like h() does.
export function fill(el, ...children) {
  el.replaceChildren();
  append(el, children);
}

function append(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(el, child);
    else el.append(child instanceof Node ? child : String(child));
  }
}

// SVG icons used across the screens (fixed markup, no data inside).
const ICONS = {
  heart: '<path d="M12 20.5s-7.5-4.6-9.3-9.3C1.4 7.8 3.6 4.5 7 4.5c2 0 3.6 1.1 5 3 1.4-1.9 3-3 5-3 3.4 0 5.6 3.3 4.3 6.7-1.8 4.7-9.3 9.3-9.3 9.3z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  box: '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16"/><path d="M20 20v-4h-4"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  chart: '<path d="M4 19V5M4 19h16"/><path d="m7 15 4-5 3 3 5-6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  bell: '<path d="M18 9a6 6 0 0 0-12 0c0 6.5-2.5 8-2.5 8h17S18 15.5 18 9"/><path d="M10.3 20.5a2 2 0 0 0 3.4 0"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  cart: '<path d="M2.5 3.5h2.6l2.3 11.2a1.6 1.6 0 0 0 1.6 1.3h8.4a1.6 1.6 0 0 0 1.6-1.2l1.6-6.8H6.2"/><circle cx="9.6" cy="20" r="1.4"/><circle cx="17.2" cy="20" r="1.4"/>',
};
export function icon(name, cls = "") {
  const span = document.createElement("span");
  span.className = `icon ${cls}`.trim();
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
  return span;
}

const KSH = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });
export const money = (n) => `KSh ${KSH.format(Math.round(n))}`;

export function timeAgo(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(seconds)) return "";
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} days ago`;
}

// Only real web addresses from scraped data are used as links and pictures.
export function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export const STORE_COLOURS = {
  "Jumia": "#f0a500",
  "Kilimall": "#8e24aa",
  "Avechi": "#2196f3",
  "Hotpoint": "#43a047",
  "Carrefour": "#1e5bc6",
  "Phone Place": "#0d9488",
  "Amazon": "#ff9800",
};
export const storeColour = (name) => STORE_COLOURS[name] || "#94a3b8";

export function storeDot(name) {
  const dot = h("span", { class: "store-dot", title: name });
  dot.style.setProperty("--dot", storeColour(name));
  return dot;
}


// ── Watchlist: products saved in this browser (no accounts, by decision) ──────

const WATCH_KEY = "beismart-watchlist";

export function watchlist() {
  try {
    return JSON.parse(localStorage.getItem(WATCH_KEY)) || [];
  } catch {
    return [];
  }
}

export const isWatched = (id) => watchlist().some((w) => w.id === id);

function saveWatchlist(list) {
  try {
    localStorage.setItem(WATCH_KEY, JSON.stringify(list));
  } catch { /* storage blocked: the heart just doesn't stick */ }
  document.dispatchEvent(new CustomEvent("watchlist-changed"));
}

// Saves what is needed to show and re-find the product later; returns the new state.
export function toggleWatch(group, query) {
  const list = watchlist();
  const watched = list.some((w) => w.id === group.id);
  saveWatchlist(watched
    ? list.filter((w) => w.id !== group.id)
    : [...list, { id: group.id, query, title: group.title, image_url: group.image_url,
                  price: group.best_price, saved_at: new Date().toISOString() }]);
  return !watched;
}

// Remove one saved item (returns it, so it can be put back with restoreWatch).
export function removeWatch(id) {
  const list = watchlist();
  const item = list.find((w) => w.id === id);
  saveWatchlist(list.filter((w) => w.id !== id));
  return item;
}

export function restoreWatch(item) {
  const list = watchlist().filter((w) => w.id !== item.id);
  saveWatchlist([...list, item]);
}
