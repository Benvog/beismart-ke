// The filter panel (owner's reference: segmented pills, a price histogram with a range slider, check chips,
// toggles, a sticky "Show N results" footer). Desktop: a side panel that applies as you go.
// Phone and tablet: a bottom sheet that applies on "Show N results".
// Filters live in the URL (?min=&max=&store=&brand=&cond=&all=1&drop=1&local=1).

import { h, icon, money, storeDot } from "./util.js";
import { inStock, isInternational } from "./card.js";

export const NO_FILTERS = { min: null, max: null, stores: [], brands: [], cond: "all", all: false, drop: false, local: false };
const BRANDS_SHOWN = 10;          // then "Show all N brands" with a search box
const BINS = 28;                  // histogram bars
const STEPS = 1000;               // slider resolution
const OTHER = "other";            // brand of products whose title names none

// ── URL ──────────────────────────────────────────────────────────────────────

export function readFilters(p) {
  const list = (key) => (p.get(key) || "").split(",").map((s) => s.trim()).filter(Boolean);
  const num = (key) => (p.get(key) && isFinite(+p.get(key)) ? +p.get(key) : null);
  const cond = ["new", "refurbished"].includes(p.get("cond")) ? p.get("cond") : "all";
  return { min: num("min"), max: num("max"), stores: list("store"), brands: list("brand"), cond,
           all: p.get("all") === "1", drop: p.get("drop") === "1", local: p.get("local") === "1" };
}

export function writeFilters(p, f) {
  if (f.min !== null) p.set("min", String(f.min));
  if (f.max !== null) p.set("max", String(f.max));
  if (f.stores.length) p.set("store", f.stores.join(","));
  if (f.brands.length) p.set("brand", f.brands.join(","));
  if (f.cond !== "all") p.set("cond", f.cond);
  if (f.all) p.set("all", "1");
  if (f.drop) p.set("drop", "1");
  if (f.local) p.set("local", "1");
}

export function activeCount(f) {
  return (f.min !== null || f.max !== null ? 1 : 0) + f.stores.length + f.brands.length
    + (f.cond !== "all" ? 1 : 0) + (f.all ? 1 : 0) + (f.drop ? 1 : 0) + (f.local ? 1 : 0);
}

// ── Filtering ────────────────────────────────────────────────────────────────

const brandOf = (g) => g.brand || OTHER;

export function applyFilters(groups, f, skip = null) {
  return groups.filter((g) =>
    (f.all || inStock(g))
    && (skip === "price" || ((f.min === null || g.best_price >= f.min) && (f.max === null || g.best_price <= f.max)))
    && (skip === "stores" || !f.stores.length || g.members.some((m) => f.stores.includes(m.store)))
    && (skip === "brands" || !f.brands.length || f.brands.includes(brandOf(g)))
    && (skip === "cond" || f.cond === "all" || g.condition === f.cond)
    && (!f.drop || Boolean(g.price_drop))
    && (!f.local || !isInternational(g)));
}

// Counts for one facet are taken with every other filter applied, so a chip says what tapping it gives.
function facetCounts(groups, f, facet, valuesOf) {
  const counts = new Map();
  for (const g of applyFilters(groups, f, facet)) {
    for (const v of new Set(valuesOf(g))) counts.set(v, (counts.get(v) || 0) + 1);
  }
  return counts;
}

const UPPER_BRANDS = new Set(["lg", "hp", "tcl", "jbl", "von"]);
export function brandName(b) {
  if (b === OTHER) return "Other";
  if (UPPER_BRANDS.has(b)) return b.toUpperCase();
  return b.replace(/(^|[\s+])([a-z])/g, (_, sep, c) => sep + c.toUpperCase());
}

// ── Price scale: logarithmic, so a KSh 3,000 fridge and a KSh 380,000 one both get room ──

function priceScale(prices) {
  const lo = Math.max(1, Math.min(...prices));
  const hi = Math.max(...prices);
  const a = Math.log(lo), b = Math.log(hi);
  const toPrice = (step) => roundPrice(Math.exp(a + (b - a) * (step / STEPS)));
  const toStep = (price) => (b === a ? 0 : Math.round(((Math.log(Math.min(hi, Math.max(lo, price))) - a) / (b - a)) * STEPS));
  return { lo, hi, toPrice, toStep, flat: hi - lo < 1 };
}

function roundPrice(p) {
  const unit = p >= 100000 ? 1000 : p >= 10000 ? 500 : p >= 1000 ? 100 : 10;
  return Math.round(p / unit) * unit;
}

function median(values) {
  const s = [...values].sort((x, y) => x - y);
  return s.length ? s[Math.floor(s.length / 2)] : 0;
}

// ── The panel ────────────────────────────────────────────────────────────────

// Builds the panel for `draft` (a filters object). onChange(next) is called with a new filters object.
// The caller re-renders; elements carry data-focus so focus can be restored after a re-render.
export function filterPanel(groups, draft, onChange, ui = {}) {
  const set = (patch) => onChange({ ...draft, ...patch });
  const toggleIn = (list, v) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return h("div", { class: "filter-panel" },
    priceSection(groups, draft, set),
    section("Stores", null, storeChips(groups, draft, (s) => set({ stores: toggleIn(draft.stores, s) }))),
    brandSection(groups, draft, (b) => set({ brands: toggleIn(draft.brands, b) }), ui),
    section("Condition", null, segmented([["all", "All"], ["new", "New"], ["refurbished", "Refurbished"]], draft.cond,
      (cond) => set({ cond }), "cond")),
    section("More options", null,
      toggle("In stock only", !draft.all, (on) => set({ all: !on }), "all"),
      toggle("Price dropped recently", draft.drop, (on) => set({ drop: on }), "drop"),
      toggle("Kenyan stores only", draft.local, (on) => set({ local: on }), "local",
        "Hides international prices, which exclude delivery and import fees")),
  );
}

function section(title, aside, ...body) {
  return h("section", { class: "fp-section" },
    h("div", { class: "fp-head" }, h("h3", {}, title), aside && h("span", { class: "fp-aside" }, aside)),
    body);
}

function priceSection(groups, f, set) {
  const pool = applyFilters(groups, f, "price");
  const prices = pool.map((g) => g.best_price);
  if (prices.length < 2) return null;
  const scale = priceScale(prices);
  if (scale.flat) return null;

  const counts = new Array(BINS).fill(0);
  for (const p of prices) counts[Math.min(BINS - 1, Math.floor((scale.toStep(p) / STEPS) * BINS))] += 1;
  const peak = Math.max(...counts);

  let lowStep = f.min === null ? 0 : scale.toStep(f.min);
  let highStep = f.max === null ? STEPS : scale.toStep(f.max);

  const bars = counts.map((c) => h("span", { class: "bar", style: `height:${c ? 12 + (c / peak) * 88 : 4}%` }));
  const fill = h("span", { class: "range-fill" });
  const lowLabel = h("span", { class: "range-value" });
  const highLabel = h("span", { class: "range-value" });
  const lowInput = h("input", { type: "range", min: "0", max: String(STEPS), value: String(lowStep), "aria-label": "Lowest price", dataset: { focus: "price-min" } });
  const highInput = h("input", { type: "range", min: "0", max: String(STEPS), value: String(highStep), "aria-label": "Highest price", dataset: { focus: "price-max" } });

  const paint = () => {
    const a = (lowStep / STEPS) * 100, b = (highStep / STEPS) * 100;
    fill.style.left = `${a}%`;
    fill.style.right = `${100 - b}%`;
    bars.forEach((bar, i) => bar.classList.toggle("on", ((i + 0.5) / BINS) * 100 >= a && ((i + 0.5) / BINS) * 100 <= b));
    lowLabel.textContent = money(lowStep === 0 ? scale.lo : scale.toPrice(lowStep));
    highLabel.textContent = money(highStep === STEPS ? scale.hi : scale.toPrice(highStep));
    lowInput.setAttribute("aria-valuetext", lowLabel.textContent);
    highInput.setAttribute("aria-valuetext", highLabel.textContent);
  };
  lowInput.addEventListener("input", () => { lowStep = Math.min(+lowInput.value, highStep - 10); lowInput.value = lowStep; paint(); });
  highInput.addEventListener("input", () => { highStep = Math.max(+highInput.value, lowStep + 10); highInput.value = highStep; paint(); });
  const commit = () => set({ min: lowStep <= 0 ? null : scale.toPrice(lowStep), max: highStep >= STEPS ? null : scale.toPrice(highStep) });
  lowInput.addEventListener("change", commit);
  highInput.addEventListener("change", commit);
  paint();

  return section("Price range", `Typical ${money(median(prices))}`,
    h("div", { class: "hist", "aria-hidden": "true" }, bars),
    h("div", { class: "range" }, h("span", { class: "range-track" }), fill, lowInput, highInput),
    h("div", { class: "range-values" }, lowLabel, highLabel));
}

function chip({ label, count, on, onClick, dot = null, focus }) {
  return h("button", { type: "button", class: `fchip${on ? " on" : ""}`, "aria-pressed": String(on),
                       disabled: !on && !count, onclick: onClick, dataset: { focus } },
    on ? h("span", { class: "fchip-check" }, icon("check")) : dot,
    h("span", {}, label),
    h("span", { class: "fchip-count" }, String(count || 0)));
}

function storeChips(groups, f, toggleStore) {
  const counts = facetCounts(groups, f, "stores", (g) => g.members.map((m) => m.store));
  const names = [...new Set([...counts.keys(), ...f.stores])].sort();
  return h("div", { class: "fchips" }, names.map((s) => chip({
    label: s, count: counts.get(s), on: f.stores.includes(s), onClick: () => toggleStore(s), dot: storeDot(s), focus: `store-${s}`,
  })));
}

function brandSection(groups, f, toggleBrand, ui) {
  const counts = facetCounts(groups, f, "brands", (g) => [brandOf(g)]);
  const all = [...new Set([...counts.keys(), ...f.brands])]
    .sort((a, b) => (a === OTHER) - (b === OTHER) || (counts.get(b) || 0) - (counts.get(a) || 0) || a.localeCompare(b));
  if (all.length < 2 && !f.brands.length) return null;

  const expanded = ui.brandsExpanded ?? false;
  const query = (ui.brandQuery || "").toLowerCase();
  const shown = expanded
    ? all.filter((b) => brandName(b).toLowerCase().includes(query))
    : [...new Set([...all.slice(0, BRANDS_SHOWN), ...f.brands])];

  const chips = h("div", { class: "fchips" }, shown.map((b) => chip({
    label: brandName(b), count: counts.get(b), on: f.brands.includes(b), onClick: () => toggleBrand(b), focus: `brand-${b}`,
  })));

  const search = expanded && h("div", { class: "fp-search" }, icon("search"),
    h("input", { type: "search", placeholder: "Search brands", value: ui.brandQuery || "", "aria-label": "Search brands",
                 dataset: { focus: "brand-search" },
                 oninput: (e) => { ui.brandQuery = e.target.value; ui.rerender?.(); } }));
  const more = all.length > BRANDS_SHOWN && h("button", { type: "button", class: "link fp-more", dataset: { focus: "brand-more" },
    onclick: () => { ui.brandsExpanded = !expanded; ui.brandQuery = ""; ui.rerender?.(); } },
    expanded ? "Show fewer brands" : `Show all ${all.length} brands`);

  return section("Brands", null, search, chips, more);
}

function segmented(options, value, onPick, focus) {
  return h("div", { class: "segmented fp-seg", role: "radiogroup" }, options.map(([v, label]) =>
    h("button", { type: "button", role: "radio", "aria-checked": String(v === value), class: v === value ? "active" : "",
                  dataset: { focus: `${focus}-${v}` }, onclick: () => v !== value && onPick(v) }, label)));
}

function toggle(label, on, onFlip, focus, hint = null) {
  return h("label", { class: "ftoggle", title: hint || null },
    h("span", {}, label),
    h("input", { type: "checkbox", role: "switch", checked: on, dataset: { focus: `toggle-${focus}` },
                 onchange: (e) => onFlip(e.target.checked) }),
    h("span", { class: "switch", "aria-hidden": "true" }));
}

// Re-render helper that keeps keyboard focus on the same control.
export function swapKeepingFocus(oldEl, newEl) {
  const key = document.activeElement?.dataset?.focus;
  oldEl.replaceWith(newEl);
  if (key) newEl.querySelector(`[data-focus="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
}

// ── Bottom sheet (phone and tablet) ──────────────────────────────────────────

export function openFilterSheet(groups, current, onApply) {
  let draft = { ...current };
  const ui = {};
  const dialog = h("dialog", { class: "sheet", "aria-label": "Filters" });
  const countBtn = h("button", { type: "button", class: "btn sheet-show" });
  const body = h("div", { class: "sheet-body" });

  const paint = () => {
    const panel = filterPanel(groups, draft, (next) => { draft = next; paint(); }, ui);
    const old = body.firstChild;
    if (old) swapKeepingFocus(old, panel); else body.append(panel);
    const n = applyFilters(groups, draft).length;
    countBtn.textContent = n ? `Show ${n} result${n === 1 ? "" : "s"}` : "No matching products";
    countBtn.disabled = !n;
  };
  ui.rerender = paint;

  const close = () => { dialog.close(); };
  dialog.append(
    h("div", { class: "sheet-head" },
      h("span", { class: "sheet-grip", "aria-hidden": "true" }),
      h("h2", {}, "Filters"),
      h("button", { type: "button", class: "chip sheet-reset", onclick: () => { draft = { ...NO_FILTERS }; paint(); } }, "Reset")),
    body,
    h("div", { class: "sheet-foot" },
      h("button", { type: "button", class: "btn btn-quiet", onclick: close }, "Cancel"),
      countBtn));
  countBtn.addEventListener("click", () => { onApply(draft); close(); });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) close(); });   // tap outside the sheet
  dialog.addEventListener("close", () => dialog.remove());

  paint();
  document.body.append(dialog);
  dialog.showModal();
}
