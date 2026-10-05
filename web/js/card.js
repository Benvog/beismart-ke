// The product card: one product (an API "group") with the best price across stores.
// Layout from the owner's reference (picture first, tags over the picture, a heart top-right);
// look from the original app (store colours, the orange accent), kept quiet so the prices lead.

import { h, icon, money, safeUrl, storeDot, isWatched, toggleWatch } from "./util.js";

const BEST_DEAL_COUNT = 3;      // at most this many "Best deal" tags in one set of results
const BEST_DEAL_MIN_PCT = 5;    // ...and only when the saving is worth mentioning
const MAX_STORE_NAMES = 2;      // then "+2"

export const inStock = (group) => group.members.some((m) => m.in_stock);
// Only international listings (Amazon): prices exclude delivery and import fees.
export const isInternational = (group) => Number(group.members.every((m) => m.converted));
export const saving = (group) => (group.store_count > 1 ? group.highest_price - group.best_price : 0);

// The products with the biggest saving between the cheapest and the dearest store.
export function bestDeals(groups) {
  return new Set(
    groups
      .filter((g) => inStock(g) && saving(g) > 0 && (saving(g) / g.highest_price) * 100 >= BEST_DEAL_MIN_PCT)
      .sort((a, b) => saving(b) - saving(a))
      .slice(0, BEST_DEAL_COUNT)
      .map((g) => g.id),
  );
}

function cheapest(group) {
  return group.members.find((m) => m.in_stock && m.price === group.best_price) || group.members[0];
}

// The struck-through price: our own record of a drop first, else the store's own "was" price.
function previousPrice(group) {
  if (group.price_drop && group.previous_best) return { price: group.previous_best, why: "Our previous best price" };
  const old = cheapest(group).old_price;
  if (old && old > group.best_price) return { price: old, why: "The store's previous price" };
  return null;
}

// At most one tag, the most useful first.
function tag(group, isBestDeal) {
  if (!inStock(group)) return h("span", { class: "tag tag-out" }, "Sold out");
  if (group.price_drop) return h("span", { class: "tag tag-drop", title: `Down ${money(group.price_drop)}` }, "Price drop");
  if (isBestDeal) return h("span", { class: "tag tag-deal" }, "Best deal");
  if (group.lowest_ever) return h("span", { class: "tag tag-low" }, "Lowest ever");
  return null;
}

function picture(group) {
  const url = safeUrl(group.image_url);
  const placeholder = () => h("span", { class: "tile-empty", "aria-hidden": "true" }, "🛒");
  if (!url) return placeholder();
  const img = h("img", { src: url, alt: "", loading: "lazy", referrerpolicy: "no-referrer", decoding: "async" });
  img.addEventListener("error", () => img.replaceWith(placeholder()), { once: true });
  return img;
}

function heart(group, query) {
  const label = (on) => (on ? "Remove from watchlist" : "Add to watchlist");
  const on = isWatched(group.id);
  const btn = h("button", { class: `heart${on ? " on" : ""}`, type: "button", "aria-pressed": String(on),
                            "aria-label": label(on), title: label(on) }, icon("heart"));
  btn.addEventListener("click", (e) => {
    const now = toggleWatch(group, query);
    btn.classList.toggle("on", now);
    btn.setAttribute("aria-pressed", String(now));
    btn.setAttribute("aria-label", label(now));
    btn.title = label(now);
  });
  return btn;
}

// Store colour dots and names: "Jumia", "Jumia, Kilimall", "Jumia, Kilimall +2".
function storesLine(group) {
  const names = [...new Set(group.members.map((m) => m.store))];
  const shown = names.slice(0, MAX_STORE_NAMES).join(", ");
  const rest = names.length - MAX_STORE_NAMES;
  return h("p", { class: "card-stores", title: names.join(", ") },
    h("span", { class: "dots" }, names.map(storeDot)),
    h("span", { class: "names" }, rest > 0 ? `${shown} +${rest}` : shown));
}

export function productCard(group, { query, bestDeal = false, hiddenReason = null } = {}) {
  const before = previousPrice(group);
  const save = saving(group);
  const intl = cheapest(group).converted;
  const href = `product.html?${new URLSearchParams({ q: query, id: group.id })}`;

  // A plain box whose title link stretches over the whole card (see .card-link), so the heart can be a
  // separate button rather than a button inside a link.
  return h("article", { class: `card${inStock(group) ? "" : " sold-out"}` },
    h("div", { class: "tile" },
      picture(group),
      !hiddenReason && tag(group, bestDeal),
      !hiddenReason && heart(group, query),
    ),
    h("div", { class: "card-body" },
      h("h3", { class: "card-title", title: group.title }, h("a", { class: "card-link", href }, group.title)),
      storesLine(group),
      hiddenReason && h("p", { class: "hidden-reason" }, `Hidden: ${hiddenReason}`),
      h("div", { class: "card-prices" },
        h("span", { class: "price" }, money(group.best_price)),
        before && h("s", { class: "was", title: before.why }, money(before.price)),
      ),
      save > 0 && h("p", { class: "card-note save" }, `Save ${money(save)} across ${group.store_count} stores`),
      intl && h("p", { class: "card-note intl", title: "International price: excludes delivery and import fees" },
                "International · excl. delivery & import fees"),
    ),
  );
}

export function skeletonCard() {
  return h("div", { class: "card skeleton", "aria-hidden": "true" },
    h("div", { class: "tile" }),
    h("div", { class: "card-body" }, h("span", { class: "sk sk-line short" }), h("span", { class: "sk sk-line" }),
      h("span", { class: "sk sk-price" })));
}
