// Price history as a step chart (prices hold until they change), drawn as inline SVG.
// Input is /api/history: points are the moments a price changed; a null price means nothing was in stock.
// The best price is the orange line; each store's line can be shown in its colour.

import { h, money, storeColour } from "./util.js";

const SVG = "http://www.w3.org/2000/svg";
const HEIGHT = 240;
const PAD = { top: 16, right: 16, bottom: 28, left: 64 };
const DAY = 86400000;

function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  el.append(...children);
  return el;
}

const toPoints = (series) => series.map((c) => ({ t: new Date(c.at).getTime(), price: c.price }));

// The price in force at time t (the last change at or before t).
function priceAt(points, t) {
  let price = null;
  for (const p of points) {
    if (p.t > t) break;
    price = p.price;
  }
  return price;
}

// Step path segments; a null price breaks the line (sold out everywhere).
function stepPath(points, end, x, y) {
  let d = "";
  points.forEach((p, i) => {
    if (p.price === null) return;
    const until = i + 1 < points.length ? points[i + 1].t : end;
    d += `M${x(p.t).toFixed(1)},${y(p.price).toFixed(1)}H${x(until).toFixed(1)}`;
    const next = points[i + 1];
    if (next && next.price !== null) d += `V${y(next.price).toFixed(1)}`;
  });
  return d;
}

// The filled area under the line: one closed shape per unbroken run of prices.
function areaPath(points, end, x, y, base) {
  let d = "";
  let open = false;
  points.forEach((p, i) => {
    const until = i + 1 < points.length ? points[i + 1].t : end;
    if (p.price === null) {
      if (open) { d += `V${base}Z`; open = false; }
      return;
    }
    if (!open) { d += `M${x(p.t).toFixed(1)},${base}`; open = true; }
    d += `V${y(p.price).toFixed(1)}H${x(until).toFixed(1)}`;
  });
  if (open) d += `V${base}Z`;
  return d;
}

function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || hi || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return ticks;
}

const shortMoney = (v) => (v >= 1000 ? `KSh ${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : `KSh ${Math.round(v)}`);
const dateLabel = (t) => new Date(t).toLocaleDateString("en-KE", { day: "numeric", month: "short" });

// Returns an element that draws itself at its container's width and redraws on resize.
export function priceChart(history, { showStores = false, range = "all" } = {}) {
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "chart-tip", hidden: true });
  const end = new Date(history.as_of).getTime();
  const best = toPoints(history.best);
  const stores = history.stores.map((st) => ({ store: st.store, points: toPoints(st.points) }));

  const draw = () => {
    const width = Math.max(280, wrap.clientWidth);
    const first = best.length ? best[0].t : end - DAY;
    const days = { "30d": 30, "90d": 90 }[range];
    const from = days ? Math.max(first, end - days * DAY) : first;
    // A little room before the first point, and at least two days shown so a young history is readable.
    const start = Math.min(from - Math.max((end - from) * 0.06, 6 * 3600000), end - 2 * DAY);

    const lines = [{ points: best, colour: "var(--accent)", main: true }];
    if (showStores) for (const st of stores) lines.push({ points: st.points, colour: storeColour(st.store), store: st.store });

    const prices = lines.flatMap((l) => l.points.filter((p) => p.price !== null && p.t <= end).map((p) => p.price));
    if (!prices.length) {
      wrap.replaceChildren(h("p", { class: "chart-empty" }, "No in-stock price recorded yet."));
      return;
    }
    let lo = Math.min(...prices), hi = Math.max(...prices);
    const pad = (hi - lo) * 0.15 || hi * 0.05;
    lo = Math.max(0, lo - pad);
    hi += pad;

    const x = (t) => PAD.left + ((Math.max(t, start) - start) / (end - start)) * (width - PAD.left - PAD.right);
    const y = (p) => PAD.top + (1 - (p - lo) / (hi - lo)) * (HEIGHT - PAD.top - PAD.bottom);

    const svg = s("svg", { viewBox: `0 0 ${width} ${HEIGHT}`, width, height: HEIGHT, role: "img",
                           "aria-label": "Price history chart" });

    // Grid and axes
    for (const v of niceTicks(lo, hi)) {
      svg.append(s("line", { x1: PAD.left, x2: width - PAD.right, y1: y(v), y2: y(v), class: "chart-grid" }));
      svg.append(s("text", { x: PAD.left - 10, y: y(v) + 4, "text-anchor": "end", class: "chart-axis" }, shortMoney(v)));
    }
    // Day ticks at midnight, thinned so labels never collide (about one per 64px).
    const spanDays = (end - start) / DAY;
    const maxTicks = Math.max(2, Math.floor((width - PAD.left - PAD.right) / 64));
    const every = Math.max(1, Math.ceil(spanDays / maxTicks));
    const midnight = new Date(start); midnight.setHours(24, 0, 0, 0);
    for (let t = midnight.getTime(), i = 0; t <= end; t += DAY, i++) {
      if (i % every) continue;
      svg.append(s("text", { x: x(t), y: HEIGHT - 8, "text-anchor": "middle", class: "chart-axis" }, dateLabel(t)));
    }

    // Area under the best line, then the lines (stores first so the best line sits on top)
    const bestPath = stepPath(best, end, x, y);
    const firstBest = best.find((p) => p.price !== null);
    if (firstBest) {
      svg.append(s("defs", {}, s("linearGradient", { id: "chart-fill", x1: 0, y1: 0, x2: 0, y2: 1 },
        s("stop", { offset: "0", "stop-color": "var(--accent)", "stop-opacity": ".22" }),
        s("stop", { offset: "1", "stop-color": "var(--accent)", "stop-opacity": "0" }))));
      svg.append(s("path", { d: areaPath(best, end, x, y, HEIGHT - PAD.bottom), class: "chart-area" }));
    }
    for (const line of lines.slice(1)) {
      svg.append(s("path", { d: stepPath(line.points, end, x, y), class: "chart-line store", stroke: line.colour }));
    }
    svg.append(s("path", { d: bestPath, class: "chart-line best" }));

    // "Now" dot on the current best price
    const nowPrice = priceAt(best, end);
    if (nowPrice !== null) svg.append(s("circle", { cx: x(end), cy: y(nowPrice), r: 4.5, class: "chart-now" }));

    // Hover: a guide line and a tooltip with the price(s) on that day
    const guide = s("line", { y1: PAD.top, y2: HEIGHT - PAD.bottom, class: "chart-guide", visibility: "hidden" });
    const dot = s("circle", { r: 4, class: "chart-now", visibility: "hidden" });
    svg.append(guide, dot);
    const hit = s("rect", { x: PAD.left, y: 0, width: width - PAD.left - PAD.right, height: HEIGHT, fill: "transparent" });
    svg.append(hit);
    const move = (clientX) => {
      const box = svg.getBoundingClientRect();
      const px = Math.min(width - PAD.right, Math.max(PAD.left, ((clientX - box.left) / box.width) * width));
      const t = start + ((px - PAD.left) / (width - PAD.left - PAD.right)) * (end - start);
      const p = priceAt(best, t);
      guide.setAttribute("x1", px); guide.setAttribute("x2", px); guide.setAttribute("visibility", "visible");
      if (p !== null) { dot.setAttribute("cx", px); dot.setAttribute("cy", y(p)); dot.setAttribute("visibility", "visible"); }
      else dot.setAttribute("visibility", "hidden");
      tip.replaceChildren(
        h("div", { class: "chart-tip-date" }, new Date(t).toLocaleDateString("en-KE", { weekday: "short", day: "numeric", month: "short" })),
        h("div", { class: "chart-tip-best" }, p === null ? "Not tracked yet" : money(p)),
        ...lines.slice(1).map((l) => {
          const sp = priceAt(l.points, t);
          return sp === null ? null : h("div", { class: "chart-tip-row" },
            h("span", { class: "store-dot", style: `--dot:${l.colour}` }), `${l.store} ${money(sp)}`);
        }).filter(Boolean));
      tip.hidden = false;
      const left = (px / width) * box.width;
      tip.style.left = `${Math.min(box.width - 150, Math.max(0, left + 12))}px`;
    };
    hit.addEventListener("pointermove", (e) => move(e.clientX));
    hit.addEventListener("pointerdown", (e) => move(e.clientX));
    hit.addEventListener("pointerleave", () => { tip.hidden = true; guide.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });

    wrap.replaceChildren(svg, tip);
  };

  new ResizeObserver(() => draw()).observe(wrap);
  return wrap;
}
