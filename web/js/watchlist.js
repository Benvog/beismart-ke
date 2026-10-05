// The watchlist (watchlist.html): products saved with the heart, kept in this browser (no accounts).
// Each saved item remembers its search and the price when saved; today's price is looked up from that search
// (one lookup per search), so the screen shows how each price moved since it was saved.

import { h, fill, icon, money, safeUrl, storeDot, timeAgo, watchlist, removeWatch, restoreWatch } from "./util.js";
import { renderShell } from "./shell.js";
import { inStock } from "./card.js";
import * as data from "./data.js";

const SORTS = [
  { id: "recent", label: "Recently saved", order: (a, b) => b.item.saved_at.localeCompare(a.item.saved_at) },
  { id: "drop", label: "Biggest drop", order: (a, b) => change(a) - change(b) },
  { id: "price", label: "Cheapest", order: (a, b) => (a.group?.best_price ?? Infinity) - (b.group?.best_price ?? Infinity) },
];

const main = document.getElementById("main");
let sort = "recent";
let rows = [];             // [{ item, group | null }]
let toastTimer = null;

renderShell();
document.title = "Watchlist · BeiSmart KE";
load();
window.addEventListener("storage", load);       // changed in another tab

// KSh change since saved (negative = cheaper); unknown products sort last.
function change(row) {
  return row.group ? row.group.best_price - row.item.price : Infinity;
}

async function load() {
  const items = watchlist();
  if (!items.length) return renderEmpty();
  renderLoading(items.length);
  const queries = [...new Set(items.map((i) => i.query))];
  const results = new Map(await Promise.all(queries.map(async (q) => [q, await data.search(q).catch(() => null)])));
  rows = items.map((item) => ({ item, group: results.get(item.query)?.groups.find((g) => g.id === item.id) || null }));
  render();
}

function renderLoading(n) {
  fill(main, head(n, null), h("div", { class: "watch-list" }, Array.from({ length: Math.min(n, 4) }, () =>
    h("div", { class: "watch-row skeleton" }, h("div", { class: "tile watch-thumb" }), h("div", { class: "watch-main" },
      h("span", { class: "sk sk-line" }), h("span", { class: "sk sk-line short" }))))));
}

function head(n, summaryBar) {
  return h("section", { class: "results-head" },
    h("div", {},
      h("h1", {}, "Your watchlist"),
      h("p", { class: "meta" }, `${n} saved product${n === 1 ? "" : "s"} · kept in this browser`)),
    summaryBar);
}

function summary() {
  const known = rows.filter((r) => r.group);
  const cheaper = known.filter((r) => change(r) < 0);
  const saved = cheaper.reduce((sum, r) => sum - change(r), 0);
  const item = (value, label, cls = "") => h("div", {}, h("div", { class: `summary-value ${cls}` }, value), h("div", { class: "summary-label" }, label));
  return h("div", { class: "summary" },
    item(String(cheaper.length), "Cheaper since saved", cheaper.length ? "good" : ""),
    saved > 0 && item(money(saved), "Total price drops", "good"));
}

function render() {
  if (!rows.length) return renderEmpty();
  const order = SORTS.find((s) => s.id === sort).order;
  const sorted = [...rows].sort(order);
  fill(main,
    head(rows.length, summary()),
    h("div", { class: "toolbar" },
      h("div", { class: "segmented", role: "radiogroup", "aria-label": "Sort watchlist" }, SORTS.map((s) =>
        h("button", { type: "button", role: "radio", "aria-checked": String(s.id === sort), class: s.id === sort ? "active" : "",
                      onclick: () => { sort = s.id; render(); } }, s.label))),
      h("p", { class: "notice subtle" }, "Want an email when a price falls? Open a product and set an alert.")),
    h("div", { class: "watch-list" }, sorted.map(watchRow)));
}

function watchRow({ item, group }) {
  const href = `product.html?${new URLSearchParams({ q: item.query, id: item.id })}`;
  const img = safeUrl(group?.image_url || item.image_url);
  const thumb = h("a", { class: "tile watch-thumb", href, tabindex: "-1", "aria-hidden": "true" },
    img ? h("img", { src: img, alt: "", loading: "lazy", referrerpolicy: "no-referrer",
                     onerror: (e) => e.target.replaceWith(h("span", { class: "tile-empty" }, "🛒")) })
        : h("span", { class: "tile-empty" }, "🛒"));

  let status;
  if (!group) {
    status = h("span", { class: "watch-change gone" }, "Not in today's listings");
  } else {
    const diff = change({ item, group });
    status = diff < 0 ? h("span", { class: "watch-change down" }, icon("arrow", "turn-down"), `${money(-diff)} cheaper`)
      : diff > 0 ? h("span", { class: "watch-change up" }, icon("arrow", "turn-up"), `${money(diff)} dearer`)
      : h("span", { class: "watch-change same" }, "Same price");
  }
  const stores = group ? [...new Set(group.members.map((m) => m.store))] : [];

  return h("article", { class: `watch-row${group ? "" : " missing"}${group && !inStock(group) ? " sold-out" : ""}` },
    thumb,
    h("div", { class: "watch-main" },
      h("a", { class: "watch-title", href, title: group?.title || item.title }, group?.title || item.title),
      h("p", { class: "card-stores" },
        stores.length > 0 && h("span", { class: "dots" }, stores.map(storeDot)),
        h("span", { class: "names" }, stores.length ? stores.join(", ") : `from “${item.query}”`),
        h("span", { class: "watch-saved" }, ` · saved ${timeAgo(item.saved_at)}`))),
    h("div", { class: "watch-price" },
      group ? h("span", { class: "price" }, money(group.best_price)) : h("span", { class: "price faded" }, money(item.price)),
      h("span", { class: "watch-then" }, `Saved at ${money(item.price)}`),
      status),
    h("div", { class: "watch-actions" },
      group && h("a", { class: "sr-go", href: `${href}#alert`, title: "Email me when it drops" }, icon("bell"), h("span", { class: "label" }, "Alert")),
      h("button", { class: "icon-btn watch-remove", type: "button", "aria-label": `Remove ${item.title} from watchlist`, title: "Remove",
                    onclick: () => remove(item.id) }, icon("close"))));
}

function remove(id) {
  const item = removeWatch(id);
  rows = rows.filter((r) => r.item.id !== id);
  render();
  if (item) toast(`Removed “${item.title.slice(0, 40)}${item.title.length > 40 ? "…" : ""}”`, () => { restoreWatch(item); load(); });
}

function toast(text, undo) {
  document.querySelector(".toast")?.remove();
  clearTimeout(toastTimer);
  const el = h("div", { class: "toast", role: "status" }, h("span", {}, text),
    h("button", { class: "link", type: "button", onclick: () => { el.remove(); undo(); } }, "Undo"));
  document.body.append(el);
  toastTimer = setTimeout(() => el.remove(), 6000);
}

async function renderEmpty() {
  const chips = h("div", { class: "chips" });
  fill(main, h("section", { class: "empty watch-empty" },
    h("span", { class: "watch-empty-ico" }, icon("heart")),
    h("h1", {}, "Nothing saved yet"),
    h("p", { class: "lead" }, "Tap the heart on any product to keep an eye on it. We'll show you how its price moves since you saved it."),
    chips));
  const list = await data.popular().catch(() => []);
  chips.replaceChildren(...(list.length ? list : ["fridge", "laptop", "air fryer"]).slice(0, 6)
    .map((q) => h("a", { class: "chip", href: `index.html?q=${encodeURIComponent(q)}` }, q)));
}
