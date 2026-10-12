// Verify the new Industries page + IndustryDetail breadth timeline render clean.
const fs = require("fs");
const path = require("path");
const babel = require("@babel/core");
const { JSDOM } = require("jsdom");

const BASE = process.env.BASE || "http://localhost:8420";
const dom = new JSDOM('<!DOCTYPE html><html><body><div id="root"></div></body></html>', {
  url: BASE + "/", pretendToBeVisual: true,
});
global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;
global.HTMLElement = dom.window.HTMLElement;
global.React = require("react");
global.ReactDOM = require("react-dom/client");

const realFetch = fetch;
const apiFetch = (p, opts) =>
  realFetch(p.startsWith("http") ? p : BASE + p, opts).then(async (r) => ({
    ok: r.ok, statusText: r.statusText,
    json: async () => {
      const d = await r.json();
      // The running :8420 server predates the new contract — inject the new
      // fields so the Industries page exercises the state/score_delta paths.
      if (p.indexOf("/api/industries") === 0 && Array.isArray(d)) {
        const states = ["Leader", "Emerging", "Neutral", "Fading", "Lagging"];
        d.forEach((row, i) => {
          row.state = states[i % states.length];
          row.score_delta = (i % 7) - 3;
          row.breadth_200 = 55;
        });
      }
      if (p.indexOf("/api/industry-detail") === 0 && d && !d.history) {
        d.history = [
          {dt: "2026-08-18", breadth_20: 40, breadth_50: 35, breadth_200: 30, chg_1w: 1, chg_1m: 2, score: 45},
          {dt: "2026-08-19", breadth_20: null, breadth_50: 38, breadth_200: 32, chg_1w: 1, chg_1m: 2, score: 48},
          {dt: "2026-08-20", breadth_20: 55, breadth_50: 44, breadth_200: 34, chg_1w: 1, chg_1m: 2, score: 52},
        ];
      }
      return d;
    },
  }));
global.fetch = apiFetch;
window.fetch = apiFetch;

const src = fs.readFileSync(path.join(__dirname, "app.jsx"), "utf8");
const compiled = babel.transformSync(src, {
  presets: [["@babel/preset-react", { runtime: "classic" }]],
  filename: "app.jsx",
}).code;

const errors = [];
window.addEventListener("error", (e) => errors.push("window: " + e.message));
console.error = (...a) => { errors.push(a.join(" ")); };

eval(compiled);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await sleep(2500);
  const root = document.getElementById("root");

  // Navigate to Industries
  const item = [...document.querySelectorAll(".sidebar-item")].find((el) => el.textContent.trim() === "Industries");
  if (!item) { console.log("FAIL  sidebar item 'Industries' not found"); process.exit(1); }
  item.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(2000);
  const html = root.innerHTML;
  const checks = [
    ["industries: title", "Industries"],
    ["industries: KPI Leading", "Leading"],
    ["industries: KPI breadth", "Avg breadth &gt;50MA"],
    ["industries: rankings", "Industry Rankings"],
    ["industries: gauge", "gauge"],
    ["industries: donut", "donut-wrap"],
    ["industries: heatmap", "Performance Heatmap"],
    ["industries: tf pill", "6M"],
    ["industries: rotation", "Capital Rotation"],
    ["industries: actionable movers", "Actionable Now"],
    ["industries: all table", "All Industries"],
    ["industries: delta col", "previous snapshot"],
    ["industries: state badge", "state-badge"],
  ];
  let failed = false;
  for (const [name, needle] of checks) {
    const ok = html.includes(needle);
    if (!ok) failed = true;
    console.log((ok ? "PASS" : "FAIL") + "  " + name);
  }

  // Click a treemap tile / a table row -> IndustryDetail with Breadth Timeline
  const row = document.querySelector(".hover-row td.fw-700");
  if (row) {
    row.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(2500);
    const dhtml = root.innerHTML;
    [["detail: breadth timeline", "Breadth Timeline"], ["detail: legend", "Above 200MA"]].forEach(([n, nd]) => {
      const ok = dhtml.includes(nd);
      if (!ok) failed = true;
      console.log((ok ? "PASS" : "FAIL") + "  " + n);
    });
  } else console.log("SKIP  no industry row to click");

  const realErrors = errors.filter((e) => !/act\(|not wrapped in act|useLayoutEffect/.test(e));
  console.log(realErrors.length ? "ERRORS:\n" + realErrors.slice(0, 8).join("\n---\n") : "NO JS ERRORS");
  process.exit(failed || realErrors.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
