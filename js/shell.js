// The page shell shared by every screen: header (logo, search, status, watchlist, theme switch) and footer.

import { h, icon, watchlist } from "./util.js";
import * as data from "./data.js";

const THEME_KEY = "beismart-theme";

// Dark is the default, as in the original app; the inline script in each page applies a saved choice.
const currentTheme = () => (document.documentElement.dataset.theme === "light" ? "light" : "dark");

function themeButton() {
  const btn = h("button", { class: "icon-btn", type: "button" });
  const paint = () => {
    const dark = currentTheme() === "dark";
    btn.replaceChildren(icon(dark ? "sun" : "moon"));
    btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    btn.title = btn.getAttribute("aria-label");
  };
  btn.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_KEY, next); } catch { /* not remembered */ }
    paint();
  });
  paint();
  return btn;
}

function watchlistLink() {
  const count = h("span", { class: "count" });
  const link = h("a", { class: "icon-btn", href: "watchlist.html" }, icon("heart"), count);
  const paint = () => {
    const n = watchlist().length;
    count.textContent = String(n);
    count.hidden = !n;
    link.setAttribute("aria-label", `Watchlist, ${n} saved`);
    link.title = link.getAttribute("aria-label");
  };
  document.addEventListener("watchlist-changed", paint);
  window.addEventListener("storage", paint);   // another tab changed it
  paint();
  return link;
}

// onSearch(q) is called instead of navigating when the page handles searches itself.
export function renderShell({ query = "", onSearch = null } = {}) {
  const input = h("input", { type: "search", name: "q", value: query, placeholder: "Search a TV, fridge, laptop…",
                             "aria-label": "Search products", autocomplete: "off", minlength: "2", required: true });
  const form = h("form", { class: "search", role: "search", action: "index.html" },
    icon("search", "search-icon"), input,
    h("kbd", { class: "search-kbd", title: "Press / to search" }, "/"),
    h("button", { class: "search-go", type: "submit" }, h("span", { class: "label" }, "Search"), icon("arrow")));
  form.addEventListener("submit", (e) => {
    const q = input.value.trim();
    if (!onSearch) return;           // normal navigation to index.html?q=
    e.preventDefault();
    if (q.length >= 2) onSearch(q);
  });

  const header = h("header", { class: "top" },
    h("div", { class: "wrap top-row" },
      h("a", { class: "brand", href: "index.html", "aria-label": "BeiSmart KE home" },
        h("span", { class: "brand-icon", "aria-hidden": "true" }, icon("cart")),
        h("span", {},
          h("span", { class: "brand-name" }, "BeiSmart ", h("span", {}, "KE")),
          h("span", { class: "brand-sub" }, "Price Intelligence"))),
      form,
      h("nav", { class: "top-actions", "aria-label": "Watchlist and theme" }, watchlistLink(), themeButton()),
    ));

  const footer = h("footer", { class: "foot" },
    h("div", { class: "wrap" },
      h("p", {}, `© ${new Date().getFullYear()} BeiSmart KE — Built for smarter shopping in Kenya`),
      data.source === "static" && h("p", {}, "This is a read-only demo with a daily snapshot of prices. Amazon is not included.")));

  // "/" anywhere (outside a text field) jumps to the search box.
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest("input, textarea, select, [contenteditable]");
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });

  const skip = h("a", { class: "skip-link", href: "#main" }, "Skip to content");
  document.body.prepend(skip, header);
  document.body.append(footer);
  return { input };
}
