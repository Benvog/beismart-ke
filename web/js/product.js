// The product page (product.html?q=fridge&id=hisense-ref094dr-new): one product across every store,
// its price history, and an email alert. The product is found in its search's results, so the page works
// the same with the live API and the exported demo files.

import { h, fill, icon, money, safeUrl, storeDot, timeAgo, isWatched, toggleWatch } from "./util.js";
import { renderShell } from "./shell.js";
import { inStock, saving } from "./card.js";
import { brandName } from "./filters.js";
import { priceChart } from "./chart.js";
import * as data from "./data.js";

const main = document.getElementById("main");
const params = new URLSearchParams(location.search);
const query = (params.get("q") || "").trim();
const id = params.get("id") || "";
const resultsUrl = `index.html?q=${encodeURIComponent(query)}`;

renderShell({ query });
load();

async function load() {
  if (!query || !id) return notFound();
  fill(main, h("div", { class: "product-loading" }, h("div", { class: "sk pl-tile" }), h("div", {},
    h("span", { class: "sk sk-line" }), h("span", { class: "sk sk-line short" }), h("span", { class: "sk sk-price" }))));
  let result;
  try {
    result = await data.search(query);
  } catch (err) {
    return fill(main, h("section", { class: "empty" }, h("h1", {}, "Something went wrong"), h("p", { class: "lead" }, err.message),
      h("button", { class: "btn", type: "button", onclick: load }, "Try again")));
  }
  const group = result.groups.find((g) => g.id === id);
  if (!group) return notFound();
  document.title = `${group.title} · BeiSmart KE`;
  render(group, result);
  if (location.hash === "#alert") document.getElementById("alert")?.scrollIntoView({ block: "start" });   // from "Set an alert"
}

function notFound() {
  fill(main, h("section", { class: "empty" },
    h("h1", {}, "We couldn't find that product"),
    h("p", { class: "lead" }, "Its listings may have changed since the link was made. Search again to see today's prices."),
    query && h("a", { class: "btn", href: resultsUrl }, `Back to “${query}”`)));
}

function cheapestMember(group) {
  return group.members.find((m) => m.in_stock && m.price === group.best_price) || group.members[0];
}

// ── Page ──────────────────────────────────────────────────────────────────────

function render(group, result) {
  const best = cheapestMember(group);
  const bestUrl = safeUrl(best.url);
  const save = saving(group);
  const available = inStock(group);
  const previous = group.price_drop && group.previous_best ? group.previous_best
    : best.old_price && best.old_price > group.best_price ? best.old_price : null;
  const discount = previous ? Math.round((1 - group.best_price / previous) * 100) : 0;
  const lastSeen = group.members.map((m) => m.last_seen).sort().pop();

  const heroImage = safeUrl(group.image_url)
    ? h("img", { src: safeUrl(group.image_url), alt: group.title, referrerpolicy: "no-referrer",
                 onerror: (e) => { e.target.parentElement?.classList.add("no-image"); e.target.replaceWith(h("span", { class: "tile-empty" }, "🛒")); } })
    : h("span", { class: "tile-empty" }, "🛒");

  fill(main,
    backButton(result),

    h("section", { class: "product-hero" },
      h("div", { class: `tile product-tile${safeUrl(group.image_url) ? "" : " no-image"}` }, heroImage),
      h("div", { class: "product-info" },
        h("p", { class: "product-kicker" }, [group.brand && brandName(group.brand), group.condition === "refurbished" ? "Refurbished" : "New"]
          .filter(Boolean).join(" · ")),
        h("h1", { class: "product-title", title: group.title }, group.title),
        h("div", { class: "product-tags" },
          !available && h("span", { class: "ptag" }, "Sold out everywhere"),
          group.price_drop && h("span", { class: "ptag drop" }, `↓ Down ${money(group.price_drop)}`),
          group.lowest_ever && h("span", { class: "ptag low" }, "Lowest price we've seen")),

        h("div", { class: "deal-card" },
          h("div", { class: "deal-top" },
            h("span", { class: "price-label" }, available ? h("span", {}, "Best price at ", h("b", {}, best.store)) : "Last price"),
            lastSeen && h("span", { class: "fresh-chip" }, h("span", { class: "fresh-dot" }), `Checked ${timeAgo(lastSeen)}`)),
          h("div", { class: "price-row" },
            h("span", { class: "price-big" }, money(group.best_price)),
            previous && h("s", { class: "was" }, money(previous)),
            discount >= 1 && h("span", { class: "discount" }, `−${discount}%`)),
          best.converted && h("p", { class: "card-note intl" }, "International price: excludes delivery and import fees"),
          h("div", { class: "product-actions" },
            bestUrl && h("a", { class: "btn go-btn", href: bestUrl, target: "_blank", rel: "noopener noreferrer" },
              `Go to ${best.store}`, icon("external")),
            saveButton(group))),

        compareStores(group, save))),

    historySection(group),
    alertSection(group),
  );
}

// "Back to results" with the search and its size, as a proper button.
function backButton(result) {
  const fromResults = document.referrer && new URL(document.referrer, location.href).pathname.match(/\/(index\.html)?$/);
  const n = result.groups.length;
  return h("nav", { class: "crumbs", "aria-label": "Back to results" },
    h("a", { class: "back-btn", href: resultsUrl,
             onclick: (e) => { if (fromResults) { e.preventDefault(); history.back(); } } },
      h("span", { class: "back-ico" }, icon("arrow")),
      h("span", { class: "back-text" }, h("span", {}, "Back to results"),
        h("small", {}, `“${query}” · ${n} product${n === 1 ? "" : "s"}`))));
}

function saveButton(group) {
  const paint = (btn, on) => {
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", String(on));
    btn.replaceChildren(icon("heart"), on ? "Saved" : "Save");
  };
  const btn = h("button", { type: "button", class: "btn btn-quiet save-btn" });
  btn.addEventListener("click", () => paint(btn, toggleWatch(group, query)));
  paint(btn, isWatched(group.id));
  return btn;
}

// Every store's price, compact, with how much more each costs than the cheapest.
const OFFERS_SHOWN = 5;          // then "Show all N offers" (a store can list the same product many times)

function compareStores(group, save) {
  const offers = group.members.length;
  const title = offers > group.store_count ? `${offers} offers from ${group.store_count} store${group.store_count === 1 ? "" : "s"}`
    : group.store_count > 1 ? `Compare ${group.store_count} stores` : "Where to buy";
  const head = h("div", { class: "compare-head" },
    h("h2", {}, title),
    save > 0 && h("span", { class: "card-note save" }, `Save up to ${money(save)}`));
  const rows = group.members.map((m, i) => {
    const url = safeUrl(m.url);
    const isBest = i === 0 && m.in_stock;
    const more = m.in_stock && !isBest ? m.price - group.best_price : 0;
    return h(url ? "a" : "div", { class: `cmp-row${m.in_stock ? "" : " out"}${isBest ? " best" : ""}`,
                                  href: url, target: url && "_blank", rel: url && "noopener noreferrer", title: m.title },
      h("span", { class: "cmp-store" }, storeDot(m.store), m.store),
      h("span", { class: "cmp-note" }, isBest ? h("span", { class: "sr-best" }, "Cheapest")
        : !m.in_stock ? "Sold out" : more > 0 ? `+${money(more)}` : "Same price"),
      h("span", { class: "cmp-price" }, money(m.price), m.converted && h("span", { class: "sr-intl" }, " intl")),
      url && h("span", { class: "cmp-go", "aria-hidden": "true" }, icon("external")));
  });
  const list = h("div", { class: "cmp-rows" }, rows.slice(0, OFFERS_SHOWN));
  const more = offers > OFFERS_SHOWN + 1 && h("button", { type: "button", class: "link cmp-more",
    onclick: (e) => { list.replaceChildren(...rows); e.currentTarget.remove(); } }, `Show all ${offers} offers`);
  if (!more) list.replaceChildren(...rows);
  return h("div", { class: "compare" }, head, list, more,
    group.store_count === 1 && h("p", { class: "fine" }, `Only ${group.members[0].store} lists this right now. We check every store daily.`));
}

// ── Price history ─────────────────────────────────────────────────────────────

function historySection(group) {
  const body = h("div", { class: "history-body" }, h("div", { class: "sk chart-sk" }));
  const section = h("section", { class: "product-section" },
    h("div", { class: "ps-head" }, h("h2", {}, "Price history")), body);

  data.history(group.members.map((m) => m.id)).then((hist) => {
    if (!hist || !hist.best.length) {
      body.replaceChildren(h("p", { class: "meta" }, "No price history yet. It builds up as the daily check runs."));
      return;
    }
    let showStores = false;
    const chartBox = h("div");
    const paint = () => chartBox.replaceChildren(priceChart(hist, { showStores }));
    const storesToggle = hist.stores.length > 1 && h("label", { class: "ftoggle chart-toggle" },
      h("span", {}, "Each store"),
      h("input", { type: "checkbox", role: "switch", onchange: (e) => { showStores = e.target.checked; paint(); } }),
      h("span", { class: "switch", "aria-hidden": "true" }));
    if (storesToggle) section.querySelector(".ps-head").append(storesToggle);
    paint();

    const sm = hist.summary;
    const changes = hist.best.length - 1;
    const since = new Date(sm.first_seen || hist.best[0].at).toLocaleDateString("en-KE", { day: "numeric", month: "long" });
    const fact = (value, label) => h("div", {}, h("div", { class: "summary-value" }, value), h("div", { class: "summary-label" }, label));
    body.replaceChildren(
      chartBox,
      h("div", { class: "summary history-facts" },
        sm.lowest_ever !== null && fact(money(sm.lowest_ever), "Lowest seen"),
        sm.highest_ever !== null && fact(money(sm.highest_ever), "Highest seen"),
        fact(since, "Tracked since")),
      h("p", { class: "meta" }, changes > 0
        ? `The best price changed ${changes} time${changes === 1 ? "" : "s"} since ${since}.`
        : `No price changes since we started tracking on ${since}. The chart fills in as the daily check runs.`));
  }).catch(() => body.replaceChildren(h("p", { class: "meta" }, "Price history is not available right now.")));
  return section;
}

// ── Email alert ───────────────────────────────────────────────────────────────

function alertSection(group) {
  const productWatch = Boolean(group.key);      // only an identified product can be followed across stores
  const suggested = Math.max(1, Math.floor((group.best_price * 0.95) / 100) * 100);
  const lead = productWatch
    ? "We'll email you when this product's best price drops to your target, at any store we track."
    : `This listing couldn't be matched across stores, so the alert covers any “${query}” at or below your target.`;
  const intlNote = group.members.every((m) => m.converted)
    && "International prices never trigger alerts (they exclude delivery and import fees), so the alert watches Kenyan stores only.";

  if (!data.canEmail) {
    return h("section", { class: "product-section alert-card", id: "alert" },
      h("div", { class: "ps-head" }, h("h2", {}, "Price alert")),
      h("p", { class: "meta" }, "Email alerts work in the local app. This demo shows a daily snapshot of prices."));
  }

  const target = h("input", { type: "number", inputmode: "numeric", min: "1", step: "1", value: String(suggested), required: true,
                              "aria-label": "Target price in shillings" });
  const email = h("input", { type: "email", placeholder: "you@example.com", required: true, autocomplete: "email", "aria-label": "Email address" });
  const button = h("button", { class: "btn", type: "submit" }, icon("bell"), "Email me");
  const status = h("p", { class: "alert-status", role: "status" });

  const form = h("form", { class: "alert-form" },
    h("label", { class: "af-field" }, h("span", {}, "Alert me at or below"),
      h("div", { class: "af-money" }, h("span", {}, "KSh"), target)),
    h("label", { class: "af-field af-email" }, h("span", {}, "Email"), email),
    button);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const price = Number(target.value);
    if (!(price > 0)) return showStatus("Enter a target price above zero.", "bad");
    if (!email.checkValidity()) return showStatus("Enter a valid email address.", "bad");
    button.disabled = true;
    showStatus("Sending…");
    try {
      const res = await data.watch({ query, target_price: price, email: email.value.trim(),
                                     product_key: productWatch ? group.key : null, label: group.title.slice(0, 150) });
      showStatus(res.message, "good");
      form.classList.add("done");
    } catch (err) {
      showStatus(err.message, "bad");
    } finally {
      button.disabled = false;
    }
  });
  function showStatus(text, kind = "") {
    status.textContent = text;
    status.className = `alert-status ${kind}`;
  }

  return h("section", { class: "product-section alert-card", id: "alert" },
    h("div", { class: "ps-head" }, h("h2", {}, "Price alert")),
    h("p", { class: "meta" }, lead, intlNote && ` ${intlNote}`),
    form, status,
    h("p", { class: "fine" }, "You'll get one email to confirm. No account needed, and every email has a one-click unsubscribe."));
}
