// One-off check: mount the app in jsdom, navigate to the Screener view and
// assert the infographic dashboard + table render without JS errors.
const fs = require("fs");
const path = require("path");
const babel = require("@babel/core");
const { JSDOM } = require("jsdom");

const BASE = process.env.BASE || "http://localhost:8420";

const dom = new JSDOM('<!DOCTYPE html><html><body><div id="root"></div></body></html>', {
  url: BASE + "/",
  pretendToBeVisual: true,
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
    ok: r.ok,
    statusText: r.statusText,
    json: () => r.json(),
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
const origErr = console.error;
console.error = (...a) => { errors.push(a.join(" ")); };

eval(compiled);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await sleep(2500);
  const root = document.getElementById("root");
  const item = [...document.querySelectorAll(".sidebar-item")].find((el) =>
    el.textContent.trim() === "Screener"
  );
  if (!item) { console.log("FAIL sidebar: Screener item not found"); process.exit(1); }
  item.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(3000);
  const html = root.innerHTML;
  const checks = [
    ["telemetry", "Universe Telemetry"],
    ["pulse", "Momentum Pulse"],
    ["rrg", "Industry Rotation"],
    ["rrg dots svg", "rrg-dots"],
    ["leading quadrant", "Leading Quadrant"],
    ["dominant cluster", "Dominant Cluster"],
    ["hottest industry", "Hottest Industry"],
    ["industry bars", "Industry Ranking"],
    ["weakest industry", "Weakest Industry"],
    ["sector mix donut", "Sector Mix"],
    ["breadth donut", "1M Market Breadth"],
    ["clusters donut", "High-Momentum Clusters"],
    ["return leaders", "Return Leaders"],
    ["podium", "podium-block"],
    ["return bars", "Top Return Leaders"],
    ["standouts", "Standout Tickers"],
    ["table header", "ALL STOCKS — RANKINGS"],
    ["table hint", "CLICK A COLUMN HEADING TO SORT DESCENDING"],
    ["score col", "Score"],
  ];
  let fail = 0;
  for (const [name, needle] of checks) {
    const ok = html.includes(needle);
    console.log((ok ? "PASS " : "FAIL ") + name);
    if (!ok) fail++;
  }
  // table rows present?
  const rows = document.querySelectorAll("tbody tr").length;
  console.log("table rows: " + rows);
  // score values present in first row?
  const firstScore = document.querySelector("tbody tr .score-cell span");
  console.log("first row score: " + (firstScore ? firstScore.textContent : "NONE"));
  console.log(fail === 0 && errors.length === 0 ? "ALL OK" : "FAILURES: " + fail);
  if (errors.length) console.log("JS ERRORS:\n" + errors.slice(0, 5).join("\n"));
  process.exit(fail === 0 && errors.length === 0 ? 0 : 1);
})();
