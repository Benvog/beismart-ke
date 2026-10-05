// The search and results screen (index.html). The URL holds the state (?q=fridge&sort=cheapest&store=Jumia…),
// so results can be shared and the back button works.

import { h, fill, icon, money, timeAgo } from "./util.js";
import { renderShell } from "./shell.js";
import { productCard, skeletonCard, bestDeals, inStock, saving, isInternational } from "./card.js";
import { NO_FILTERS, readFilters, writeFilters, activeCount, applyFilters, filterPanel, openFilterSheet } from "./filters.js";
import { renderHome } from "./home.js";
import * as data from "./data.js";

const SORTS = [
  { id: "match", label: "Best match", order: (a, b) => isInternational(a) - isInternational(b) },   // local stores first
  { id: "cheapest", label: "Cheapest", order: (a, b) => a.best_price - b.best_price },
  { id: "saving", label: "Biggest saving", order: (a, b) => saving(b) - saving(a) || a.best_price - b.best_price },
  { id: "stores", label: "Most stores", order: (a, b) => b.store_count - a.store_count || a.best_price - b.best_price },
];
const EXAMPLES = ["fridge", "laptop", "air fryer", "headphones", "blender"];
const PROBLEM_STATUSES = { blocked: "blocked us", layout_changed: "could not be read", timeout: "timed out", error: "failed" };

const main = document.getElementById("main");
let state = readUrl();
let current = null;     // the last search response
let loadId = 0;         // ignore answers to searches the person has moved on from
const sideUi = { rerender: () => render() };   // side panel state that is not in the URL (brand list open, brand search)

const { input } = renderShell({ query: state.q, onSearch: (q) => go(fresh(q)) });

const fresh = (q) => ({ q, sort: "match", hidden: false, filters: { ...NO_FILTERS } });   // a new search starts unfiltered

function readUrl() {
  const p = new URLSearchParams(location.search);
  const sort = SORTS.some((s) => s.id === p.get("sort")) ? p.get("sort") : "match";
  return { q: (p.get("q") || "").trim(), sort, hidden: p.get("hidden") === "1", filters: readFilters(p) };
}

function writeUrl(s, replace = false) {
  const p = new URLSearchParams();
  if (s.q) p.set("q", s.q);
  if (s.sort !== "match") p.set("sort", s.sort);
  if (s.hidden) p.set("hidden", "1");
  writeFilters(p, s.filters);
  const url = `${location.pathname}${p.toString() ? `?${p}` : ""}`;
  history[replace ? "replaceState" : "pushState"](null, "", url);
}

// Filter changes replace the history entry (one Back leaves the search, not each tap on a chip).
function go(next, { replace = false } = {}) {
  const newQuery = next.q !== state.q;
  state = next;
  writeUrl(state, replace);
  if (newQuery) {
    Object.assign(sideUi, { brandsExpanded: false, brandQuery: "" });
    load();
  } else render();
}

window.addEventListener("popstate", () => {
  const before = state.q;
  state = readUrl();
  input.value = state.q;
  if (state.q !== before) load();
  else render();
});

// ── Loading ───────────────────────────────────────────────────────────────────

async function load() {
  const id = ++loadId;
  document.title = state.q ? `${state.q} · BeiSmart KE` : "BeiSmart KE: compare prices across Kenyan stores";
  if (!state.q) return renderIntro();
  renderLoading();
  try {
    const result = await data.search(state.q);
    if (id !== loadId) return;
    current = result;
    render();
  } catch (err) {
    if (id !== loadId) return;
    current = null;
    renderError(err);
  }
}

// ── Screens ───────────────────────────────────────────────────────────────────

function renderIntro() {
  document.body.classList.add("is-home");      // the hero has the big search, so the header hides its own
  renderHome(main, { onSearch: (q) => { input.value = q; go(fresh(q)); } });
}

function renderLoading() {
  document.body.classList.remove("is-home");
  fill(main,
    resultsHead(state.q, "Looking up saved prices…"),
    h("div", { class: "grid", "aria-busy": "true" }, Array.from({ length: 10 }, skeletonCard)));
}

function resultsHead(query, meta, summaryBar = null) {
  return h("section", { class: "results-head" },
    h("div", {}, h("h1", {}, query), h("p", { class: "meta" }, meta)),
    summaryBar);
}

// One slim bar: the cheapest local price, and the biggest saving on one product across stores.
function summary(groups) {
  const local = groups.filter((g) => inStock(g) && !isInternational(g));
  if (!local.length) return null;
  const best = Math.max(0, ...local.map(saving));
  const item = (value, label, cls = "") => h("div", {}, h("div", { class: `summary-value ${cls}` }, value), h("div", { class: "summary-label" }, label));
  return h("div", { class: "summary" },
    item(money(Math.min(...local.map((g) => g.best_price))), "Lowest price"),
    best > 0 && item(money(best), "Biggest saving", "good"));
}

function sortControl() {
  return h("div", { class: "segmented", role: "radiogroup", "aria-label": "Sort products" },
    SORTS.map((s) => h("button", {
      type: "button", role: "radio", "aria-checked": String(s.id === state.sort),
      class: s.id === state.sort ? "active" : "", dataset: { focus: `sort-${s.id}` },
      onclick: () => s.id !== state.sort && go({ ...state, sort: s.id }, { replace: true }),
    }, s.label)));
}

function freshness(groups) {
  const seen = groups.flatMap((g) => g.members.map((m) => m.last_seen)).sort();
  return seen.length ? `prices checked ${timeAgo(seen[seen.length - 1])}` : "";
}

function storeProblems(stores) {
  const bad = stores.filter((s) => PROBLEM_STATUSES[s.status]);
  if (!bad.length) return null;
  const text = bad.map((s) => `${s.store} ${PROBLEM_STATUSES[s.status]}`).join(", ");
  return h("p", { class: "notice" }, icon("alert"), `On the last check: ${text}. Their prices may be missing or older.`);
}

const setFilters = (filters) => go({ ...state, filters }, { replace: true });

function render() {
  if (!state.q) return renderIntro();
  if (!current) return load();
  const r = current;
  if (!r.groups.length) return renderEmpty(r);

  const focusKey = document.activeElement?.dataset?.focus;   // keep focus on the same control after re-rendering

  const sort = SORTS.find((s) => s.id === state.sort);
  const sorted = r.groups.map((g, i) => ({ g, i }))
    .sort((a, b) => (inStock(b.g) - inStock(a.g)) || sort.order(a.g, b.g) || a.i - b.i)   // sold out last
    .map((x) => x.g);
  const shown = applyFilters(sorted, state.filters);
  const deals = bestDeals(sorted);
  const storeCount = new Set(r.results.map((l) => l.store)).size;
  const active = activeCount(state.filters);
  // Sold-out products are hidden by default ("In stock only"), so that is the count to compare with.
  const total = state.filters.all ? sorted.length : applyFilters(sorted, NO_FILTERS).length;
  const clear = active > 0 && h("button", { class: "link", type: "button", onclick: () => setFilters({ ...NO_FILTERS }) }, "Clear filters");

  const hiddenToggle = r.hidden_count > 0 && h("p", { class: "notice subtle" },
    `${r.hidden_count} hidden as accessories or oddities · `,
    h("button", { class: "link", type: "button", onclick: () => go({ ...state, hidden: !state.hidden }, { replace: true }) },
      state.hidden ? "Hide them" : "Show them"));

  const filtersButton = h("button", { type: "button", class: `filters-btn${active ? " on" : ""}`, dataset: { focus: "filters-btn" },
    onclick: () => openFilterSheet(sorted, state.filters, setFilters) },
    icon("sliders"), "Filters", active > 0 && h("span", { class: "count" }, String(active)));

  const meta = shown.length !== total
    ? [`${shown.length} of ${total} products`, clear && " · ", clear]
    : [`${total} product${total === 1 ? "" : "s"} from ${storeCount} store${storeCount === 1 ? "" : "s"}`,
       freshness(r.groups) && ` · ${freshness(r.groups)}`, clear && " · ", clear];

  fill(main,
    resultsHead(r.query, meta, summary(shown)),
    h("div", { class: "results-layout" },
      h("aside", { class: "filters-side", "aria-label": "Filters" },
        h("a", { class: "skip-link", href: "#results-list" }, "Skip filters, go to results"),
        h("div", { class: "fp-title" }, h("h2", {}, "Filters"),
          active > 0 && h("button", { type: "button", class: "chip fp-reset", onclick: () => setFilters({ ...NO_FILTERS }) }, "Reset")),
        filterPanel(sorted, state.filters, setFilters, sideUi)),
      h("div", { class: "results-main", id: "results-list", tabindex: "-1" },
        h("div", { class: "toolbar" }, h("div", { class: "toolbar-left" }, filtersButton, sortControl()), hiddenToggle),
        storeProblems(r.stores),
        shown.length
          ? h("div", { class: "grid" }, shown.map((g) => productCard(g, { query: r.query, bestDeal: deals.has(g.id) })))
          : h("div", { class: "no-match" },
              h("h2", {}, "No products match these filters"),
              h("p", { class: "meta" }, "Try a wider price range or fewer stores and brands."),
              h("button", { class: "btn", type: "button", onclick: () => setFilters({ ...NO_FILTERS }) }, "Clear filters")),
        state.hidden && r.hidden.length > 0 && h("section", { class: "hidden-section" },
          h("h2", {}, "Hidden listings"),
          h("p", { class: "meta" }, "Judged to be accessories, spare parts or far too cheap to be the real thing. Nothing is deleted."),
          h("div", { class: "grid" }, r.hidden.map((l) => productCard(asGroup(l), { query: r.query, hiddenReason: l.hidden_reason })))),
      )),
  );

  if (focusKey) main.querySelector(`[data-focus="${CSS.escape(focusKey)}"]`)?.focus({ preventScroll: true });
}

// A hidden listing shown with the same card as a product.
function asGroup(l) {
  return { id: `listing-${l.id}`, title: l.title, image_url: l.image_url, key: null, brand: null, condition: "new", store_count: 1,
           best_price: l.price, highest_price: l.price, members: [l], price_drop: null, previous_best: null, lowest_ever: false };
}

function renderEmpty(r) {
  const refreshBtn = data.canRefresh && h("button", { class: "btn", type: "button", onclick: (e) => runRefresh(e.currentTarget) },
    icon("refresh"), "Check the stores now");
  fill(main,
    h("section", { class: "empty" },
      h("h1", {}, `No saved prices for “${r.query}” yet`),
      h("p", { class: "lead" }, data.canRefresh
        ? "Prices are saved by the daily check. Check the stores now to look it up (it takes about a minute)."
        : "Try one of these searches."),
      refreshBtn,
      h("div", { class: "chips" }, EXAMPLES.map((q) => h("a", { class: "chip", href: `?q=${encodeURIComponent(q)}` }, q)))));
}

async function runRefresh(btn) {
  btn.disabled = true;
  btn.replaceChildren(icon("refresh", "spin"), "Checking 7 stores…");
  try {
    await data.refresh(state.q);
    current = null;
    load();
  } catch (err) {
    btn.disabled = false;
    btn.replaceChildren(icon("refresh"), "Try again");
    btn.after(h("p", { class: "notice" }, icon("alert"), err.message));
  }
}

async function renderError(err) {
  const known = err.kind === "not_exported" ? await data.queries().catch(() => []) : null;
  fill(main,
    h("section", { class: "empty" },
      h("h1", {}, err.kind === "not_exported" ? `“${state.q}” is not in this demo` : "Something went wrong"),
      h("p", { class: "lead" }, err.kind === "not_exported"
        ? "The demo holds a daily snapshot of a fixed set of searches. Try one of these:"
        : err.message),
      known && h("div", { class: "chips" }, known.map((q) => h("a", { class: "chip", href: `?q=${encodeURIComponent(q)}` }, q))),
      err.kind !== "not_exported" && h("button", { class: "btn", type: "button", onclick: load }, "Try again")));
}

writeUrl(state, true);
load();
