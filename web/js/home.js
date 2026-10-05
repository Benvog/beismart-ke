// The home screen (index.html with no search): the search first, popular searches, this week's price drops,
// and a short "how it works". Drops come from /api/drops (or data/drops.json in the demo).

import { h, fill, icon, storeDot, timeAgo } from "./util.js";
import { productCard, skeletonCard } from "./card.js";
import * as data from "./data.js";

// The public demo leaves Amazon out (see beismart/export.py).
const STORES = ["Jumia", "Kilimall", "Avechi", "Hotpoint", "Carrefour", "Phone Place", "Amazon"]
  .filter((s) => data.source !== "static" || s !== "Amazon");
const FALLBACK_SEARCHES = ["fridge", "laptop", "air fryer", "headphones", "blender"];

// onSearch(q) runs a search without leaving the page.
export function renderHome(main, { onSearch }) {
  const chips = h("div", { class: "chips hero-chips" }, FALLBACK_SEARCHES.map((q) => searchChip(q, onSearch)));
  const drops = h("div", { class: "drops-slot" }, dropsSection(null));

  fill(main,
    h("section", { class: "intro" },
      h("h1", {}, "Find the Best Deals", h("br"), h("span", { class: "grad" }, "Across Every Platform")),
      h("p", { class: "lead" }, "Compare prices across Kenya's biggest online stores, see how prices move, "
        + "and get an email when one drops below your target."),
      heroSearch(onSearch),
      h("div", { class: "popular" }, h("span", { class: "popular-label" }, "Popular"), chips)),
    drops,
    howItWorks(),
    h("div", { class: "intro-stores" }, h("span", { class: "popular-label" }, "Prices from"),
      STORES.map((s) => h("span", { class: "card-stores" }, storeDot(s), s))));

  data.popular().then((list) => {
    if (list && list.length) chips.replaceChildren(...list.slice(0, 8).map((q) => searchChip(q, onSearch)));
  }).catch(() => { /* keep the fallback searches */ });

  data.drops().then((list) => drops.replaceChildren(dropsSection(list)))
    .catch(() => drops.replaceChildren(dropsSection([])));
}

function searchChip(q, onSearch) {
  return h("a", { class: "chip", href: `?q=${encodeURIComponent(q)}`, onclick: (e) => { e.preventDefault(); onSearch(q); } }, q);
}

// The big search in the hero (the header has the small one).
function heroSearch(onSearch) {
  const input = h("input", { type: "search", placeholder: "What are you shopping for?", "aria-label": "Search products",
                             autocomplete: "off", minlength: "2", required: true });
  const form = h("form", { class: "search search-hero", role: "search" },
    icon("search", "search-icon"), input,
    h("button", { class: "search-go", type: "submit" }, h("span", { class: "label" }, "Compare prices"), icon("arrow")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (q.length >= 2) onSearch(q);
  });
  return form;
}

// "Price drops this week": a strip that scrolls sideways, with arrow buttons on larger screens.
// list === null while loading.
function dropsSection(list) {
  if (list && !list.length) {
    return h("section", { class: "drops quiet" },
      h("div", { class: "drops-head" }, h("div", {}, h("h2", {}, "Price drops this week"),
        h("p", { class: "meta" }, "No price has fallen since the last checks. New drops show up here after the daily check."))));
  }
  const track = h("div", { class: "drops-track", tabindex: "0", "aria-label": "Price drops this week" },
    list ? list.map((d) => productCard(d, { query: d.query })) : Array.from({ length: 5 }, skeletonCard));
  const scroll = (dir) => track.scrollBy({ left: dir * track.clientWidth * 0.8, behavior: "smooth" });
  const latest = list && list.flatMap((d) => d.members.map((m) => m.last_seen)).sort().pop();

  return h("section", { class: "drops" },
    h("div", { class: "drops-head" },
      h("div", {},
        h("h2", {}, "Price drops this week"),
        h("p", { class: "meta" }, list
          ? `${list.length} product${list.length === 1 ? "" : "s"} cheaper than before, biggest fall first${latest ? ` · checked ${timeAgo(latest)}` : ""}`
          : "Looking for price drops…")),
      h("div", { class: "drops-nav" },
        h("button", { class: "icon-btn", type: "button", "aria-label": "Scroll back", onclick: () => scroll(-1) }, icon("arrow", "flip")),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Scroll on", onclick: () => scroll(1) }, icon("arrow")))),
    track);
}

function howItWorks() {
  const step = (ic, title, text) => h("div", { class: "how-step" },
    h("span", { class: "how-ico" }, icon(ic)), h("h3", {}, title), h("p", {}, text));
  return h("section", { class: "how" },
    step("search", "One search, every store", "Jumia, Kilimall, Avechi, Hotpoint, Carrefour and more, side by side, with junk listings filtered out."),
    step("chart", "See how prices move", "Prices are checked every day, so you can tell a real deal from a fake discount."),
    step("bell", "Get told when it drops", "Pick a target price and get one email when a store hits it. No account needed."));
}
