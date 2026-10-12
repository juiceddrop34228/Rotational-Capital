// Smoke test: mount the compiled app in jsdom against the live local API,
// navigate each view, and assert key content renders without throwing.
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
  await sleep(2500); // let /api/dashboard + /api/config resolve and effects flush
  const root = document.getElementById("root");
  const html = root.innerHTML;

  const checks = [
    ["dashboard: benchmark", "Benchmark"],
    ["dashboard: EMA trend", "Trend (10/20 EMA)"],
    ["dashboard: market environment", "Market Environment"],
    ["dashboard: gauge svg", "gauge"],
    ["dashboard: index panel SPY", "S&amp;P 500"],
    ["dashboard: index panel QQQ", "Nasdaq 100"],
    ["dashboard: index panel DJI", "Dow Jones Industrial"],
    ["dashboard: index panel IWM", "Russell 2000"],
    ["dashboard: six return boxes", "YTD"],
    ["dashboard: entrance animation", "anim-fade-up"],
  ];

  // navigate: click sidebar items (All Sectors, Rotation, Momentum, Breadth, Playbook)
  const labels = ["All Sectors", "Rotation", "Momentum", "Breadth & Risk", "Playbook", "Watchlist", "EPs"];
  const navResults = [];
  for (const label of labels) {
    const item = [...document.querySelectorAll(".sidebar-item")].find((el) =>
      el.textContent.trim() === label
    );
    if (!item) { navResults.push(label + ": SIDEBAR ITEM NOT FOUND"); continue; }
    item.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(1800);
    navResults.push(label + ": " + root.innerHTML.length + " chars");
    if (label === "All Sectors") {
      const ths = [...document.querySelectorAll("th.sortable")];
      const firstTicker = () => document.querySelector("tbody tr .mono")?.textContent;
      const th1m = ths.find((t) => t.textContent.includes("1M"));
      if (th1m) {
        const defFirst = firstTicker();
        th1m.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        await sleep(300);
        const sortedFirst = firstTicker();
        const active = document.querySelector("th.sortable.active");
        th1m.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        await sleep(300);
        const restoredFirst = firstTicker();
        sortInfo = `default=${defFirst} sortedBy1M=${sortedFirst} arrow=${!!active} restored=${restoredFirst === defFirst}`;
      } else sortInfo = "1M sortable th not found (" + ths.length + " sortable ths)";
    }
  }

  let failed = false;
  for (const [name, needle] of checks) {
    const ok = html.includes(needle);
    if (!ok) failed = true;
    console.log((ok ? "PASS" : "FAIL") + "  " + name);
  }
  navResults.forEach((r) => console.log("NAV   " + r));
  console.log("SORT  " + sortInfo);
  const realErrors = errors.filter(
    (e) => !/act\(|not wrapped in act|useLayoutEffect/.test(e)
  );
  console.log(realErrors.length ? "ERRORS:\n" + realErrors.slice(0, 8).join("\n---\n") : "NO JS ERRORS");
  process.exit(failed || realErrors.length ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
