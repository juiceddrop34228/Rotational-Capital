const {useState, useEffect, useMemo, useRef} = React;
const ThemeContext = React.createContext("dark");
const API = "";

// The strategy dashboard inside the shared scanner shell. Markets is
// universal; sector ranking is CCI-based (50% performance + 50% CCI).
const STRATEGIES = [
  {id:"qullamaggie", label:"Qullamaggie"},
];
function strategyLabel(id){
  const s = STRATEGIES.find(x=>x.id===id);
  return s ? s.label : id;
}
function apiUrl(path, strategy){
  if(!strategy) return path;
  return path + (path.indexOf("?") >= 0 ? "&" : "?") + "strategy=" + strategy;
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------
function useApi(path, deps=[]) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  useEffect(() => {
    setLoading(true); setError(null);
    fetch(API + path)
      .then(r => { if(!r.ok) throw new Error(r.statusText); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, deps);
  return [data, loading, setData, error];
}

// Measure an element's visible width (ResizeObserver) — used to pin chart
// areas inside horizontally-scrollable tables to the viewport width.
function useContainerWidth(){
  // Callback ref (not useEffect+[]) so the observer still attaches when the
  // element only appears after an early-return loading state re-renders.
  const [el, setEl] = useState(null);
  const [w, setW] = useState(null);
  useEffect(()=>{
    if(!el) return;
    if(typeof ResizeObserver === "undefined"){ setW(el.clientWidth); return; }
    const ro = new ResizeObserver(es=>{ setW(es[0].contentRect.width); });
    ro.observe(el);
    setW(el.clientWidth);
    return ()=>ro.disconnect();
  },[el]);
  return [setEl, w];
}

function fmtPct(v){ if(v===null||v===undefined||isNaN(v)) return "—"; const s = v>=0?"+":""; return s+v.toFixed(2)+"%"; }
function fmtPct1(v){ if(v===null||v===undefined||isNaN(v)) return "—"; const s = v>=0?"+":""; return s+v.toFixed(1)+"%"; }
function fmtPrice(v){ if(v===null||v===undefined||isNaN(v)) return "—"; return "$"+v.toFixed(2); }
function fmtNumber(v){ if(v===null||v===undefined||isNaN(v)) return "—"; return v.toLocaleString(undefined,{maximumFractionDigits:0}); }
function fmtCap(v){ if(v===null||v===undefined||isNaN(v)) return "—"; return "$"+(v/1000).toFixed(2)+"B"; }
function fmtVol(v){ if(v===null||v===undefined||isNaN(v)) return "—"; if(v>=1e9) return (v/1e9).toFixed(2)+"B"; if(v>=1e6) return (v/1e6).toFixed(2)+"M"; return (v/1e3).toFixed(1)+"K"; }
function pctClass(v){ return v>=0?"pos":"neg"; }
function ratingLabelClass(label){
  if(label==="Buy"||label==="Strong Buy") return "pos";
  if(label==="Sell"||label==="Strong Sell") return "neg";
  return "text-dim";
}
// TradingView Recommend.All: 0 = strong sell .. 1 = strong buy
function fmtRating(v){
  if(v===null||v===undefined||isNaN(v)) return "—";
  const label = v>=0.8 ? "S.Buy" : v>=0.6 ? "Buy" : v>=0.4 ? "Neutral" : v>=0.2 ? "Sell" : "S.Sell";
  return v.toFixed(2)+" "+label;
}
function ratingClass(v){ return v>=0.6 ? "pos" : v<0.4 ? "neg" : ""; }
function stateClass(state){
  if(!state) return "";
  if(state==="leader"||state==="leading") return "state-leader";
  if(state==="emerging") return "state-emerging";
  if(state==="recovering") return "state-recovering";
  if(state==="fading") return "state-fading";
  if(state==="lagging") return "state-lagging";
  return "state-neutral";
}
function stateLabel(state){
  if(!state) return "Neutral";
  return state[0].toUpperCase()+state.slice(1);
}
function stateColor(state){
  if(state==="leader"||state==="leading") return "#00e676";
  if(state==="emerging") return "#7ee787";
  if(state==="recovering") return "#4cc9f0";
  if(state==="fading") return "#ff2e63";
  if(state==="lagging") return "#7a8494";
  return "#d9a03f";
}
const STATUS_BADGE = {
  actionable: ["ACTIONABLE", "ok"],
  emerging:   ["EMERGING", "pb"],
  extended:   ["EXTENDED", "ext"],
  watchlist:  ["WATCHLIST", "cap"],
  avoid:      ["AVOID", "avd"],
};
function StatusBadge({status}){
  const s = STATUS_BADGE[status];
  if(!s) return <span className="text-faint">—</span>;
  return <span className={"lb-badge "+s[1]}>{s[0]}</span>;
}
function ReasonChips({reasons}){
  if(!reasons || !reasons.length) return null;
  return <span className="reason-chips">{reasons.map(r=>(
    <span key={r} className="reason-chip">{r}</span>
  ))}</span>;
}
// Sector identity dots: distinct muted hues, stable per sector id.
const SEC_YELLOWS = ["#6ea8fe","#4cc9f0","#b388ff","#7ee787","#ff9f7a","#8ecae6","#c3a6ff","#90f1ef","#a3e635","#f72585","#5b8def","#7bd8c4","#d9a03f","#9aa4b2","#ff5d8f","#4dd0a6"];
function secColor(s){
  const id = (s && s.id) || 0;
  return SEC_YELLOWS[(id-1)%SEC_YELLOWS.length] || SEC_YELLOWS[0];
}
// min-max normalize a list of numbers to 0-100
function normList(vals){
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const span = (mx-mn)||1;
  return vals.map(v=> ((v-mn)/span)*100 );
}
function avg(arr){ if(!arr.length) return 0; return arr.reduce((a,b)=>a+b,0)/arr.length; }
function median(arr){
  if(!arr.length) return 0;
  const s=[...arr].sort((a,b)=>a-b);
  return s.length%2 ? s[(s.length-1)/2] : (s[s.length/2-1]+s[s.length/2])/2;
}

// ---------------------------------------------------------------------------
// Icons (stroke-based, white by default, no emojis)
// ---------------------------------------------------------------------------
const Icon = {
  dashboard: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
  sectors: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2 L22 8.5 L22 15.5 L12 22 L2 15.5 L2 8.5 Z"/><path d="M12 12 L22 8.5"/><path d="M12 12 L12 22"/><path d="M12 12 L2 8.5"/></svg>,
  etf: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>,
  settings: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
  menu: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>,
  up: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke={p.color||"currentColor"} strokeWidth="2.2"><path d="M4 17 L10 10 L14 14 L20 6"/><path d="M14 6 H20 V12"/></svg>,
  down: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke={p.color||"currentColor"} strokeWidth="2.2"><path d="M4 7 L10 14 L14 10 L20 18"/><path d="M14 18 H20 V12"/></svg>,
  flat: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke={p.color||"currentColor"} strokeWidth="2.2"><path d="M4 12 H20"/></svg>,
  flame: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke={p.color||"currentColor"} strokeWidth="1.8"><path d="M12 2 C9 7 6 9 6 13 a6 6 0 0 0 12 0 c0-2-1-3-2-4 c0 2-1 3-2 3 c1-3-1-6-2-10z"/></svg>,
  warn: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke={p.color||"currentColor"} strokeWidth="2"><path d="M12 3 L22 20 H2 Z"/><path d="M12 9 V13"/><circle cx="12" cy="16.5" r="0.6" fill={p.color||"currentColor"}/></svg>,
  star: (p) => <svg className="icon" viewBox="0 0 24 24" fill={p.filled?"currentColor":"none"} stroke="currentColor" strokeWidth="1.5"><path d="M12 3 L14.5 9.5 L21 10 L16 14.3 L17.6 21 L12 17.3 L6.4 21 L8 14.3 L3 10 L9.5 9.5 Z"/></svg>,
  search: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21 L16.5 16.5"/></svg>,
  refresh: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>,
  back: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18 L9 12 L15 6"/></svg>,
  expand: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18 L15 12 L9 6"/></svg>,
  cloud: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M7 18h10a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.6-1.8A4.5 4.5 0 0 0 7 18z"/><path d="M12 12v6"/><path d="M9.5 15.5L12 18l2.5-2.5"/></svg>,
  x: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>,
  table: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>,
  chart: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18"/><path d="M18 14l-4-4-3 3-4-5"/></svg>,
  bull: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 16c0-2 1.5-4 4-4s3 2 5 2 2-2 5-2 4 2 4 4v4H4z"/><circle cx="9" cy="9" r="2"/><circle cx="15" cy="9" r="2"/></svg>,
  bear: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 16c0-2 1.5-3 3-3s3 1 5 1 2-1 5-1 4 1 4 3v4H4z"/><circle cx="9" cy="9" r="2"/><circle cx="15" cy="9" r="2"/></svg>,
  arrowRight: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>,
  arrowTrendUp: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/></svg>,
  arrowTrendDown: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 18l-9.5-9.5-5 5L1 6"/><path d="M17 18h6v-6"/></svg>,
  target: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>,
  activity: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>,
  candles: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M7 4v2M7 18v2M17 2v3M17 19v3"/><rect x="4" y="6" width="6" height="12" rx="1"/><rect x="14" y="5" width="6" height="14" rx="1"/></svg>,
  check: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M4 12.5 L9.5 18 L20 6.5"/></svg>,
  zap: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2 L4 14 H11 L10 22 L20 9 H13 Z"/></svg>,
  bell: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>,
  sun: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42"/></svg>,
  moon: (p) => <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z"/></svg>,
};

function BrandLogo(){
  return (
    <svg className="brand-logo" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M8 3v5M8 23v6" stroke="#6f9fd2" strokeWidth="2"/>
      <rect x="4.5" y="8" width="7" height="15" rx="1" fill="#6f9fd2"/>
      <path d="M23 3v7M23 24v5" stroke="var(--text)" strokeWidth="2"/>
      <rect x="19.5" y="10" width="7" height="14" rx="1" fill="var(--text)"/>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Watchlist (shared state): breakout tickers, persisted in the backend.
// `map` = {ticker: true}; toggle adds/removes (no dupes). EP-tagged rows are
// excluded — EPs live in their own independent section with their own list.
// ---------------------------------------------------------------------------
function useWatchlist(refreshKey){
  const [items, setItems] = useState(null);
  function refresh(){ fetch("/api/watchlist").then(r=>r.json()).then(setItems).catch(()=>{}); }
  useEffect(()=>{ refresh(); }, [refreshKey]);
  const map = useMemo(()=>{
    const m = {};
    (items||[]).forEach(e=>{ if(e && e.ticker && e.category!=="ep") m[e.ticker] = true; });
    return m;
  }, [items]);
  function toggle(ticker){
    if(map[ticker]){
      fetch("/api/watchlist/"+encodeURIComponent(ticker), {method:"DELETE"}).then(refresh);
    }else{
      fetch("/api/watchlist", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ticker, category:"breakout"})}).then(refresh);
    }
  }
  return {items, map, toggle, refresh};
}

// Checkmark button shown next to every stock anywhere in the app. Filled/green
// when the stock is already watchlisted; click toggles add/remove.
function WatchBtn({wl, ticker}){
  if(!wl || !ticker) return null;
  const active = wl.map[ticker];
  return (
    <button className={"watch-btn "+(active?"active":"")}
      title={active ? "In watchlist — click to remove" : "Add to watchlist"}
      onClick={e=>{ e.stopPropagation(); wl.toggle(ticker); }}>
      <Icon.check/>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Chart primitives
// ---------------------------------------------------------------------------
function LineSpark({values, width=120, height=34, color="var(--accent)"}) {
  if(!values || values.length<2) return <svg width={width} height={height}></svg>;
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max-min)||1;
  const pts = values.map((v,i)=>{
    const x = (i/(values.length-1))*width;
    const y = height - ((v-min)/span)*height;
    return x+","+y;
  }).join(" ");
  return <svg width={width} height={height}><polyline className="draw" pathLength="1" points={pts} fill="none" stroke={color} strokeWidth="1.6"/></svg>;
}

function MiniSpark({values, width=100, height=30, color="var(--accent)", positive}) {
  if(!values || values.length<2) return <svg width={width} height={height}></svg>;
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max-min)||1;
  const c = positive===undefined ? color : (positive ? "var(--green)" : "var(--red)");
  const pts = values.map((v,i)=> (i/(values.length-1))*width + "," + (height - ((v-min)/span)*height)).join(" ");
  return <svg width={width} height={height}><polyline points={pts} fill="none" stroke={c} strokeWidth="1.5"/></svg>;
}

function HorizontalBar({value, max, color, height=6}) {
  const pct = max && max>0 ? Math.min(100, Math.max(0, (Math.abs(value)/max)*100)) : 0;
  return (
    <div className="bar-bg" style={{height}}>
      <div className="bar-fill" style={{width: pct+"%", background: color, marginLeft: value>=0?"50%":"calc(50% - "+pct+"%)"}}></div>
    </div>
  );
}

function ScoreBar({value}) {
  const pct = Math.max(0, Math.min(100, value));
  let color = "var(--red)";
  if(value>=50) color = "var(--amber)";
  if(value>=70) color = "var(--green)";
  return (
    <div className="bar-bg" style={{height:6, borderRadius:3}}>
      <div className={"bar-fill "+(value>=70?"leader":"")} style={{width:pct+"%", background:color, borderRadius:3}}></div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Relative Strength score (0-100). The backend (engine.score_and_rank over
// the FULL screener universe) attaches a universal `score` to every stock —
// it never changes no matter which group (screener / industry / sector / ETF
// holdings) the stock is viewed in, so it is used verbatim here. The local
// percentile computation below only runs as a fallback for rows that arrived
// without a backend score.
// ---------------------------------------------------------------------------
function rsScore(stocks){
  if(!stocks || !stocks.length) return stocks || [];
  if(stocks.every(s=> s.score!=null))
    return stocks.map(s=> ({...s, _score: Math.round(s.score*10)/10}));
  const perf = s=> 0.15*(s.chg_1w||0) + 0.50*(s.chg_1m||0) + 0.35*(s.chg_3m||0);
  const vals = stocks.map(perf);
  const n = vals.length;
  return stocks.map((s,i)=>{
    const below = vals.reduce((c,v)=> c + (v <= vals[i] ? 1 : 0), 0);
    return {...s, _score: Math.round(below/n*1000)/10};
  });
}
const withStockScores = rsScore;
const withMomentumScores = rsScore;

function extVsEma10(s){
  if(s.ext_ema10!=null) return s.ext_ema10;
  if(s.price!=null && s.ema10) return (s.price/s.ema10-1)*100;
  return null;
}

function AreaChart({series, width=640, height=220, pad=32, colors, yDomain}) {
  if(!series || series.length===0 || series[0].values.length<2) return <div className="empty">No data</div>;
  const allVals = series.flatMap(s=>s.values);
  const min = yDomain ? yDomain[0] : Math.min(...allVals);
  const max = yDomain ? yDomain[1] : Math.max(...allVals);
  const span = (max-min)||1;
  const n = series[0].values.length;
  const xFor = (i)=> pad + (i/(n-1))*(width-pad*2);
  const yFor = (v)=> height - pad - ((v-min)/span)*(height-pad*2);
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+height}>
      {[min, min+span/2, max].map((g,i)=> (
        <g key={i}>
          <line x1={pad} x2={width-pad} y1={yFor(g)} y2={yFor(g)} stroke="#1c2027" strokeWidth="1"/>
          <text x={4} y={yFor(g)+3} fontSize="9" fill="var(--text-faint)" fontFamily="var(--mono)">{g.toFixed(0)}</text>
        </g>
      ))}
      {series.map((s,si)=>{
        const pts = s.values.map((v,i)=> xFor(i)+","+yFor(v)).join(" ");
        return <polyline key={si} className="draw" pathLength="1" style={{animationDelay:(si*120)+"ms"}} points={pts} fill="none" stroke={s.color || colors[si%colors.length]} strokeWidth={s.width||2}/>;
      })}
    </svg>
  );
}

const RRG_LIGHT_PALETTE = ["#285f9e","#16735f","#8a5a00","#ad3151","#6c4b91","#14737e","#a44a2a","#587200","#a43d68","#4f5f70","#806016","#087469"];

function RRGChart({paths, midX=100, midY=0, labels}) {
  const theme = React.useContext(ThemeContext);
  const [selected, setSelected] = useState(null);
  const [containerRef, containerWidth] = useContainerWidth();
  if(!paths || paths.length===0) return <div className="empty">No rotation data</div>;
  const narrow = containerWidth!==null && containerWidth<480;
  const TRAIL_LEN = 8;
  const QL = labels || {tl:"IMPROVING", tr:"LEADING", bl:"LAGGING", br:"WEAKENING"};
  const w=560,h=420,pad=30;
  paths = paths.map(p=>({...p, points: p.points.slice(-TRAIL_LEN)}));
  const allX = paths.flatMap(p=>p.points.map(pt=>pt.x));
  const allY = paths.flatMap(p=>p.points.map(pt=>pt.y));
  const rangeX = Math.max(6, Math.max(...allX.map(v=>Math.abs(v-midX)))*1.3);
  const rangeY = Math.max(3, Math.max(...allY.map(v=>Math.abs(v-midY)))*1.3);
  const xFor = (v)=> w/2 + ((v-midX)/rangeX)*(w/2-pad);
  const yFor = (v)=> h/2 - ((v-midY)/rangeY)*(h/2-pad);
  const labelBoxes = [];
  const labelLayouts = paths.map(p=>{
    const last = p.points[p.points.length-1];
    const px=xFor(last.x), py=yFor(last.y);
    const left=px>w-80, textWidth=p.etf.length*7+8;
    const lx=left?px-8:px+8;
    let ly=py+3.5;
    const candidates=[0,-15,15,-30,30,-45,45,-60,60];
    for(const offset of candidates){
      const y=py+3.5+offset;
      const box={x1:left?lx-textWidth:lx,x2:left?lx:lx+textWidth,y1:y-11,y2:y+4};
      const collides=labelBoxes.some(b=>box.x1<b.x2&&box.x2>b.x1&&box.y1<b.y2&&box.y2>b.y1);
      if(y>16&&y<h-10&&!collides){ ly=y; labelBoxes.push(box); break; }
    }
    return {left,lx,ly};
  });
  const selectedPath = selected===null ? null : paths[selected];
  const selectedPoint = selectedPath ? selectedPath.points[selectedPath.points.length-1] : null;
  return (
    <div className="rrg-chart" ref={containerRef}>
      {narrow && <div className="chart-scroll-note">Scroll horizontally to inspect all sectors · select a point for values</div>}
      <div className="responsive-chart-scroll">
        <svg width="100%" viewBox={"0 0 "+w+" "+h} style={narrow?{width:w,minWidth:w}:undefined}>
          <rect x={w/2} y={0} width={w/2} height={h/2} fill="rgba(62,207,142,0.05)"/>
          <rect x={0} y={0} width={w/2} height={h/2} fill="rgba(217,164,65,0.05)"/>
          <rect x={0} y={h/2} width={w/2} height={h/2} fill="rgba(239,91,91,0.05)"/>
          <rect x={w/2} y={h/2} width={w/2} height={h/2} fill="rgba(91,141,239,0.05)"/>
          <line x1={w/2} x2={w/2} y1={0} y2={h} stroke="#2a303a"/><line x1={0} x2={w} y1={h/2} y2={h/2} stroke="#2a303a"/>
          <text x={w-4} y={14} fontSize="10" fill="var(--green)" textAnchor="end">{QL.tr}</text>
          <text x={4} y={14} fontSize="10" fill="var(--amber)">{QL.tl}</text>
          <text x={4} y={h-6} fontSize="10" fill="var(--red)">{QL.bl}</text>
          <text x={w-4} y={h-6} fontSize="10" fill="var(--accent)" textAnchor="end">{QL.br}</text>
          {paths.map((p,pi)=>{
            const pts = p.points.map(pt=> xFor(pt.x)+","+yFor(pt.y)).join(" ");
            const last = p.points[p.points.length-1];
            const color = theme==="light" ? RRG_LIGHT_PALETTE[pi%RRG_LIGHT_PALETTE.length] : p.color;
            const label = labelLayouts[pi];
            return (
              <g key={p.etf} className="rrg-sector" role="button" tabIndex={0}
                aria-label={p.etf+" RS-Ratio "+last.x.toFixed(2)+", RS-Momentum "+last.y.toFixed(2)}
                onClick={()=>setSelected(pi)} onFocus={()=>setSelected(pi)}
                onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();setSelected(pi);}}}>
                <title>{p.etf+" · RS-Ratio "+last.x.toFixed(2)+" · RS-Momentum "+last.y.toFixed(2)}</title>
                <polyline className="draw" pathLength="1" style={{animationDelay:(pi*90)+"ms"}} points={pts} fill="none" stroke={color} strokeWidth={theme==="light"?1.4:1.1} opacity={theme==="light"?0.58:0.35}/>
                {p.points.map((pt,i)=> i<p.points.length-1 &&
                  <circle key={i} className="pop-in" style={{animationDelay:(pi*90+i*40)+"ms"}} cx={xFor(pt.x)} cy={yFor(pt.y)} r="1.1" fill={color} opacity={theme==="light"?0.65:0.4}/>)}
                <circle className="pop-in" style={{animationDelay:(pi*90+p.points.length*40)+"ms"}} cx={xFor(last.x)} cy={yFor(last.y)} r={selected===pi?6:4.5} fill={color} stroke="var(--bg)" strokeWidth="1.5"/>
                <text className="pop-in" style={{animationDelay:(pi*90+p.points.length*40+60)+"ms"}} x={label.lx} y={label.ly} fontSize="11" fontWeight="700" fill={color}
                  textAnchor={label.left?"end":"start"} stroke="var(--bg)" strokeWidth="3" paintOrder="stroke">{p.etf}</text>
              </g>
            );
          })}
        </svg>
      </div>
      {selectedPath && selectedPoint && <div className="rrg-detail" aria-live="polite"><strong>{selectedPath.etf}</strong><span>RS-Ratio {selectedPoint.x.toFixed(2)}</span><span>RS-Momentum {selectedPoint.y.toFixed(2)}</span></div>}
    </div>
  );
}

// Dots-only RRG scatter for the industries page: no trails, no always-on
// labels — each industry is one circle, color-coded by sector, and hovering a
// circle pops a tooltip with the industry name and its sector.
const RRG_DOT_CSS = `
.rrg-dots{position:relative;}
.rrg-dots circle.dot{cursor:pointer;}
.rrg-dot-tip{position:absolute;pointer-events:none;transform:translate(-50%,-130%);
  background:#161b22;border:1px solid var(--border);border-radius:6px;
  padding:6px 10px;font-size:12px;font-weight:700;white-space:nowrap;z-index:5;}
.rrg-dot-tip .tip-sector{font-size:10.5px;font-weight:600;opacity:.85;}
.rrg-dot-legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:8px;font-size:10.5px;color:var(--text-dim);}
.rrg-dot-legend .leg{display:flex;align-items:center;gap:5px;}
.rrg-dot-legend .sw{width:8px;height:8px;border-radius:50%;flex-shrink:0;}`;
const SECTOR_PALETTE = ["#5b8def","#3ecf8e","#ffd166","#ef5b5b","#b388eb",
                        "#4dd0e1","#ff8a65","#a3e635","#f472b6","#8d99ae",
                        "#f4d35e","#2ec4b6"];

function RRGDots({rows, midX, midY, labels, onSelect, compact}) {
  const theme = React.useContext(ThemeContext);
  const [hover, setHover] = useState(null); // index into rows
  if(!rows || rows.length===0) return <div className="empty">No rotation data</div>;
  const QL = labels || {tl:"IMPROVING", tr:"LEADING", bl:"LAGGING", br:"WEAKENING"};
  const w=560,h=compact?340:420,pad=30;
  const sectors = [...new Set(rows.map(r=>r.sector||"Other"))].sort();
  const palette = theme==="light" ? RRG_LIGHT_PALETTE : SECTOR_PALETTE;
  const colorOf = s=> palette[sectors.indexOf(s||"Other") % palette.length];
  const rangeX = Math.max(20, Math.max(...rows.map(r=>Math.abs(r.x-midX)))*1.3);
  const rangeY = Math.max(10, Math.max(...rows.map(r=>Math.abs(r.y-midY)))*1.3);
  const xFor = v=> w/2 + ((v-midX)/rangeX)*(w/2-pad);
  const yFor = v=> h/2 - ((v-midY)/rangeY)*(h/2-pad);
  const hv = hover!=null ? rows[hover] : null;
  return (
    <div className="rrg-dots">
      <style>{RRG_DOT_CSS}</style>
      <svg width="100%" viewBox={"0 0 "+w+" "+h}>
        <rect x={w/2} y={0} width={w/2} height={h/2} fill="rgba(62,207,142,0.05)"/>
        <rect x={0} y={0} width={w/2} height={h/2} fill="rgba(217,164,65,0.05)"/>
        <rect x={0} y={h/2} width={w/2} height={h/2} fill="rgba(239,91,91,0.05)"/>
        <rect x={w/2} y={h/2} width={w/2} height={h/2} fill="rgba(91,141,239,0.05)"/>
        <line x1={w/2} x2={w/2} y1={0} y2={h} stroke="#2a303a"/><line x1={0} x2={w} y1={h/2} y2={h/2} stroke="#2a303a"/>
        <text x={w-4} y={14} fontSize="9" fill="var(--green)" textAnchor="end">{QL.tr}</text>
        <text x={4} y={14} fontSize="9" fill="var(--amber)">{QL.tl}</text>
        <text x={4} y={h-6} fontSize="9" fill="var(--red)">{QL.bl}</text>
        <text x={w-4} y={h-6} fontSize="9" fill="var(--accent)" textAnchor="end">{QL.br}</text>
        {rows.map((r,i)=>(
          <circle key={r.industry} className="dot pop-in"
            style={{animationDelay:(i*12)+"ms"}}
            cx={xFor(r.x)} cy={yFor(r.y)} r={hover===i?7:5}
            fill={colorOf(r.sector)}
            stroke={hover===i?"#fff":"var(--bg)"} strokeWidth="1.5"
            opacity={hover==null||hover===i?1:0.55}
            onMouseEnter={()=>setHover(i)} onMouseLeave={()=>setHover(null)}
            onClick={onSelect? ()=>onSelect(r.industry, null) : undefined}/>
        ))}
      </svg>
      {hv && (
        <div className="rrg-dot-tip" style={{left:(xFor(hv.x)/w*100)+"%", top:(yFor(hv.y)/h*100)+"%"}}>
          <div>{hv.industry}</div>
          <div className="tip-sector" style={{color:colorOf(hv.sector)}}>{hv.sector||"Other"}</div>
        </div>
      )}
      <div className="rrg-dot-legend">
        {sectors.map(s=>(
          <span key={s} className="leg"><span className="sw" style={{background:colorOf(s)}}/>{s}</span>
        ))}
      </div>
    </div>
  );
}

function RadarChart({axes, color="var(--accent)"}) {
  const w=220,h=220,cx=110,cy=110,r=85;
  const n=axes.length;
  const pt = (i,val)=>{
    const angle = -Math.PI/2 + (i*2*Math.PI/n);
    const rad = (val/100)*r;
    return [cx+rad*Math.cos(angle), cy+rad*Math.sin(angle)];
  };
  const poly = axes.map((a,i)=>pt(i,a.v).join(",")).join(" ");
  return (
    <svg width={w} height={h} viewBox={"0 0 "+w+" "+h}>
      {[0.25,0.5,0.75,1].map((f,i)=> <polygon key={i} points={axes.map((a,ai)=>pt(ai,f*100).join(",")).join(" ")} fill="none" stroke="#20262f" strokeWidth="1"/>)}
      {axes.map((a,i)=> <line key={i} x1={cx} y1={cy} x2={pt(i,100)[0]} y2={pt(i,100)[1]} stroke="#20262f" strokeWidth="1"/>)}
      <polygon points={poly} fill={color.replace(")",",0.25)").replace("rgb","rgba").replace("#","") ? "rgba(91,141,239,0.25)" : "rgba(91,141,239,0.25)"} stroke={color} strokeWidth="2"/>
      {axes.map((a,i)=>{
        const angle = -Math.PI/2 + (i*2*Math.PI/n);
        const lx = cx+(r+22)*Math.cos(angle), ly = cy+(r+22)*Math.sin(angle);
        return <text key={i} x={lx} y={ly} fontSize="9" fill="var(--text-dim)" textAnchor="middle">{a.label}</text>;
      })}
    </svg>
  );
}

function VolumeExpansionBars({holdings}) {
  const sorted = [...holdings].sort((a,b)=>b.volume_ratio-a.volume_ratio).slice(0,12);
  if(sorted.length===0) return <div className="empty">No names post-filter</div>;
  const w=640,rowH=22,pad=110;
  const h = sorted.length*rowH+16;
  const maxV = Math.max(...sorted.map(h=>h.volume_ratio),1);
  return (
    <svg width="100%" viewBox={"0 0 "+w+" "+h}>
      {sorted.map((d,i)=>{
        const bw = (d.volume_ratio/maxV)*(w-pad-30);
        const y=i*rowH+6;
        return (
          <g key={d.stock_ticker}>
            <text x={pad-6} y={y+10} fontSize="10" fill="var(--text-dim)" fontFamily="var(--mono)" textAnchor="end">{d.stock_ticker}</text>
            <rect className="bar-grow" style={{animationDelay:(i*45)+"ms"}} x={pad} y={y} width={bw} height={12} fill={d.volume_ratio>2?"var(--amber)":"var(--accent)"} opacity="0.85"/>
            <text x={pad+bw+4} y={y+10} fontSize="9.5" fill="var(--text-faint)" fontFamily="var(--mono)">{d.volume_ratio.toFixed(2)}x</text>
          </g>
        );
      })}
    </svg>
  );
}

function ContributionBars({holdings}) {
  const top = holdings.filter(h=>h.classification==='leader').slice(0,8);
  const bottom = holdings.filter(h=>h.classification==='laggard').slice(-8);
  const all = [...top, ...bottom];
  if(all.length===0) return <div className="empty">No holdings pass filters</div>;
  const maxAbs = Math.max(...all.map(h=>Math.abs(h.chg_1m)), 1);
  const w=640,rowH=22,pad=110;
  const h = all.length*rowH+20;
  return (
    <svg width="100%" viewBox={"0 0 "+w+" "+h}>
      <line x1={pad} x2={pad} y1={0} y2={h} stroke="#2a303a"/>
      {all.map((d,i)=>{
        const barMax = (w-pad-20)/2;
        const bw = (Math.abs(d.chg_1m)/maxAbs)*barMax;
        const isPos = d.chg_1m>=0;
        const x = isPos? pad : pad-bw;
        const y = i*rowH+6;
        return (
          <g key={d.stock_ticker}>
            <text x={pad-6} y={y+10} fontSize="10" fill="var(--text-dim)" fontFamily="var(--mono)" textAnchor="end">{d.stock_ticker}</text>
            <rect className="bar-grow" style={{animationDelay:(i*45)+"ms"}} x={x} y={y} width={bw} height={12} fill={isPos?"var(--green)":"var(--red)"} opacity={d.classification==='leader'?1:0.7}/>
            <text x={isPos? x+bw+4 : x-4} y={y+10} fontSize="9.5" fill="var(--text-faint)" fontFamily="var(--mono)" textAnchor={isPos?"start":"end"}>{fmtPct(d.chg_1m)}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Generic chart helpers (Part 2)
// ---------------------------------------------------------------------------
function Scatter({points, width=560, height=360, pad=42, xMid=null, yMid=null, quad=null, bubble=false}) {
  if(!points || points.length===0) return <div className="empty">No data</div>;
  const xs = points.map(p=>p.x), ys = points.map(p=>p.y);
  let xMin = Math.min(...xs), xMax = Math.max(...xs);
  let yMin = Math.min(...ys), yMax = Math.max(...ys);
  if(xMid!==null && xMid!==undefined){ xMin=Math.min(xMin,xMid); xMax=Math.max(xMax,xMid); }
  if(yMid!==null && yMid!==undefined){ yMin=Math.min(yMin,yMid); yMax=Math.max(yMax,yMid); }
  const xPad = ((xMax-xMin)*0.12)||1, yPad = ((yMax-yMin)*0.12)||1;
  xMin-=xPad; xMax+=xPad; yMin-=yPad; yMax+=yPad;
  const xFor = v=> pad + ((v-xMin)/(xMax-xMin))*(width-pad-14);
  const yFor = v=> height - pad - ((v-yMin)/(yMax-yMin))*(height-pad-10);
  const mx = (xMid!==null && xMid!==undefined) ? xFor(xMid) : null;
  const my = (yMid!==null && yMid!==undefined) ? yFor(yMid) : null;
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+height}>
      {quad && mx!==null && my!==null && (
        <g>
          <rect x={pad} y={10} width={mx-pad} height={my-10} fill={quad.tl.color} opacity="0.05"/>
          <rect x={mx} y={10} width={width-14-mx} height={my-10} fill={quad.tr.color} opacity="0.05"/>
          <rect x={pad} y={my} width={mx-pad} height={height-pad-my} fill={quad.bl.color} opacity="0.05"/>
          <rect x={mx} y={my} width={width-14-mx} height={height-pad-my} fill={quad.br.color} opacity="0.05"/>
          <text x={pad+6} y={22} fontSize="9" fill={quad.tl.color}>{quad.tl.label}</text>
          <text x={width-20} y={22} fontSize="9" fill={quad.tr.color} textAnchor="end">{quad.tr.label}</text>
          <text x={pad+6} y={height-pad-6} fontSize="9" fill={quad.bl.color}>{quad.bl.label}</text>
          <text x={width-20} y={height-pad-6} fontSize="9" fill={quad.br.color} textAnchor="end">{quad.br.label}</text>
        </g>
      )}
      {mx!==null && <line x1={mx} x2={mx} y1={10} y2={height-pad} stroke="#2a303a"/>}
      {my!==null && <line x1={pad} x2={width-14} y1={my} y2={my} stroke="#2a303a"/>}
      {points.map((p,i)=>(
        <g key={i}>
          <circle className="pop-in" style={{animationDelay:(i*35)+"ms"}} cx={xFor(p.x)} cy={yFor(p.y)} r={bubble ? Math.max(4, Math.min(18, (p.r||1)*7)) : 5}
            fill={p.color} opacity={bubble?0.55:0.85} stroke={p.color} strokeWidth="1"/>
          <text className="pop-in" style={{animationDelay:(i*35+80)+"ms"}} x={xFor(p.x)+ (bubble?10:8)} y={yFor(p.y)+3} fontSize="10" fontWeight="700" fill={p.color} fontFamily="var(--mono)">{p.label}</text>
          <title>{p.label}: {p.x.toFixed(1)}, {p.y.toFixed(2)}</title>
        </g>
      ))}
    </svg>
  );
}

function HBars({rows, width=560, rowH=24, padL=130, padR=56, fmt, refLine}) {
  if(!rows || rows.length===0) return <div className="empty">No data</div>;
  const maxV = Math.max(...rows.map(r=>r.value), refLine?refLine.x:0, 0.0001);
  const minV = Math.min(...rows.map(r=>r.value), 0);
  const span = (maxV-minV)||1;
  const h = rows.length*rowH + 8;
  const xFor = v=> padL + ((v-minV)/span)*(width-padL-padR);
  const zeroX = xFor(Math.max(0, minV));
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+h}>
      {minV<0 && <line x1={xFor(0)} x2={xFor(0)} y1={0} y2={h} stroke="#2a303a"/>}
      {refLine && (
        <g>
          <line x1={xFor(refLine.x)} x2={xFor(refLine.x)} y1={0} y2={h} stroke="var(--text-faint)" strokeDasharray="4,3"/>
          <text x={xFor(refLine.x)} y={h-1} fontSize="9" fill="var(--text-faint)" textAnchor="middle">{refLine.label}</text>
        </g>
      )}
      {rows.map((r,i)=>{
        const y = i*rowH+4;
        const x0 = xFor(Math.min(0,r.value)), x1 = xFor(Math.max(0,r.value));
        const bw = Math.max(1.5, x1-x0);
        return (
          <g key={r.label}>
            <text x={padL-8} y={y+11} fontSize="10.5" fill="var(--text-dim)" textAnchor="end">{r.label}</text>
            <rect className="bar-grow" style={{animationDelay:(i*45)+"ms"}} x={x0} y={y} width={bw} height={rowH-10} fill={r.color} opacity="0.85" rx="2"/>
            <text x={r.value>=0 || x0-50<padL ? x1+5 : x0-5} y={y+11} fontSize="10" fill="var(--text-faint)" fontFamily="var(--mono)"
              textAnchor={r.value>=0 || x0-50<padL ? "start" : "end"}>{fmt?fmt(r.value):r.value}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Donut({segments, size=170, thickness=26, centerLabel}) {
  const total = segments.reduce((a,s)=>a+s.value,0);
  if(!total) return <div className="empty">No data</div>;
  const r = (size-thickness)/2, C = 2*Math.PI*r;
  let off = 0;
  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox={"0 0 "+size+" "+size}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1a1e24" strokeWidth={thickness}/>
        {segments.map((s,i)=>{
          const len = s.value/total*C;
          const el = <circle key={i} className="donut-seg" style={{animationDelay:(i*90)+"ms"}} cx={size/2} cy={size/2} r={r} fill="none" stroke={s.color} strokeWidth={thickness}
            strokeDasharray={len+" "+(C-len)} strokeDashoffset={-off} transform={"rotate(-90 "+size/2+" "+size/2+")"}/>;
          off += len;
          return el;
        })}
        {centerLabel && <text x={size/2} y={size/2+4} fontSize="15" fontWeight="700" fill="var(--text)" textAnchor="middle" fontFamily="var(--mono)">{centerLabel}</text>}
      </svg>
      <div className="donut-legend">
        {segments.map((s,i)=>(
          <span key={i}><span className="legend-dot" style={{background:s.color}}></span>{s.label} — {s.value}</span>
        ))}
      </div>
    </div>
  );
}

function Gauge({value, width=140, height=84, label}) {
  const cx=70, cy=66, r=52;
  const clamped = Math.max(0, Math.min(100, value));
  const color = clamped>=60 ? "var(--green)" : clamped>=40 ? "var(--amber)" : "var(--red)";
  const pt = (frac, rr) => { const a = Math.PI - frac*Math.PI; return [cx+(rr===undefined?r:rr)*Math.cos(a), cy-(rr===undefined?r:rr)*Math.sin(a)]; };
  const arc = (f0,f1) => { const [x0,y0]=pt(f0), [x1,y1]=pt(f1); return "M "+x0.toFixed(2)+" "+y0.toFixed(2)+" A "+r+" "+r+" 0 0 1 "+x1.toFixed(2)+" "+y1.toFixed(2); };
  const zones = [[0,0.4,"var(--red)"],[0.4,0.6,"var(--amber)"],[0.6,1,"var(--green)"]];
  const [nx,ny] = pt(clamped/100, r-16);
  return (
    <svg className="gauge" width={width} height={height} viewBox={"0 0 "+width+" "+height}>
      <path d={arc(0,1)} fill="none" stroke="#1a1e24" strokeWidth="10" strokeLinecap="round"/>
      {zones.map((z,i)=> <path key={i} d={arc(z[0],z[1])} fill="none" stroke={z[2]} strokeWidth="10" opacity="0.35"/>)}
      <line className="gauge-needle" x1={cx} y1={cy} x2={nx.toFixed(2)} y2={ny.toFixed(2)} stroke="var(--text)" strokeWidth="2" strokeLinecap="round"/>
      <circle cx={cx} cy={cy} r="3.5" fill="var(--text)"/>
      <text x={cx} y={cy+15} fontSize="13" fontWeight="700" fill={color} textAnchor="middle" fontFamily="var(--mono)">{clamped.toFixed(0)}</text>
      {label && <text x={cx} y={cy-46} fontSize="9" fill="var(--text-dim)" textAnchor="middle">{label}</text>}
    </svg>
  );
}

// Large gradient area chart for the benchmark composite (market_history),
// with a drawn line and a pulsing last-value marker.
function MarketAreaChart({values, width=640, height=480, pad=30}) {
  if(!values || values.length<2) return <div className="empty">No data</div>;
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max-min)||1;
  const n = values.length;
  const xFor = i=> pad + (i/(n-1))*(width-pad-8);
  const yFor = v=> height - pad + 4 - ((v-min)/span)*(height-pad-16);
  const pts = values.map((v,i)=> xFor(i).toFixed(1)+","+yFor(v).toFixed(1)).join(" ");
  const area = "M "+xFor(0).toFixed(1)+","+(height-pad+4)+" L "+pts.replace(/ /g," L ")+" L "+xFor(n-1).toFixed(1)+","+(height-pad+4)+" Z";
  const last = values[n-1];
  const lineColor = last>=values[0] ? "var(--green)" : "var(--red)";
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+height}>
      <defs>
        <linearGradient id="mktAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.30"/>
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0.02"/>
        </linearGradient>
      </defs>
      {[min, min+span/2, max].map((g,i)=>(
        <g key={i}>
          <line x1={pad} x2={width-8} y1={yFor(g)} y2={yFor(g)} stroke="#1c2027" strokeWidth="1"/>
          <text x={4} y={yFor(g)+3} fontSize="10" fill="var(--text-faint)" fontFamily="var(--mono)">{g.toFixed(1)}</text>
        </g>
      ))}
      <path d={area} fill="url(#mktAreaGrad)"/>
      <polyline className="draw" pathLength="1" points={pts} fill="none" stroke={lineColor} strokeWidth="2"/>
      <circle className="pop-in" style={{animationDelay:"500ms"}} cx={xFor(n-1)} cy={yFor(last)} r="4" fill={lineColor} stroke="var(--bg)" strokeWidth="1.5"/>
      <text x={xFor(n-1)-8} y={yFor(last)-9} fontSize="12" fontWeight="700" fill={lineColor} textAnchor="end" fontFamily="var(--mono)">{last.toFixed(2)}</text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// TradingView charts (advanced chart widget, lazy-loaded) + chart layout
// customization. Every chart carries the 5/10/20/50/200 EMA studies; the
// numeric EMA readout (EmaStrip) renders below the chart.
// ---------------------------------------------------------------------------
const EMA_DEFS = [["EMA 5","ema5"],["EMA 10","ema10"],["EMA 20","ema20"],["EMA 50","ema50"],["EMA 200","ema200"]];
// Blue gradient, fastest EMA lightest → slowest EMA darkest. All are EMAs (MAExp).
const EMA_COLORS = {ema5:"#a5d6ff", ema10:"#79c0ff", ema20:"#539bf5", ema50:"#1f6feb", ema200:"#0d419d"};
const EMA_COLORS_LIGHT = {ema5:"#6b8ba6", ema10:"#4f7898", ema20:"#396f9f", ema50:"#28537d", ema200:"#183c61"};
// Each study instance gets a uid so studies_overrides can color them individually.
const EMA_STUDIES = [5,10,20,50,200].map(n=>({id:"MAExp@tv-basicstudies", uid:"ema"+n, inputs:{length:n}}));
const EMA_STUDY_OVERRIDES = Object.fromEntries(EMA_DEFS.map(([,key])=>[key+".plot.color", EMA_COLORS[key]]));
const EMA_STUDY_OVERRIDES_LIGHT = Object.fromEntries(EMA_DEFS.map(([,key])=>[key+".plot.color", EMA_COLORS_LIGHT[key]]));

let _tvScriptPromise = null;
function loadTvScript(){
  if(!_tvScriptPromise){
    _tvScriptPromise = new Promise((resolve, reject)=>{
      const s = document.createElement("script");
      s.src = "https://s3.tradingview.com/tv.js";
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  return _tvScriptPromise;
}

let _tvUid = 0;
function TVChart({symbol, interval="D", height=360}){
  const ref = useRef(null);
  const theme = React.useContext(ThemeContext);
  const [visible, setVisible] = useState(false);
  const [failed, setFailed] = useState(false);
  // Lazy-mount: only build the (heavy) widget when the chart scrolls into view.
  useEffect(()=>{
    const el = ref.current;
    if(!el) return;
    if(typeof IntersectionObserver === "undefined"){ setVisible(true); return; }
    const io = new IntersectionObserver(entries=>{
      entries.forEach(e=>{ if(e.isIntersecting){ setVisible(true); io.disconnect(); } });
    }, {rootMargin:"300px"});
    io.observe(el);
    return ()=>io.disconnect();
  },[]);
  useEffect(()=>{
    if(!visible || !ref.current) return;
    let cancelled = false;
    loadTvScript().then(()=>{
      if(cancelled || !ref.current) return;
      if(!window.TradingView){ setFailed(true); return; }
      const id = "tv-chart-"+(++_tvUid);
      ref.current.innerHTML = "";
      const holder = document.createElement("div");
      holder.id = id;
      holder.style.height = height+"px";
      ref.current.appendChild(holder);
      try{
        new window.TradingView.widget({
          container_id: id,
          symbol: symbol,
          interval: interval,
          theme: theme,
          style: "1",
          locale: "en",
          width: "100%",
          height: height,
          hide_side_toolbar: true,
          allow_symbol_change: false,
          save_image: false,
          studies: EMA_STUDIES,
          studies_overrides: theme==="dark" ? EMA_STUDY_OVERRIDES : EMA_STUDY_OVERRIDES_LIGHT,
          // Logarithmic price scale everywhere (not the auto-adjusted default).
          overrides: {"mainSeriesProperties.priceAxisProperties.log": true},
        });
      }catch(e){ setFailed(true); }
    }).catch(()=>{ if(!cancelled) setFailed(true); });
    return ()=>{ cancelled = true; if(ref.current) ref.current.innerHTML = ""; };
  },[visible, symbol, interval, height, theme]);
  return (
    <div className="tv-chart" ref={ref} style={{minHeight:height}}>
      {!visible && !failed && <div className="tv-chart-placeholder" style={{height:height}}>Chart loads when visible…</div>}
      {failed && <div className="tv-chart-placeholder" style={{height:height}}>Chart unavailable — TradingView widget needs internet access</div>}
    </div>
  );
}

// Numeric 5/10/20/50/200 EMA readout rendered below a chart. Symmetric cells.
function EmaStrip({emas, price}){
  const theme = React.useContext(ThemeContext);
  const colors = theme==="dark" ? EMA_COLORS : EMA_COLORS_LIGHT;
  return (
    <div className="ema-strip">
      {EMA_DEFS.map(([label, key])=>{
        const v = emas ? emas[key] : null;
        const above = (v!=null && price!=null) ? price >= v : null;
        const c = colors[key];
        return (
          <div key={key} className="ema-cell">
            <div className="stat-label"><span className="ema-dot" style={{background:c}}></span>{label}</div>
            <div className="ema-val" style={{color:c}}>{v!=null ? fmtPrice(v) : "—"}</div>
            <div className={"ema-state "+(above===null?"":above?"pos":"neg")}>{above===null ? "" : above ? "Above" : "Below"}</div>
          </div>
        );
      })}
    </div>
  );
}

// --- Chart layout customization (persisted to localStorage) ---
const CHART_SIZE_PX = {S:340, M:460, L:600};
const CHART_INTERVAL_PRESETS = [
  {id:"swing", label:"1H / D / W", intervals:["60","D","W"]},
  {id:"intraday", label:"15m / 1H / D", intervals:["15","60","D"]},
  {id:"position", label:"D / W / M", intervals:["D","W","M"]},
];
const CHART_LAYOUT_DEFAULT = {perRow:3, size:"M", preset:"swing", showEma:true};
function useChartLayout(){
  const [layout, setLayout] = useState(()=>{
    try{ return {...CHART_LAYOUT_DEFAULT, ...(JSON.parse(localStorage.getItem("chart-layout"))||{})}; }
    catch(e){ return {...CHART_LAYOUT_DEFAULT}; }
  });
  function update(patch){
    setLayout(l=>{
      const nl = {...l, ...patch};
      try{ localStorage.setItem("chart-layout", JSON.stringify(nl)); }catch(e){}
      return nl;
    });
  }
  return [layout, update];
}
function layoutIntervals(layout){
  const p = CHART_INTERVAL_PRESETS.find(x=>x.id===layout.preset) || CHART_INTERVAL_PRESETS[0];
  return p.intervals.slice(0, layout.perRow);
}

// Symmetric settings row: charts per row / size / timeframe set / EMA readout.
function ChartLayoutSettings({layout, onChange}){
  return (
    <div className="chart-settings">
      <div className="chart-settings-group">
        <span className="stat-label">Charts per row</span>
        <div className="toggle-row" style={{marginBottom:0}}>
          {[1,2,3].map(n=>(
            <div key={n} className={"toggle "+(layout.perRow===n?"active":"")} onClick={()=>onChange({perRow:n})}>{n}</div>
          ))}
        </div>
      </div>
      <div className="chart-settings-group">
        <span className="stat-label">Chart size</span>
        <div className="toggle-row" style={{marginBottom:0}}>
          {["S","M","L"].map(s=>(
            <div key={s} className={"toggle "+(layout.size===s?"active":"")} onClick={()=>onChange({size:s})}>{s}</div>
          ))}
        </div>
      </div>
      <div className="chart-settings-group">
        <span className="stat-label">Timeframes</span>
        <div className="toggle-row" style={{marginBottom:0}}>
          {CHART_INTERVAL_PRESETS.map(p=>(
            <div key={p.id} className={"toggle "+(layout.preset===p.id?"active":"")} onClick={()=>onChange({preset:p.id})}>{p.label}</div>
          ))}
        </div>
      </div>
      <div className="chart-settings-group">
        <span className="stat-label">EMA readout</span>
        <div className="toggle-row" style={{marginBottom:0}}>
          <div className={"toggle "+(layout.showEma?"active":"")} onClick={()=>onChange({showEma:!layout.showEma})}>{layout.showEma ? "On" : "Off"}</div>
        </div>
      </div>
    </div>
  );
}

// Modern on/off switch — distinct accent glow when active, smooth knob
// transition. Use for binary view options (e.g. Charts on/off).
function Switch({on, onChange, label, title}){
  return (
    <div className={"switch-wrap "+(on?"on":"")} title={title||""}
         role="switch" aria-checked={on} tabIndex={0}
         onClick={()=>onChange(!on)}
         onKeyDown={e=>{ if(e.key===" "||e.key==="Enter"){ e.preventDefault(); onChange(!on); } }}>
      {label && <span className="switch-label">{label}</span>}
      <span className="switch">
        <span className="switch-knob"/>
      </span>
      <span className="switch-state">{on ? "On" : "Off"}</span>
    </div>
  );
}

// Finviz-inspired chart card: ticker header (price + 1D change + class badge),
// the configured timeframe charts side by side, and the EMA readout below.
function StockChartCard({stock, layout, action}){
  const intervals = layoutIntervals(layout);
  const height = CHART_SIZE_PX[layout.size] || 360;
  const chg = stock.chg_1d;
  return (
    <div className="stock-chart-card">
      <div className="stock-chart-head">
        {action}
        <span className="mono stock-chart-ticker">{stock.stock_ticker || stock.ticker}</span>
        {stock.price!=null && <span className="mono stock-chart-price">${stock.price.toFixed(2)}</span>}
        {chg!=null && <span className={"mono "+pctClass(chg)}>{fmtPct(chg)}</span>}
        <span className="stock-chart-spacer"/>
        {stock.classification==="leader" && <span className="tag-leader">Leader</span>}
        {stock.classification==="laggard" && <span className="tag-laggard">Laggard</span>}
        {stock.sector_name && <span className="hint">{stock.sector_name}</span>}
      </div>
      <div className="stock-chart-grid" data-cols={intervals.length} style={{gridTemplateColumns:"repeat("+intervals.length+",1fr)"}}>
        {intervals.map(iv=>(
          <div key={iv} className="row-chart-cell">
            <div className="row-chart-title mono">{iv==="D"?"Daily":iv==="W"?"Weekly":iv==="M"?"Monthly":iv+"m"}</div>
            <TVChart symbol={stock.stock_ticker || stock.ticker} interval={iv} height={height}/>
          </div>
        ))}
      </div>
      {layout.showEma!==false && <EmaStrip emas={stock} price={stock.price}/>}
    </div>
  );
}

// Chart cards stack vertically — one stock per row, full width so every
// timeframe chart gets the maximum space on the monitor.
function StockChartsGrid({stocks, layout, renderAction}){
  return (
    <div className="stock-charts-grid" style={{gridTemplateColumns:"1fr"}}>
      {stocks.map(s=> <StockChartCard key={s.stock_ticker || s.ticker} stock={s} layout={layout} action={renderAction ? renderAction(s) : null}/>)}
    </div>
  );
}

// Horizontal bar chart ranking all sectors by composite score, colored by state.
function SectorScoreBars({sectors, onSelectSector}) {
  if(!sectors || sectors.length===0) return <div className="empty">No data</div>;
  const rows = [...sectors].sort((a,b)=> (snapOf(b).score||0) - (snapOf(a).score||0));
  const width=640, rowH=19, padL=60, padR=40;
  const h = rows.length*rowH+10;
  const xFor = v=> padL + (Math.max(0, Math.min(100, v))/100)*(width-padL-padR);
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+h}>
      {[0,25,50,75,100].map(g=>(
        <g key={g}>
          <line x1={xFor(g)} x2={xFor(g)} y1={0} y2={h-12} stroke="#1c2027" strokeWidth="1"/>
          <text x={xFor(g)} y={h-1} fontSize="10" fill="var(--text-faint)" textAnchor="middle" fontFamily="var(--mono)">{g}</text>
        </g>
      ))}
      {rows.map((s,i)=>{
        const sn = snapOf(s);
        const sc = sn.score||0;
        const y = i*rowH+4;
        const w = Math.max(2, xFor(sc)-padL);
        return (
          <g key={s.id} className="svg-row" onClick={()=>onSelectSector && onSelectSector(s.id)}>
            <text x={padL-8} y={y+11} fontSize="12" fill="var(--text-dim)" textAnchor="end">{s.ticker}</text>
            <rect className="bar-grow" style={{transformOrigin:"left center", animationDelay:(i*35)+"ms"}}
              x={padL} y={y} width={w} height={rowH-10} fill={stateColor(sn.state)} opacity="0.85" rx="2"/>
            <text x={padL+w+6} y={y+11} fontSize="11" fill="var(--text-faint)" fontFamily="var(--mono)">{sc.toFixed(0)}</text>
          </g>
        );
      })}
    </svg>
  );
}

// Grouped diverging bars: 1W / 1M / 3M returns per sector around a zero line.
function PerfCompareBars({sectors, onSelectSector, compact=false}) {
  const [containerRef, containerWidth] = useContainerWidth();
  if(!sectors || sectors.length===0) return <div className="empty">No data</div>;
  const narrow = containerWidth!==null && containerWidth<520;
  const tight = compact && !narrow;
  const periods = [["chg_1w","var(--accent)"],["chg_1m","var(--purple)"],["chg_3m","var(--amber)"]];
  const rows = [...sectors].sort((a,b)=> (snapOf(b).chg_1m||0) - (snapOf(a).chg_1m||0));
  const maxAbs = Math.max(...sectors.flatMap(s=> periods.map(p=> Math.abs(snapOf(s)[p[0]]||0))), 1);
  const width=640, rowH=narrow?28:tight?17:24, padL=60, padR=12, barH=tight?3.4:5.5, gap=tight?1:1.5;
  const labelSize = tight?10.5:12;
  const h = rows.length*rowH+10;
  const zeroX = padL + (width-padL-padR)/2;
  const half = (width-padL-padR)/2;
  return (
    <div ref={containerRef}>
      {narrow && <div className="chart-scroll-note">Scroll horizontally for readable sector labels · select a row to drill down</div>}
      <div className="responsive-chart-scroll">
        <svg width="100%" viewBox={"0 0 "+width+" "+h} style={{maxWidth:compact?"none":700, display:"block", width:narrow?width:"100%", minWidth:narrow?width:0}}>
          <line x1={zeroX} x2={zeroX} y1={0} y2={h} stroke="#2a303a"/>
          {rows.map((s,i)=>{
            const sn = snapOf(s);
            const top = i*rowH+(tight?4:6);
            return (
              <g key={s.id} className="svg-row" role={onSelectSector?"button":undefined} tabIndex={onSelectSector?0:undefined}
                onClick={()=>onSelectSector && onSelectSector(s.id)}
                onKeyDown={e=>{if(onSelectSector&&(e.key==="Enter"||e.key===" ")){e.preventDefault();onSelectSector(s.id);}}}>
                <title>{s.ticker+" · 1W "+fmtPct(sn.chg_1w)+" · 1M "+fmtPct(sn.chg_1m)+" · 3M "+fmtPct(sn.chg_3m)}</title>
                <text x={padL-8} y={top+9} fontSize={labelSize} fill="var(--text-dim)" textAnchor="end">{s.ticker}</text>
                {periods.map((p,j)=>{
                  const v = sn[p[0]]||0;
                  const bw = Math.max(1.5, (Math.abs(v)/maxAbs)*half);
                  const x = v>=0 ? zeroX : zeroX-bw;
                  return <rect key={p[0]} className="bar-grow"
                    style={{transformOrigin:(v>=0?"left":"right")+" center", animationDelay:(i*30+j*50)+"ms"}}
                    x={x} y={top+j*(barH+gap)} width={bw} height={barH} fill={p[1]} opacity="0.9" rx="1.5">
                    <title>{s.ticker+" "+["1W","1M","3M"][j]+": "+fmtPct(v)}</title>
                  </rect>;
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// Grouped bars: % of constituents above the 20 / 50 / 200 MA per sector.
function BreadthCompareBars({sectors, onSelectSector, compact=false}) {
  const [containerRef, containerWidth] = useContainerWidth();
  if(!sectors || sectors.length===0) return <div className="empty">No data</div>;
  const narrow = containerWidth!==null && containerWidth<520;
  const tight = compact && !narrow;
  const periods = [["breadth_20","var(--green)"],["breadth_50","var(--accent)"],["breadth_200","var(--purple)"]];
  const valOf = (s,k)=>{ const cmd = s.command||{}; const v = cmd[k]; return v===null||v===undefined ? (k==="breadth_50" ? (snapOf(s).breadth_pct_above_50ma||0) : 0) : v; };
  const rows = [...sectors].sort((a,b)=> valOf(b,"breadth_50") - valOf(a,"breadth_50"));
  const width=640, rowH=narrow?28:tight?17:24, padL=60, padR=12, barH=tight?3.4:5.5, gap=tight?1:1.5;
  const labelSize = tight?10.5:12;
  const h = rows.length*rowH+10;
  const xFor = v=> padL + (Math.max(0, Math.min(100, v))/100)*(width-padL-padR);
  return (
    <div ref={containerRef}>
      {narrow && <div className="chart-scroll-note">Scroll horizontally for readable sector labels · select a row to drill down</div>}
      <div className="responsive-chart-scroll">
        <svg width="100%" viewBox={"0 0 "+width+" "+h} style={{maxWidth:compact?"none":700, display:"block", width:narrow?width:"100%", minWidth:narrow?width:0}}>
          {[0,25,50,75,100].map(g=>(
            <line key={g} x1={xFor(g)} x2={xFor(g)} y1={0} y2={h} stroke="#1c2027" strokeWidth="1"/>
          ))}
          {rows.map((s,i)=>{
            const top = i*rowH+(tight?4:6);
            return (
              <g key={s.id} className="svg-row" role={onSelectSector?"button":undefined} tabIndex={onSelectSector?0:undefined}
                onClick={()=>onSelectSector && onSelectSector(s.id)}
                onKeyDown={e=>{if(onSelectSector&&(e.key==="Enter"||e.key===" ")){e.preventDefault();onSelectSector(s.id);}}}>
                <title>{s.ticker+" · above 20/50/200 MA: "+periods.map(p=>valOf(s,p[0]).toFixed(0)+"%").join(" / ")}</title>
                <text x={padL-8} y={top+9} fontSize={labelSize} fill="var(--text-dim)" textAnchor="end">{s.ticker}</text>
                {periods.map((p,j)=>{
                  const v = valOf(s, p[0]);
                  const w = Math.max(1.5, xFor(v)-padL);
                  return <rect key={p[0]} className="bar-grow"
                    style={{transformOrigin:"left center", animationDelay:(i*30+j*50)+"ms"}}
                    x={padL} y={top+j*(barH+gap)} width={w} height={barH} fill={p[1]} opacity="0.9" rx="1.5">
                    <title>{s.ticker+" "+[">20MA",">50MA",">200MA"][j]+": "+v.toFixed(0)+"%"}</title>
                  </rect>;
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function Waterfall({steps, width=560, height=280, pad=36}) {
  if(!steps || steps.length===0) return <div className="empty">No data</div>;
  let cum = 0;
  const bars = steps.map(s=>{ const b={label:s.label, start:cum, end:cum+s.value, color:s.color}; cum+=s.value; return b; });
  bars.push({label:"Score", start:0, end:cum, color:"var(--text)", total:true});
  const maxV = Math.max(...bars.map(b=>Math.max(b.start,b.end)), 1);
  const n = bars.length;
  const slot = (width-pad*2)/n;
  const yFor = v=> height-pad - (v/maxV)*(height-pad*2);
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+height}>
      <line x1={pad} x2={width-pad} y1={yFor(0)} y2={yFor(0)} stroke="#2a303a"/>
      {bars.map((b,i)=>{
        const x = pad + i*slot + slot*0.18;
        const w = slot*0.64;
        const y0 = yFor(Math.max(b.start,b.end)), y1 = yFor(Math.min(b.start,b.end));
        return (
          <g key={b.label}>
            <rect className="nh-bar" style={{animationDelay:(i*70)+"ms"}} x={x} y={y0} width={w} height={Math.max(2,y1-y0)} fill={b.color} opacity={b.total?0.9:0.75} rx="2"/>
            {i<n-1 && <line x1={x+w} x2={x+slot} y1={yFor(b.end)} y2={yFor(b.end)} stroke="#2a303a" strokeDasharray="3,2"/>}
            <text x={x+w/2} y={height-pad+13} fontSize="9" fill="var(--text-faint)" textAnchor="middle">{b.label}</text>
            <text x={x+w/2} y={y0-5} fontSize="9.5" fill="var(--text-dim)" textAnchor="middle" fontFamily="var(--mono)">{b.total? b.end.toFixed(0) : "+"+(b.end-b.start).toFixed(1)}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Treemap({items, width=560, height=330}) {
  if(!items || items.length===0) return <div className="empty">No data</div>;
  const sorted = items.filter(s=>s.value>0).sort((a,b)=>b.value-a.value);
  if(sorted.length===0) return <div className="empty">No data</div>;
  const total = sorted.reduce((a,s)=>a+s.value,0)||1;
  const rects = [];
  (function layout(list, x, y, w, h){
    if(list.length===0) return;
    if(list.length===1){ rects.push({...list[0], x, y, w, h}); return; }
    let acc=0, i=0;
    const sum = list.reduce((a,s)=>a+s.value,0);
    while(i<list.length-1 && acc+list[i].value <= sum/2){ acc+=list[i].value; i++; }
    acc+=list[i].value; i++;
    const g1 = list.slice(0,i), g2 = list.slice(i);
    if(g2.length===0){ g2.push(g1.pop()); }
    const f = acc/sum;
    if(w>=h){ layout(g1,x,y,w*f,h); layout(g2,x+w*f,y,w*(1-f),h); }
    else { layout(g1,x,y,w,h*f); layout(g2,x,y+h*f,w,h*(1-f)); }
  })(sorted, 0, 0, width, height);
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+height}>
      {rects.map((r,i)=>(
        <g key={i}>
          <rect x={r.x+1} y={r.y+1} width={Math.max(0,r.w-2)} height={Math.max(0,r.h-2)} fill={r.color} opacity="0.22" stroke={r.color} strokeWidth="1" rx="3"
            style={r.onSelect?{cursor:"pointer"}:undefined} onClick={r.onSelect}/>
          {r.w>44 && r.h>24 && <text x={r.x+r.w/2} y={r.y+r.h/2-2} fontSize="11" fontWeight="700" fill={r.color} textAnchor="middle" fontFamily="var(--mono)" style={r.onSelect?{pointerEvents:"none"}:undefined}>{r.label}</text>}
          {r.w>44 && r.h>38 && <text x={r.x+r.w/2} y={r.y+r.h/2+12} fontSize="9.5" fill="var(--text-dim)" textAnchor="middle" fontFamily="var(--mono)" style={r.onSelect?{pointerEvents:"none"}:undefined}>{r.sub!==undefined ? r.sub : r.value.toFixed(0)}</text>}
          <title>{r.label}{r.title?": "+r.title:": "+r.value.toFixed(1)}</title>
        </g>
      ))}
    </svg>
  );
}

function Dumbbell({rows, width=560, rowH=26, padL=130, padR=56, fmt}) {
  if(!rows || rows.length===0) return <div className="empty">No data</div>;
  const all = rows.flatMap(r=>[r.v1,r.v2]);
  const minV = Math.min(...all, 0), maxV = Math.max(...all, 0.0001);
  const h = rows.length*rowH + 8;
  const xFor = v=> padL + ((v-minV)/((maxV-minV)||1))*(width-padL-padR);
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+h}>
      <line x1={xFor(0)} x2={xFor(0)} y1={0} y2={h} stroke="#2a303a"/>
      {rows.map((r,i)=>{
        const y = i*rowH + rowH/2 + 2;
        return (
          <g key={r.label}>
            <text x={padL-8} y={y+3} fontSize="10.5" fill="var(--text-dim)" textAnchor="end">{r.label}</text>
            <line x1={xFor(r.v1)} x2={xFor(r.v2)} y1={y} y2={y} stroke={r.color} strokeWidth="1.5" opacity="0.6"/>
            <circle cx={xFor(r.v1)} cy={y} r="4" fill="var(--bg)" stroke={r.color} strokeWidth="2"/>
            <circle cx={xFor(r.v2)} cy={y} r="4.5" fill={r.color}/>
            <text x={Math.max(xFor(r.v1),xFor(r.v2))+9} y={y+3} fontSize="9.5" fill="var(--text-faint)" fontFamily="var(--mono)">{fmt?fmt(r.v2):r.v2}</text>
          </g>
        );
      })}
    </svg>
  );
}

function SlopeChart({rows, width=560, height=380, padL=64, padR=64}) {
  if(!rows || rows.length===0) return <div className="empty">No data</div>;
  const all = rows.flatMap(r=>[r.from,r.to]);
  const minV = Math.min(...all), maxV = Math.max(...all);
  const pad = (maxV-minV)*0.08||1;
  const yFor = v=> height-24 - ((v-(minV-pad))/((maxV-minV)+2*pad))*(height-48);
  const x1 = padL, x2 = width-padR;
  return (
    <svg width="100%" viewBox={"0 0 "+width+" "+height}>
      <text x={x1} y={12} fontSize="9.5" fill="var(--text-faint)" textAnchor="middle">10 days ago</text>
      <text x={x2} y={12} fontSize="9.5" fill="var(--text-faint)" textAnchor="middle">Latest</text>
      {rows.map((r,i)=>{
        const rising = r.to>=r.from;
        return (
          <g key={r.label}>
            <line x1={x1} x2={x2} y1={yFor(r.from)} y2={yFor(r.to)} stroke={r.color} strokeWidth="1.6" opacity="0.75"/>
            <circle cx={x1} cy={yFor(r.from)} r="3" fill={r.color}/>
            <circle cx={x2} cy={yFor(r.to)} r="3.5" fill={r.color}/>
            <text x={x1-7} y={yFor(r.from)+3} fontSize="9.5" fill={r.color} textAnchor="end" fontFamily="var(--mono)">{r.label} {r.from.toFixed(0)}</text>
            <text x={x2+7} y={yFor(r.to)+3} fontSize="9.5" fill={r.color} fontFamily="var(--mono)">{r.to.toFixed(0)} {r.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

function MiniPrice({values, width=160, height=54, maPeriod=20}) {
  if(!values || values.length<2) return <svg width={width} height={height}></svg>;
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max-min)||1;
  const xFor = i=> (i/(values.length-1))*width;
  const yFor = v=> height-3 - ((v-min)/span)*(height-6);
  const pts = values.map((v,i)=> xFor(i)+","+yFor(v)).join(" ");
  const maPts = values.map((v,i)=>{
    if(i<maPeriod-1) return null;
    const m = avg(values.slice(i-maPeriod+1, i+1));
    return xFor(i)+","+yFor(m);
  }).filter(Boolean).join(" ");
  const up = values[values.length-1] >= values[0];
  return (
    <svg width={width} height={height}>
      <polyline className="draw" pathLength="1" points={pts} fill="none" stroke={up?"var(--green)":"var(--red)"} strokeWidth="1.5"/>
      {maPts && <polyline points={maPts} fill="none" stroke="var(--amber)" strokeWidth="1.2" strokeDasharray="3,2" opacity="0.9"/>}
    </svg>
  );
}

function SectorPerformanceTable({sectors, onClick, title}) {
  const sort = useSortable((a,b)=> (snapOf(b).score||0) - (snapOf(a).score||0));
  const keyFns = {
    ticker: s=> s.ticker,
    state: s=> snapOf(s).state||"",
    score: s=> snapOf(s).score||0,
    chg_1d: s=> snapOf(s).chg_1d||0,
    chg_1w: s=> snapOf(s).chg_1w||0,
    chg_1m: s=> snapOf(s).chg_1m||0,
    chg_3m: s=> snapOf(s).chg_3m||0,
    breadth: s=> snapOf(s).breadth_pct_above_50ma||0,
    rs: s=> snapOf(s).avg_rs_rating||0,
    vs_spy: s=> snapOf(s).rs_vs_spy_1m||0,
    nh: s=> snapOf(s).pct_new_highs||0,
    vol: s=> snapOf(s).avg_volume_ratio||0,
    from_hi: s=> snapOf(s).etf_pct_from_52w_high??-999,
    ema: s=> (snapOf(s).ema10_above_20?2:0)+(snapOf(s).above_50ema?1:0),
    rs_delta: s=> s.rs_trend||0,
    score_delta: s=> s.score_delta_5d||0,
    rank_delta: s=> s.rank_delta||0,
    style: s=> s.style==="offensive"?1:0,
  };
  const sorted = sort.apply(sectors, keyFns);
  return (
    <div className="panel">
      <div className="panel-title">
        <span>{title || "Sector Performance Table"}</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <SortTh label="Sector" k="ticker" sort={sort}/>
              <SortTh label="State" k="state" sort={sort}/>
              <SortTh label="Score" k="score" sort={sort}/>
              <SortTh label="1D" k="chg_1d" sort={sort}/>
              <SortTh label="1W" k="chg_1w" sort={sort}/>
              <SortTh label="1M" k="chg_1m" sort={sort}/>
              <SortTh label="3M" k="chg_3m" sort={sort}/>
              <SortTh label="Breadth" k="breadth" sort={sort}/>
              <SortTh label="RS" k="rs" sort={sort}/>
              <SortTh label="vs SPY" k="vs_spy" sort={sort}/>
              <SortTh label="New Highs" k="nh" sort={sort}/>
              <SortTh label="Vol x" k="vol" sort={sort}/>
              <SortTh label="% fr Hi" k="from_hi" sort={sort} title="Sector ETF distance from 52-week high"/>
              <SortTh label="EMA" k="ema" sort={sort} title="10EMA vs 20EMA, price vs 50EMA"/>
              <SortTh label="RS Δ" k="rs_delta" sort={sort} title="RS rating change, 5 days"/>
              <SortTh label="Score Δ" k="score_delta" sort={sort} title="Score change, 5 days"/>
              <SortTh label="Rank Δ" k="rank_delta" sort={sort} title="Rank change, 5 days (positive = moved up)"/>
              <SortTh label="Style" k="style" sort={sort}/>
              <th>Tags</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(s=>{
              const snap = snapOf(s);
              return (
                <tr key={s.id} onClick={()=>onClick(s.id)} className="hover-row">
                  <td>
                    <div className="flex gap-2 ai-center">
                      <span className="dot" style={{background:secColor(s)}}></span>
                      <span className="mono">{s.ticker}</span>
                      <span className="text-dim">{s.name}</span>
                    </div>
                  </td>
                  <td><span className={"state-badge "+stateClass(snap.state)}>{stateLabel(snap.state)}</span></td>
                  <td><div className="score-cell"><span>{(snap.score||0).toFixed(0)}</span><ScoreBar value={snap.score||0}/></div></td>
                  <td className={pctClass(snap.chg_1d)}>{fmtPct(snap.chg_1d)}</td>
                  <td className={pctClass(snap.chg_1w)}>{fmtPct(snap.chg_1w)}</td>
                  <td className={pctClass(snap.chg_1m)}>{fmtPct(snap.chg_1m)}</td>
                  <td className={pctClass(snap.chg_3m)}>{fmtPct(snap.chg_3m)}</td>
                  <td>{(snap.breadth_pct_above_50ma||0).toFixed(0)}%</td>
                  <td>{(snap.avg_rs_rating||0).toFixed(0)}</td>
                  <td className={pctClass(snap.rs_vs_spy_1m)}>{fmtPct(snap.rs_vs_spy_1m)}</td>
                  <td>{(snap.pct_new_highs||0).toFixed(0)}%</td>
                  <td>{(snap.avg_volume_ratio||0).toFixed(2)}x</td>
                  <td className="neg">{snap.etf_pct_from_52w_high!==null&&snap.etf_pct_from_52w_high!==undefined ? snap.etf_pct_from_52w_high.toFixed(1)+"%" : "—"}</td>
                  <EmaCell sn={snap}/>
                  <td className={pctClass(s.rs_trend||0)}>{s.rs_trend>0?"+":""}{(s.rs_trend||0).toFixed(1)}</td>
                  <td className={pctClass(s.score_delta_5d||0)}>{s.score_delta_5d>0?"+":""}{(s.score_delta_5d||0).toFixed(1)}</td>
                  <td className={pctClass(s.rank_delta||0)}>{s.rank_delta>0?"+"+s.rank_delta:(s.rank_delta||0)}</td>
                  <td>{s.style==="defensive" ? <span className="tag tag-purple">Def</span> : <span className="tag tag-blue">Off</span>}</td>
                  <td><Tags sector={s}/></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
function Sidebar({open, setOpen, current, onNavigate}) {
  const items = [
    {id:"dashboard", label:"Markets", icon:"dashboard"},
    {id:"sectors", label:"All Sectors", icon:"sectors"},
    {id:"industries", label:"Industries", icon:"candles"},
    {id:"etf", label:"ETFs", icon:"etf"},
    {id:"watchlist", label:"Watchlist", icon:"check"},
    {id:"ep", label:"EPs", icon:"zap"},
    {id:"screener", label:"Screener", icon:"sectors"},
  ];
  return (
    <aside className={"sidebar "+(open?"open":"collapsed")} aria-label="Primary navigation">
      <div className="sidebar-header"
        onClick={!open ? ()=>setOpen(true) : undefined}
        style={!open ? {cursor:"pointer"} : undefined}
        title={!open ? "Expand sidebar" : "Rotational Capital"}>
        <div className="brand-mark"><BrandLogo/><span className="brand-wordmark">Rotational Capital</span></div>
        <button className="sidebar-toggle" onClick={(e)=>{ e.stopPropagation(); setOpen(!open); }} title={open?"Collapse sidebar":"Expand sidebar"} aria-label={open?"Collapse sidebar":"Expand sidebar"}>
          {open ? <Icon.menu/> : <Icon.expand/>}
        </button>
      </div>
      <nav className="sidebar-nav">
        {items.map(item=>{
          const I = Icon[item.icon];
          return (
            <div key={item.id} className={"sidebar-item "+(current===item.id?"active":"")}
              role="link" tabIndex={0} aria-current={current===item.id?"page":undefined}
              onClick={()=>onNavigate(item.id)}
              onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();onNavigate(item.id);}}}>
              <div className="sidebar-icon"><I/></div>
              {open && <span className="sidebar-label">{item.label}</span>}
              {!open && <div className="sidebar-tooltip">{item.label}</div>}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// TopBar
// ---------------------------------------------------------------------------
function TopBar({mode, lastSynced, market, marketHistory, onSync, onRefresh, syncing, strategy, onStrategy, theme, onToggleTheme}) {
  const syncLabel = mode==='live' && lastSynced
    ? "Synced "+new Date(lastSynced).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})
    : "Demo data";
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="data-mode" title={lastSynced ? "Last live sync: "+new Date(lastSynced).toLocaleString() : "Using synthetic demo data"}>
          <span className={"data-mode-dot "+(mode==='live'?'live':'demo')}></span>
          <span>{mode==='live' ? "LIVE DATA" : "DEMO DATA"}</span>
        </div>
        {mode!=='live' && (
          <span className="demo-badge" onClick={onSync} title="Synthetic data — click to sync live market data">
            <Icon.warn color="var(--amber)"/> DEMO DATA — click Sync for live market data
          </span>
        )}
        <span className="sync-time">{syncLabel}</span>
        {market && (
          <div className="spy-chip" title="Benchmark trend">
            <span className="mono fw-700">{market.ticker}</span>
            <MiniSpark values={marketHistory} width={72} height={20} positive={(marketHistory||[]).length>1 ? marketHistory[marketHistory.length-1]>=marketHistory[0] : undefined}/>
            <span className={"mono "+pctClass(market.chg_1d)}>{fmtPct1(market.chg_1d)}</span>
          </div>
        )}
      </div>
      <div className="topbar-right">
        <div className="strategy-switch" title="Strategy dashboard — same scanner shell, different ranking engine (Markets stays universal)">
          {STRATEGIES.map(s=>(
            <button key={s.id}
              className={"strategy-btn "+(strategy===s.id?"active":"")}
              onClick={()=>onStrategy(s.id)}>{s.label}</button>
          ))}
        </div>
        <button className="theme-toggle" onClick={onToggleTheme}
          aria-label={theme==="dark"?"Switch to light theme":"Switch to dark theme"}
          title={theme==="dark"?"Switch to light theme":"Switch to dark theme"}
          aria-pressed={theme==="light"}>
          {theme==="dark" ? <Icon.sun/> : <Icon.moon/>}
        </button>
        <button className="btn" onClick={onRefresh} title="Reset Demo"><Icon.refresh/><span className="btn-label">Reset Demo</span></button>
        <button className="btn primary" onClick={onSync} disabled={syncing} title={syncing?"Syncing live data":"Sync Live Data"}>
          <Icon.cloud/><span className="btn-label">{syncing ? "Syncing…" : "Sync Live Data"}</span>
        </button>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Dashboard components
// ---------------------------------------------------------------------------
function MarketSummary({market}) {
  if(!market) return null;
  const rets = market.returns || {};
  return (
    <div className="panel market-summary">
      <div className="market-summary-grid">
        <div className="metric" title="Benchmark index tracked by the whole dashboard">
          <div className="stat-label">Benchmark</div>
          <div className="flex gap-2 ai-baseline">
            <span className="stat-xl">{market.ticker}</span>
            <span className="stat-lg">{fmtPrice(market.price)}</span>
          </div>
        </div>
        <div className="metric" title="1-day return">
          <div className="stat-label">1D</div>
          <div className={"stat-value "+pctClass(market.chg_1d)}>{fmtPct(market.chg_1d)}</div>
        </div>
        <div className="metric" title="1-week (5 trading day) return">
          <div className="stat-label">1W</div>
          <div className={"stat-value "+pctClass(market.chg_1w)}>{fmtPct(market.chg_1w)}</div>
        </div>
        <div className="metric" title="1-month (21 trading day) return">
          <div className="stat-label">1M</div>
          <div className={"stat-value "+pctClass(market.chg_1m)}>{fmtPct(market.chg_1m)}</div>
        </div>
        <div className="metric" title="3-month (63 trading day) return">
          <div className="stat-label">3M</div>
          <div className={"stat-value "+(rets["3M"]!=null?pctClass(rets["3M"]):"")}>{fmtPct(rets["3M"])}</div>
        </div>
        <div className="metric" title="Year-to-date return">
          <div className="stat-label">YTD</div>
          <div className={"stat-value "+(rets["YTD"]!=null?pctClass(rets["YTD"]):"")}>{fmtPct(rets["YTD"])}</div>
        </div>
        <div className="metric" title="1-year (252 trading day) return">
          <div className="stat-label">1Y</div>
          <div className={"stat-value "+(rets["1Y"]!=null?pctClass(rets["1Y"]):"")}>{fmtPct(rets["1Y"])}</div>
        </div>
        <div className="metric" title="Short-term trend: 10 EMA above (uptrend) or below (downtrend) the 20 EMA">
          <div className="stat-label">Trend (10/20 EMA)</div>
          <div className="stat-value">{market.trend==null ? "—" : market.trend==="uptrend" ? <span className="pos"><Icon.up/> Uptrend</span> : <span className="neg"><Icon.down/> Downtrend</span>}</div>
        </div>
        <div className="metric" title="Overall trend: price above or below the 50 EMA">
          <div className="stat-label">Overall (50 EMA)</div>
          <div className="stat-value">{market.overall_trend==null ? "—" : market.overall_trend==="above_50ema" ? <span className="pos"><Icon.up/> Above 50EMA</span> : <span className="neg"><Icon.down/> Below 50EMA</span>}</div>
        </div>
      </div>
    </div>
  );
}

function MoversColumn({title, sectors, onClick, icon}) {
  const I = Icon[icon] || Icon.arrowTrendUp;
  return (
    <div className="movers-column">
      <div className="movers-header">
        <div className="flex gap-2 ai-center"><I/> {title}</div>
        <span className="text-faint">{sectors.length}</span>
      </div>
      <div className="movers-list">
        {sectors.map(s=>{
          const snap = s.latest_snapshot || {};
          const history = s.history || [];
          const spark = history.slice(-20).map(h=>h.score);
          const positive = snap.chg_1m >= 0;
          return (
            <div key={s.id} className="mover-card" onClick={()=>onClick(s.id)}>
              <div className="mover-main">
                <div className="mover-title">
                  <span className="dot" style={{background:secColor(s)}}></span>
                  <span className="mover-name">{s.name}</span>
                  <span className="text-faint mono">{s.ticker}</span>
                </div>
                <div className="mover-sub">{s.sub}</div>
              </div>
              <div className="mover-chart"><LineSpark values={spark} color={s.color}/></div>
              <div className="mover-stats">
                <div className="mover-score">{snap.score!==undefined ? snap.score.toFixed(0) : "—"}</div>
                <div className={"mover-chg "+pctClass(snap.chg_1m)}>{fmtPct(snap.chg_1m)}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SummaryCards({sectors, onSelectSector}) {
  const ls = sectorScores(sectors);
  const withLs = sectors.map((s,i)=>({s, ls: ls[i]}));
  const cards = [
    {label:"Best Overall", pick: maxBy(withLs, x=>x.ls)},
    {label:"Best Offensive", pick: maxBy(withLs.filter(x=>x.s.style==="offensive"), x=>x.ls)},
    {label:"Best Defensive", pick: maxBy(withLs.filter(x=>x.s.style==="defensive"), x=>x.ls)},
    {label:"Fastest Improving", pick: maxBy(withLs, x=>(x.s.score_delta_5d||0)*1000+(x.s.rs_trend||0))},
    {label:"Weakest", pick: minBy(withLs, x=>x.ls)},
  ];
  return (
    <div className="summary-cards">
      {cards.map(c=>{
        if(!c.pick) return null;
        const s = c.pick.s;
        return (
          <div key={c.label} className="sum-card" style={{borderLeftColor:s.color}} onClick={()=>onSelectSector(s.id)}>
            <div className="stat-label">{c.label}</div>
            <div className="sum-card-name"><span className="dot" style={{background:secColor(s)}}></span><span className="mono fw-700">{s.ticker}</span><span className="text-dim">{s.name}</span></div>
            <div className="sum-card-reason">{sectorReason(s)}</div>
          </div>
        );
      })}
    </div>
  );
}

function StrongestBanner({sectors, onSelectSector}) {
  const ls = sectorScores(sectors);
  const top = maxBy(sectors.map((s,i)=>({s, ls:ls[i]})), x=>x.ls);
  if(!top) return null;
  const s = top.s, sn = snapOf(s);
  return (
    <div className="panel strongest-banner" style={{borderLeftColor:s.color}} onClick={()=>onSelectSector(s.id)}>
      <div className="strongest-main">
        <div className="stat-label">Strongest Sector — Score {top.ls.toFixed(0)}</div>
        <div className="flex gap-3 ai-baseline">
          <span className="dot-lg" style={{background:secColor(s)}}></span>
          <span className="strongest-name">{s.name}</span>
          <span className="mono text-faint">{s.ticker}</span>
        </div>
        <div className="sum-card-reason">{sectorReason(s)}</div>
      </div>
      <div className="strongest-stats">
        <div className="metric"><div className="stat-label">Score</div><div className="stat-value">{(sn.score||0).toFixed(0)}</div></div>
        <div className="metric"><div className="stat-label">vs SPY</div><div className={"stat-value "+pctClass(sn.rs_vs_spy_1m)}>{fmtPct1(sn.rs_vs_spy_1m)}</div></div>
        <div className="metric"><div className="stat-label">Breadth</div><div className="stat-value">{(sn.breadth_pct_above_50ma||0).toFixed(0)}%</div></div>
        <div className="metric"><div className="stat-label">% fr Hi</div><div className="stat-value neg">{sn.etf_pct_from_52w_high!==null&&sn.etf_pct_from_52w_high!==undefined ? sn.etf_pct_from_52w_high.toFixed(1)+"%" : "—"}</div></div>
        <div className="metric"><div className="stat-label">EMA 10/20</div><div className="stat-value">{sn.ema10_above_20 ? <span className="pos">Aligned</span> : <span className="neg">Crossed</span>}</div></div>
        <Tags sector={s}/>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Industries — TradingView industry classification, ranked by the two-stage
// 100-point Leadership Score (see engine.industry_leaderboard_scores:
// eligibility status gate + percentile-ranked components across industries)
// ---------------------------------------------------------------------------
const INDUSTRY_SORT_KEYS = {
  industry: i=> i.industry,
  sector: i=> i.sector_name||"",
  score: i=> i.leadership_score??-1,
  opp: i=> i.opportunity_score??-1,
  rk5: i=> i.rank_chg_5d??-999,
  rk20: i=> i.rank_chg_20d??-999,
  count: i=> i.stock_count,
  chg_1w: i=> i.chg_1w??-999,
  chg_1m: i=> i.chg_1m??-999,
  chg_3m: i=> i.chg_3m??-999,
  chg_6m: i=> i.chg_6m??-999,
  b20: i=> i.breadth_20??-1,
  b50: i=> i.breadth_50??-1,
  nh: i=> i.pct_new_highs??-1,
  vol: i=> i.avg_volume_ratio??-1,
  vs_spy: i=> i.avg_rs_vs_spy_1m??-999,
  vold: i=> i.avg_volatility_d??-1,
  rating: i=> i.avg_recommend_all??-1,
  delta: i=> i.score_delta??-999,
  state: i=> i.state||"",
  status: i=> i.status||"",
};

function IndustryTable({industries, onSelectIndustry, title, hint, showSector}) {
  const sort = useSortable((a,b)=> (b.leadership_score??-1)-(a.leadership_score??-1));
  if(!industries || industries.length===0) return null;
  const sorted = sort.apply(industries, INDUSTRY_SORT_KEYS);
  const confClass = c=> c==="High"?"conf-hi":c==="Medium"?"conf-md":"conf-lo";
  return (
    <div className="panel">
      <div className="panel-title">
        <span>{title || "Industries"}</span>
        {hint && <span className="hint">{hint}</span>}
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <SortTh label="Industry" k="industry" sort={sort}/>
              {showSector && <SortTh label="Sector" k="sector" sort={sort}/>}
              <SortTh label="Score" k="score" sort={sort} title="Leadership Score (0-100): percentile-ranked sustained RS, recent momentum, breadth, trend, rotation, volume and opportunity components"/>
              <SortTh label="Opp" k="opp" sort={sort} title="Opportunity score (0-100): 100 = constructive pullback/consolidation near the 10/20EMA, lower = extended or breaking down"/>
              <SortTh label="Rk Δ5" k="rk5" sort={sort} title="Leadership rank change vs 5 snapshots ago (positive = improved)"/>
              <SortTh label="Rk Δ20" k="rk20" sort={sort} title="Leadership rank change vs 20 snapshots ago (positive = improved)"/>
              <SortTh label="Δ" k="delta" sort={sort} title="Change in leadership score vs the previous snapshot (needs two syncs)"/>
              <SortTh label="State" k="state" sort={sort} title="Leading / Emerging / Fading / Lagging / Recovering"/>
              <SortTh label="Status" k="status" sort={sort} title="Eligibility: Actionable / Emerging / Extended / Watchlist / Avoid"/>
              <th title="Confidence from constituent count and breadth coverage">Conf</th>
              <th>Why</th>
              <th title="Industry benchmark: a dedicated industry ETF, or an equal-weight custom index of the top members by market cap">Benchmark</th>
              <SortTh label="#" k="count" sort={sort} title="Stocks in the filtered universe"/>
              <SortTh label="1W" k="chg_1w" sort={sort}/>
              <SortTh label="1M" k="chg_1m" sort={sort}/>
              <SortTh label="3M" k="chg_3m" sort={sort}/>
              <SortTh label="6M" k="chg_6m" sort={sort}/>
              <SortTh label="&gt;20MA" k="b20" sort={sort} title="% of stocks above 20 SMA"/>
              <SortTh label="&gt;100EMA" k="b50" sort={sort} title="% of stocks above 100 EMA"/>
              <SortTh label="NH%" k="nh" sort={sort} title="% within 5% of 1M/3M high"/>
              <SortTh label="Vol x" k="vol" sort={sort}/>
              <SortTh label="vs SPY" k="vs_spy" sort={sort} title="Avg 1M relative strength vs SPY"/>
              <SortTh label="Vol.D" k="vold" sort={sort} title="Avg TradingView daily volatility"/>
              <SortTh label="Rating" k="rating" sort={sort} title="Avg TradingView analyst rating (0-1)"/>
            </tr>
          </thead>
          <tbody>
            {sorted.map(i=>(
              <tr key={i.industry}
                  onClick={(i.stock_count||0)>=3 ? ()=>onSelectIndustry(i.industry) : undefined}
                  className={(i.stock_count||0)>=3 ? "hover-row" : ""}
                  title={(i.stock_count||0)<3 ? "Fewer than 3 stocks — no industry page" : undefined}>
                <td className="fw-700">{i.industry}</td>
                {showSector && <td className="text-dim">{i.sector_name || "—"}</td>}
                <td>{i.leadership_score!=null ? i.leadership_score.toFixed(0) : "—"}</td>
                <td className="mono">{i.opportunity_score!=null ? i.opportunity_score.toFixed(0) : "—"}</td>
                <td className={"mono "+(i.rank_chg_5d==null?"text-faint":pctClass(i.rank_chg_5d))}>{i.rank_chg_5d==null?"—":(i.rank_chg_5d>0?"+":"")+i.rank_chg_5d}</td>
                <td className={"mono "+(i.rank_chg_20d==null?"text-faint":pctClass(i.rank_chg_20d))}>{i.rank_chg_20d==null?"—":(i.rank_chg_20d>0?"+":"")+i.rank_chg_20d}</td>
                <td className={"mono "+(i.score_delta==null?"text-faint":pctClass(i.score_delta))}>{i.score_delta==null?"—":(i.score_delta>=0?"+":"")+i.score_delta.toFixed(1)}</td>
                <td>{i.state ? <span className={"state-badge "+stateClass(String(i.state).toLowerCase())}>{stateLabel(String(i.state).toLowerCase())}</span> : "—"}</td>
                <td><StatusBadge status={i.status}/></td>
                <td className={confClass(i.confidence)}>{i.confidence || "—"}</td>
                <td><ReasonChips reasons={i.reasons}/></td>
                <td className="mono text-dim">{i.benchmark_etf || (i.benchmark_kind==="custom" ? "Custom" : "—")}</td>
                <td>{i.stock_count}</td>
                <td className={pctClass(i.chg_1w)}>{fmtPct(i.chg_1w)}</td>
                <td className={pctClass(i.chg_1m)}>{fmtPct(i.chg_1m)}</td>
                <td className={pctClass(i.chg_3m)}>{fmtPct(i.chg_3m)}</td>
                <td className={pctClass(i.chg_6m)}>{i.chg_6m==null?"—":fmtPct(i.chg_6m)}</td>
                <td><BarMeter value={i.breadth_20}/></td>
                <td><BarMeter value={i.breadth_50}/></td>
                <td>{(i.pct_new_highs||0).toFixed(0)}%</td>
                <td>{i.avg_volume_ratio==null?"—":i.avg_volume_ratio.toFixed(2)+"x"}</td>
                <td className={pctClass(i.avg_rs_vs_spy_1m)}>{fmtPct(i.avg_rs_vs_spy_1m)}</td>
                <td>{i.avg_volatility_d==null?"—":i.avg_volatility_d.toFixed(2)+"%"}</td>
                <td className={ratingClass(i.avg_recommend_all)}>{fmtRating(i.avg_recommend_all)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function industryLeadership(i){
  // Backend Leadership Score (two-stage 100-point system, >=3 stocks).
  // Fallback: 3M blend for industries too small to score.
  if(i.leadership_score!=null) return i.leadership_score;
  return (i.chg_3m??-999)*2 + (i.breadth_50||0)*0.5 + (i.pct_new_highs||0)*0.25;
}

// Industry Leadership panel — every industry with >= 3 stocks, ranked by the
// industry leadership score. Shared by All Sectors / Momentum /
// Playbook (not the Markets dashboard).
function IndustryLeadershipPanel({strategy, onSelectIndustry, limit, title, hint}) {
  const [industries] = useApi(apiUrl("/api/industries", strategy), [strategy]);
  if(!industries) return <div className="panel"><div className="loading">Loading industries…</div></div>;
  const scored = industries
    .filter(i=> i.leadership_score!=null && (i.stock_count||0)>=3)
    .sort((a,b)=> b.leadership_score - a.leadership_score);
  const shown = limit ? scored.slice(0, limit) : scored;
  if(!shown.length) return null;
  return (
    <div className="panel">
      <div className="panel-title">
        <span>{title || "Industry Leadership"}</span>
        <span className="hint">{hint || "Every industry with >=3 stocks · >25 stocks: 65% performance + 35% CCI · <=25 stocks: performance only (1M > 3M > 1W) · click to open the industry page"}</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Industry</th><th>Sector</th><th>Benchmark</th><th>Score</th>
              <th>Perf</th><th>CCI</th><th>Stocks</th>
              <th>1W</th><th>1M</th><th>3M</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(i=>(
              <tr key={i.industry} onClick={()=>onSelectIndustry(i.industry, i.sector_id)} className="hover-row">
                <td className="text-faint mono">{i.leadership_rank}</td>
                <td className="fw-700">{i.industry}</td>
                <td className="text-dim">{i.sector_name || "—"}</td>
                <td className="mono text-dim">{i.benchmark_etf || (i.benchmark_kind==="custom" ? "Custom" : "—")}</td>
                <td><div className="score-cell"><span>{i.leadership_score.toFixed(0)}</span><ScoreBar value={i.leadership_score}/></div></td>
                <td>{i.perf_component!=null ? i.perf_component.toFixed(0) : "—"}</td>
                <td>{i.cci_factor!=null ? i.cci_factor.toFixed(0) : "—"}</td>
                <td>{i.stock_count}</td>
                <td className={pctClass(i.chg_1w)}>{fmtPct1(i.chg_1w)}</td>
                <td className={pctClass(i.chg_1m)}>{fmtPct1(i.chg_1m)}</td>
                <td className={pctClass(i.chg_3m)}>{fmtPct1(i.chg_3m)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LeadingIndustryBanner({industries, onSelectIndustry}) {
  if(!industries || !industries.length) return null;
  const top = maxBy(industries, industryLeadership);
  if(!top) return null;
  return (
    <div className="panel strongest-banner" style={{borderLeftColor:"var(--accent)"}} onClick={()=>onSelectIndustry(top.industry)}>
      <div className="strongest-main">
        <div className="stat-label">Leading Industry</div>
        <div className="flex gap-3 ai-baseline">
          <span className="dot-lg" style={{background:"var(--accent)"}}></span>
          <span className="strongest-name">{top.industry}</span>
          <span className="mono text-faint">{top.stock_count} stocks</span>
        </div>
        <div className="sum-card-reason">{"3M "+fmtPct1(top.chg_3m)+" · "+(top.breadth_50||0).toFixed(0)+"% above 100EMA · "+(top.pct_new_highs||0).toFixed(0)+"% near 3M highs"}</div>
      </div>
      <div className="strongest-stats">
        <div className="metric"><div className="stat-label">3M</div><div className={"stat-value "+pctClass(top.chg_3m)}>{fmtPct(top.chg_3m)}</div></div>
        <div className="metric"><div className="stat-label">1M</div><div className={"stat-value "+pctClass(top.chg_1m)}>{fmtPct(top.chg_1m)}</div></div>
        <div className="metric"><div className="stat-label">Breadth</div><div className="stat-value">{(top.breadth_50||0).toFixed(0)}%</div></div>
        <div className="metric"><div className="stat-label">New Highs</div><div className="stat-value">{(top.pct_new_highs||0).toFixed(0)}%</div></div>
        <div className="metric"><div className="stat-label">Vol x</div><div className="stat-value">{top.avg_volume_ratio==null?"—":top.avg_volume_ratio.toFixed(2)+"x"}</div></div>
        <div className="metric"><div className="stat-label">Rating</div><div className={"stat-value "+ratingClass(top.avg_recommend_all)}>{fmtRating(top.avg_recommend_all)}</div></div>
      </div>
    </div>
  );
}

const IND_STOCK_SORT_KEYS = {
  ticker: s=> s.ticker,
  score: s=> s._score ?? -1,
  sector: s=> s.sector_name||"",
  price: s=> s.price,
  mcap: s=> s.market_cap_musd,
  chg_1d: s=> s.chg_1d,
  chg_1w: s=> s.chg_1w,
  chg_1m: s=> s.chg_1m,
  chg_3m: s=> s.chg_3m,
  chg_6m: s=> s.chg_6m,
  rs: s=> s.rs_rating,
  from_hi: s=> s.pct_from_52w_high??-999,
  vol: s=> s.volume_ratio,
  vold: s=> s.volatility_d??-1,
  atr: s=> s.atr??-1,
  adr: s=> s.adr_pct??-1,
  rating: s=> s.recommend_all??-1,
};

// Breadth Timeline — daily snapshots from /api/industry-detail history:
// % of constituents above the 20/50/200 SMA plus the leadership score, so a
// rising score on falling breadth (narrowing leadership) is visible at a glance.
function BreadthTimeline({history}) {
  if(!history || history.length===0)
    return <div className="empty">No history yet — click Sync Live Data; snapshots accumulate each day.</div>;
  const w=600, h=220, pad=34;
  const xFor = i=> history.length===1 ? w/2 : pad + (i/(history.length-1))*(w-pad*2);
  const yFor = v=> h-24 - (Math.max(0, Math.min(100, v))/100)*(h-24-14);
  // Build one path per series, breaking segments across null points.
  function linePath(get){
    let d="", pen=false;
    history.forEach((pt,i)=>{
      const v = get(pt);
      if(v===null || v===undefined || isNaN(v)){ pen=false; return; }
      d += (pen?" L":"M ")+xFor(i).toFixed(1)+" "+yFor(v).toFixed(1);
      pen = true;
    });
    return d;
  }
  const series = [
    {label:"Above 20MA", color:"var(--accent)", get: p=>p.breadth_20},
    {label:"Above 100EMA", color:"var(--green)", get: p=>p.breadth_50},
    {label:"Above 200MA", color:"var(--amber)", get: p=>p.breadth_200},
    {label:"Score", color:"var(--purple)", get: p=>p.score, dashed:true},
  ];
  const first = history[0], mid = history[Math.floor(history.length/2)], last = history[history.length-1];
  const xl = [ [pad, first.dt], [xFor(Math.floor(history.length/2)), mid.dt], [w-pad, last.dt] ];
  return (
    <div>
      <svg width="100%" viewBox={"0 0 "+w+" "+h}>
        {[0,50,100].map((g,gi)=>(
          <g key={gi}>
            <line x1={pad} x2={w-pad} y1={yFor(g)} y2={yFor(g)} stroke="#1c2027" strokeWidth="1"/>
            <text x={6} y={yFor(g)+3} fontSize="9" fill="var(--text-faint)" fontFamily="var(--mono)">{g}%</text>
          </g>
        ))}
        {xl.map((x,i)=> <text key={i} x={x[0]} y={h-8} fontSize="9" fill="var(--text-faint)" textAnchor="middle" fontFamily="var(--mono)">{x[1]}</text>)}
        {series.map((s,si)=>{
          const d = linePath(s.get);
          return d ? <path key={si} d={d} fill="none" stroke={s.color} strokeWidth="1.8" strokeDasharray={s.dashed?"5,3":undefined}/> : null;
        })}
        {/* Visible markers so a series with one or two isolated points is
            never invisible (an SVG line path draws nothing for a single point). */}
        {history.length<3 && series.map((s,si)=>
          history.map((pt,i)=>{
            const v = s.get(pt);
            if(v===null || v===undefined || isNaN(v)) return null;
            return <circle key={si+"-"+i} cx={xFor(i)} cy={yFor(v)} r="3.5" fill={s.color}/>;
          })
        )}
      </svg>
      <div className="hint" style={{marginTop:8}}>Breadth rising with score = confirmed strength · score up while breadth falls = divergence / narrowing leadership.</div>
    </div>
  );
}

function IndustryDetail({industry, onBack, onSelectSector, strategy, wl}) {
  const [stocks, loading, , err] = useApi(apiUrl("/api/industry-stocks?name="+encodeURIComponent(industry), strategy), [industry, strategy]);
  const [detail] = useApi("/api/industry-detail?name="+encodeURIComponent(industry), [industry]);
  const sort = useSortable((a,b)=> (b.chg_3m??-999)-(a.chg_3m??-999));
  const [page, setPage] = useState(1);
  const [chartsOn, setChartsOn] = useState(false);
  const [chartLayout, updateChartLayout] = useChartLayout();

  // Industry chart: TradingView benchmark from the backend — a dedicated
  // industry ETF, or an equal-weight custom-index expression over the top
  // market-cap members, or none (<3 stocks). The EMA readout comes from the
  // same benchmark (scanner for ETFs, member EMAs for custom indices), so
  // the chart title, symbol and readout always refer to the same thing.
  const tvSym = detail ? detail.tv_symbol : null;
  const [emas, setEmas] = useState(null);
  useEffect(()=>{
    setEmas(null);
    if(!tvSym || !tvSym.kind || tvSym.kind==="none") return;
    fetch(API+"/api/industry-benchmark-emas?name="+encodeURIComponent(industry))
      .then(r=> r.ok ? r.json() : null)
      .then(setEmas)
      .catch(()=>setEmas(null));
  },[industry, tvSym && tvSym.symbol]);

  if(loading) return <div className="loading">Loading industry…</div>;
  if(err) return <div className="loading error">Error: {err}</div>;
  if(!stocks) return null;

  const n = stocks.length || 1;
  const agg = {
    avg_chg_1w: avg(stocks.map(s=>s.chg_1w||0)),
    avg_chg_1m: avg(stocks.map(s=>s.chg_1m||0)),
    avg_chg_3m: avg(stocks.map(s=>s.chg_3m||0)),
    avg_chg_6m: avg(stocks.map(s=>s.chg_6m||0)),
    breadth_20: stocks.filter(s=>s.above_20d).length/n*100,
    breadth_50: stocks.filter(s=>(s.above_100ema ?? s.above_50d)).length/n*100,
    pct_new_highs: stocks.filter(s=>((s.dist_high_3m??s.pct_from_52w_high)??-100)>=-5).length/n*100,
    avg_volume_ratio: avg(stocks.map(s=>s.volume_ratio||0)),
    avg_volatility_d: avg(stocks.map(s=>s.volatility_d||0)),
    avg_recommend_all: avg(stocks.map(s=>s.recommend_all||0)),
  };
  const sorted = sort.apply(withStockScores(stocks), IND_STOCK_SORT_KEYS);
  const indTotalPages = Math.max(1, Math.ceil(sorted.length / DRILL_PAGE_SIZE));
  const indCurPage = Math.min(page, indTotalPages);
  const indPageRows = sorted.slice((indCurPage-1)*DRILL_PAGE_SIZE, indCurPage*DRILL_PAGE_SIZE);
  function indToggleSort(k){ sort.toggle(k); setPage(1); }
  const indSortCtl = {...sort, toggle: indToggleSort};

  return (
    <div className="page">
      <div className="back" onClick={onBack}><Icon.back/> Back</div>

      <div className="sector-header" style={{borderLeftColor:"var(--accent)"}}>
        <div>
          <div className="flex gap-3 ai-center">
            <span className="dot-lg" style={{background:"var(--accent)"}}></span>
            <h1 className="page-title">{industry}</h1>
            <span className="mono text-faint">{stocks.length} stocks</span>
          </div>
          <div className="page-subtitle">
            Industry — TradingView classification
            {detail && detail.sector_name && (
              <span>
                {" · sector: "}
                <span
                  className="fw-700"
                  style={{color:"var(--accent)", cursor: onSelectSector ? "pointer" : "default"}}
                  onClick={onSelectSector && detail.sector_id!=null ? ()=>onSelectSector(detail.sector_id) : undefined}
                  title={onSelectSector ? "Open the "+detail.sector_name+" sector page" : undefined}
                >{detail.sector_name}</span>
              </span>
            )}
            {tvSym && tvSym.benchmark && <span>{" · benchmark: "}<span className="mono fw-700">{tvSym.benchmark}</span></span>}
          </div>
          {detail && detail.leadership_score!=null && (
            <div className="page-subtitle" style={{marginTop:4}}>
              <span style={{color:"var(--accent)", fontWeight:700}}>Industry leadership</span>
              {" "}· Performance {detail.perf_component!=null ? detail.perf_component.toFixed(1) : "—"}
              {detail.cci_factor!=null ? " + CCI "+detail.cci_factor.toFixed(0)+" (65/35)" : " only (1M > 3M > 1W)"}
              {" "}→ <span className="mono">{detail.leadership_score.toFixed(1)}</span>
              {detail.leadership_rank!=null && <span className="text-faint">{" "}· rank #{detail.leadership_rank}</span>}
            </div>
          )}
        </div>
        <div className="sector-header-metrics">
          <div className="metric" title="TradingView's exact published 3-month industry performance (INDUSTRY_US aggregate — the same number shown on TradingView's industry page)">
            <div className="stat-label">3M</div>
            <div className={"stat-xl "+pctClass(detail && detail.chg_3m!=null ? detail.chg_3m : agg.avg_chg_3m)}>{fmtPct(detail && detail.chg_3m!=null ? detail.chg_3m : agg.avg_chg_3m)}</div>
          </div>
          <div className="metric" title="TradingView's exact published 1-month industry performance (INDUSTRY_US aggregate — the same number shown on TradingView's industry page)">
            <div className="stat-label">1M</div>
            <div className={"stat-xl "+pctClass(detail && detail.chg_1m!=null ? detail.chg_1m : agg.avg_chg_1m)}>{fmtPct(detail && detail.chg_1m!=null ? detail.chg_1m : agg.avg_chg_1m)}</div>
          </div>
          <div className="metric">
            <div className="stat-label">Breadth &gt;100EMA</div>
            <div className="stat-xl">{agg.breadth_50.toFixed(0)}%</div>
          </div>
        </div>
      </div>

      {tvSym && tvSym.kind!=="none" && tvSym.symbol && (
        <div className="panel">
          <div className="panel-title">
            <span>{tvSym.kind==="custom_index" ? (tvSym.benchmark+" — Industry Custom Index") : (tvSym.symbol.split(":").pop()+" — Industry Benchmark Chart")}</span>
            <span className="hint">EMA 5 / 10 / 20 / 50 / 200 · logarithmic scale, not auto-scaled{tvSym.kind==="custom_index" ? " · equal-weight basket of the top members by market cap" : " · dedicated industry ETF benchmark"}</span>
          </div>
          <TVChart symbol={tvSym.symbol} interval="D" height={420}/>
          <EmaStrip emas={emas} price={emas ? emas.price : null}/>
          {tvSym.kind==="custom_index" && tvSym.members && (
            <div className="hint" style={{marginTop:8}}>
              Equal-weight custom index of {tvSym.members.length} members (top by market cap): <span className="mono">{tvSym.members.join(", ")}</span>
              {" · expression: "}<span className="mono">{tvSym.symbol}</span>
            </div>
          )}
        </div>
      )}
      {tvSym && tvSym.kind==="none" && (
        <div className="panel">
          <div className="panel-title"><span>Industry Chart</span></div>
          <div className="empty">No chart available — this industry has fewer than 3 stocks in the filtered universe and no dedicated industry ETF.</div>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">Key Metrics</div>
        <div className="grid-4">
          <div className="metric-card" title="Number of stocks in this TradingView industry passing the scanner filters"><div className="stat-label">Stocks</div><div className="stat-value">{stocks.length}</div></div>
          <div className="metric-card" title="Industry leadership score: >25 stocks = 65% performance + 35% CCI; <=25 stocks = performance only (1M > 3M > 1W)"><div className="stat-label">Leadership</div><div className="stat-value">{detail && detail.leadership_score!=null ? detail.leadership_score.toFixed(1) : "—"}</div></div>
          <div className="metric-card" title="CCI(34) rating of the industry's benchmark ETF (falls back to the parent sector's ETF CCI)"><div className="stat-label">Industry CCI</div><div className="stat-value" style={{color: detail && detail.cci_rating ? cciRatingColor(detail.cci_rating) : undefined}}>{detail && detail.cci_rating ? detail.cci_rating : (detail && detail.cci_factor!=null ? detail.cci_factor.toFixed(0)+"*" : "—")}</div>
            {detail && detail.cci34!=null && <div className="text-faint" style={{fontSize:11, fontFamily:"var(--mono)", marginTop:4}}>CCI(34) {detail.cci34} · EMA {detail.cci_ema}</div>}
            {detail && detail.cci34==null && detail.cci_factor!=null && <div className="text-faint" style={{fontSize:11, fontFamily:"var(--mono)", marginTop:4}}>* sector/market CCI (sync to compute industry ETF CCI)</div>}
          </div>
          <div className="metric-card" title="Average 1-week return across constituents"><div className="stat-label">Avg 1W</div><div className={"stat-value "+pctClass(agg.avg_chg_1w)}>{fmtPct(agg.avg_chg_1w)}</div></div>
          <div className="metric-card" title="Average 6-month return across constituents"><div className="stat-label">Avg 6M</div><div className={"stat-value "+pctClass(agg.avg_chg_6m)}>{fmtPct(agg.avg_chg_6m)}</div></div>
          <div className="metric-card" title="Share of constituents trading above their 20-day moving average"><div className="stat-label">Breadth &gt;20MA</div><div className="stat-value">{agg.breadth_20.toFixed(0)}%</div></div>
          <div className="metric-card" title="Share of constituents within 5% of their 3-month high"><div className="stat-label">Near 3M Highs</div><div className="stat-value">{agg.pct_new_highs.toFixed(0)}%</div></div>
          <div className="metric-card" title="Average relative volume vs the 30-day average — above 1.00x means expanding interest"><div className="stat-label">Avg Vol Ratio</div><div className="stat-value">{agg.avg_volume_ratio.toFixed(2)}x</div></div>
          <div className="metric-card" title="Average TradingView daily volatility across constituents"><div className="stat-label">Avg Volatility.D</div><div className="stat-value">{agg.avg_volatility_d.toFixed(2)}%</div></div>
          <div className="metric-card" title="Average TradingView analyst rating (0-1 scale: <0.35 Sell, 0.35-0.45 Neutral, 0.45+ Buy)"><div className="stat-label">Avg TV Rating</div><div className={"stat-value "+ratingClass(agg.avg_recommend_all)}>{fmtRating(agg.avg_recommend_all)}</div></div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Breadth Timeline</span>
          <span className="hint">
            <span className="legend-dot" style={{background:"var(--accent)"}}></span>Above 20MA&nbsp;&nbsp;
            <span className="legend-dot" style={{background:"var(--green)"}}></span>Above 100EMA&nbsp;&nbsp;
            <span className="legend-dot" style={{background:"var(--amber)"}}></span>Above 200MA&nbsp;&nbsp;
            <span className="legend-dot" style={{background:"var(--purple)"}}></span>Score (dashed)
          </span>
        </div>
        <BreadthTimeline history={detail ? detail.history : null}/>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Constituents</span>
          <span className="hint">Click a column heading to sort descending · click again to restore · flip Charts on to view every stock as TradingView charts (5/10/20/50/200 EMA)</span>
        </div>
        <div className="toggle-row" style={{alignItems:"center"}}>
          <Switch on={chartsOn} onChange={setChartsOn} label="Charts"
                  title="Show TradingView charts for every stock in this industry (same chart engine as sector constituents)"/>
        </div>
        {chartsOn && <ChartLayoutSettings layout={chartLayout} onChange={updateChartLayout}/>}
        {chartsOn ? (
          <div>
            <StockChartsGrid stocks={indPageRows} layout={chartLayout} renderAction={s=><WatchBtn wl={wl} ticker={s.ticker}/>}/>
            <Pager page={indCurPage} totalPages={indTotalPages} onPage={setPage}/>
          </div>
        ) : (
        <div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th title="Watchlist">✓</th>
                <SortTh label="Ticker" k="ticker" sort={indSortCtl}/>
                <SortTh label="Sector" k="sector" sort={indSortCtl}/>
                <SortTh label="Price" k="price" sort={indSortCtl}/>
                <SortTh label="Mkt Cap" k="mcap" sort={indSortCtl}/>
                <SortTh label="Score" k="score" sort={indSortCtl} title="Relative Strength score: percentile rank (0-100) of the performance composite (15% 1W / 50% 1M / 35% 3M) within the full screener universe; the score is universal per stock and identical in every view"/>
                <SortTh label="1D" k="chg_1d" sort={indSortCtl}/>
                <SortTh label="1W" k="chg_1w" sort={indSortCtl}/>
                <SortTh label="1M" k="chg_1m" sort={indSortCtl}/>
                <SortTh label="3M" k="chg_3m" sort={indSortCtl}/>
                <SortTh label="6M" k="chg_6m" sort={indSortCtl}/>
                <SortTh label="RS" k="rs" sort={indSortCtl}/>
                <SortTh label="% fr Hi" k="from_hi" sort={indSortCtl}/>
                <SortTh label="Vol x" k="vol" sort={indSortCtl}/>
                <SortTh label="Vol.D" k="vold" sort={indSortCtl} title="TradingView daily volatility"/>
                <SortTh label="ATR" k="atr" sort={indSortCtl}/>
                <SortTh label="ADR" k="adr" sort={indSortCtl} title="Average daily range %"/>
                <SortTh label="Rating" k="rating" sort={indSortCtl} title="TradingView analyst rating (0-1)"/>
              </tr>
            </thead>
            <tbody>
              {indPageRows.map(s=>(
                <tr key={s.ticker}>
                  <td className="watch-cell"><WatchBtn wl={wl} ticker={s.ticker}/></td>
                  <td className="mono fw-700">{s.ticker}</td>
                  <td>{s.sector_color && <span className="dot" style={{background:s.sector_color}}></span>} {s.sector_name || "—"}</td>
                  <td>${(s.price||0).toFixed(2)}</td>
                  <td>{fmtCap(s.market_cap_musd)}</td>
                  <td><div className="score-cell"><span>{(s._score||0).toFixed(0)}</span><ScoreBar value={s._score||0}/></div></td>
                  <td className={pctClass(s.chg_1d)}>{fmtPct(s.chg_1d)}</td>
                  <td className={pctClass(s.chg_1w)}>{fmtPct(s.chg_1w)}</td>
                  <td className={pctClass(s.chg_1m)}>{fmtPct(s.chg_1m)}</td>
                  <td className={pctClass(s.chg_3m)}>{fmtPct(s.chg_3m)}</td>
                  <td className={pctClass(s.chg_6m)}>{s.chg_6m==null?"—":fmtPct(s.chg_6m)}</td>
                  <td>{(s.rs_rating||0).toFixed(0)}</td>
                  <td className="neg">{s.pct_from_52w_high==null?"—":s.pct_from_52w_high.toFixed(1)+"%"}</td>
                  <td>{(s.volume_ratio||0).toFixed(2)}{s.volume_ratio>2 && <Icon.flame color="var(--amber)"/>}</td>
                  <td>{s.volatility_d==null?"—":s.volatility_d.toFixed(2)+"%"}</td>
                  <td>{s.atr==null?"—":s.atr.toFixed(2)}</td>
                  <td>{s.adr_pct==null?"—":s.adr_pct.toFixed(2)+"%"}</td>
                  <td className={ratingClass(s.recommend_all)}>{fmtRating(s.recommend_all)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={indCurPage} totalPages={indTotalPages} onPage={setPage}/>
        </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Industries page — market-wide industry leadership, rotation and breadth
// ---------------------------------------------------------------------------
const IND_TF_OPTIONS = [["1D","chg_1d"],["1W","chg_1w"],["1M","chg_1m"],["3M","chg_3m"],["6M","chg_6m"]];

function IndustriesPage({onSelectIndustry, strategy, wl}) {
  const [industries, loading] = useApi(apiUrl("/api/industries", strategy), [strategy]);
  const [tf, setTf] = useState("chg_1m");
  const [sectorFilter, setSectorFilter] = useState("All");

  if(loading || !industries) return <div className="page"><div className="loading">Loading industries…</div></div>;

  const rows = industries || [];
  const tfLabel = (IND_TF_OPTIONS.find(o=>o[1]===tf)||["?"])[0];

  // KPI strip — null deltas mean no history yet (sync builds it day by day).
  const leaderCount = rows.filter(r=> String(r.state||"").toLowerCase()==="leader").length;
  const deltasKnown = rows.some(r=> r.score_delta!=null);
  const improving = rows.filter(r=> (r.score_delta??0) >= 3).length;
  const weakening = rows.filter(r=> r.score_delta!=null && r.score_delta <= -3).length;
  const b50s = rows.map(r=>r.breadth_50).filter(v=> v!=null);
  const avgB50 = b50s.length ? avg(b50s) : null;

  // Leadership scoring now lives in <IndustryLeaderboards> (the new
  // percentile-ranked scoring system supersedes the old snapshot panel).
  const sectorsPresent = ["All", ...Array.from(new Set(rows.map(r=>r.sector_name).filter(Boolean))).sort()];
  const heatRows = rows.filter(r=> sectorFilter==="All" || r.sector_name===sectorFilter);
  const tmItems = heatRows.map(r=>({
    label: r.industry,
    value: Math.max(1, r.stock_count||1),
    color: heatBg(r[tf], 5) || "rgba(122,132,148,0.25)",
    sub: fmtPct1(r[tf]),
    title: (r.sector_name?r.sector_name+" · ":"")+tfLabel+" "+fmtPct(r[tf])+" · "+(r.stock_count||0)+" stocks",
    onSelect: ()=>onSelectIndustry(r.industry, null),
  }));

  // Capital rotation
  const inflowing = rows.filter(r=> r.score_delta!=null).sort((a,b)=> b.score_delta-a.score_delta).slice(0,5);
  const outflowing = rows.filter(r=> r.score_delta!=null).sort((a,b)=> a.score_delta-b.score_delta).slice(0,5);
  const maxScore = Math.max(...rows.map(r=> r.leadership_score||0), 100);
  function rotRow(r, idx){
    return (
      <div key={r.industry} className="rot-row hover-row" onClick={()=>onSelectIndustry(r.industry, null)}>
        <span className={"mono rot-delta "+pctClass(r.score_delta)}>{(r.score_delta>=0?"+":"")+r.score_delta.toFixed(1)}</span>
        <span className="fw-700">{r.industry}</span>
        <span className="text-dim rot-sector">{r.sector_name||"—"}</span>
        <span className="rot-bar"><ScoreBar value={r.leadership_score||0}/></span>
        <span className="mono text-faint">{r.leadership_score!=null?r.leadership_score.toFixed(0):"—"}</span>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Industries</h1>
          <div className="page-subtitle">Market-wide industry leadership, rotation and breadth</div>
        </div>
      </div>

      <div className="grid-4">
        <div className="metric-card" title="Industries currently in Leading state"><div className="stat-label">Leading</div><div className="stat-value" style={{color:"var(--green)"}}>{leaderCount}</div></div>
        <div className="metric-card" title="Leadership score up 3+ points vs the previous snapshot"><div className="stat-label">Improving</div><div className={"stat-value "+(deltasKnown?"pos":"")}>{deltasKnown?improving:"—"}</div>
          {!deltasKnown && <div className="hint" style={{marginTop:4}}>sync to build history</div>}</div>
        <div className="metric-card" title="Leadership score down 3+ points vs the previous snapshot"><div className="stat-label">Weakening</div><div className={"stat-value "+(deltasKnown?"neg":"")}>{deltasKnown?weakening:"—"}</div>
          {!deltasKnown && <div className="hint" style={{marginTop:4}}>sync to build history</div>}</div>
        <div className="metric-card" title="Average % of constituents above their 100-day EMA"><div className="stat-label">Avg breadth &gt;100EMA</div><div className="stat-value">{avgB50==null?"—":avgB50.toFixed(1)+"%"}</div></div>
      </div>

      <IndustryLeaderboards onSelectIndustry={onSelectIndustry}/>

      <div className="panel">
        <div className="panel-title">
          <span>Performance Heatmap</span>
          <span className="hint">tile size ∝ stocks in industry · color = {tfLabel} change · click a tile to open the industry</span>
        </div>
        <div className="filter-pills">
          {IND_TF_OPTIONS.map(o=>(
            <span key={o[1]} className={"filter-pill clickable "+(tf===o[1]?"active":"")} onClick={()=>setTf(o[1])}>{o[0]}</span>
          ))}
        </div>
        <div className="filter-pills">
          {sectorsPresent.map(s=>(
            <span key={s} className={"filter-pill clickable "+(sectorFilter===s?"active":"")} onClick={()=>setSectorFilter(s)}>{s}</span>
          ))}
        </div>
        <Treemap items={tmItems} width={900} height={420}/>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Capital Rotation</span>
          <span className="hint">change in leadership score vs the previous snapshot</span>
        </div>
        {!deltasKnown ? (
          <div className="empty">Run Sync Live Data on two different days to see rotation.</div>
        ) : (
          <div className="grid-2">
            <div>
              <div className="section-title" style={{margin:"0 0 10px 2px"}}>Inflowing</div>
              {inflowing.length ? inflowing.map(rotRow) : <div className="empty">No movers</div>}
            </div>
            <div>
              <div className="section-title" style={{margin:"0 0 10px 2px"}}>Outflowing</div>
              {outflowing.length ? outflowing.map(rotRow) : <div className="empty">No movers</div>}
            </div>
          </div>
        )}
      </div>

      <IndustryTable industries={rows} showSector={true} onSelectIndustry={n=>onSelectIndustry(n, null)}
        title="All Industries" hint="click headers to sort · click a row to drill in"/>
    </div>
  );
}

const INDEX_NAMES = {
  SPY: "S&P 500",
  QQQ: "Nasdaq 100",
  DJI: "Dow Jones Industrial",
  IWM: "Russell 2000",
};
const INDEX_DESCS = {
  SPY: "Tracks 500 of the largest U.S. companies — the broad benchmark for the overall market.",
  QQQ: "Tracks the 100 largest non-financial Nasdaq names — the gauge for mega-cap tech and growth.",
  DJI: "Tracks 30 blue-chip industrials — the oldest and most price-weighted of the major averages.",
  IWM: "Tracks ~2,000 small-cap stocks — the barometer for domestic risk appetite and breadth.",
};
const RETURN_PERIODS = [
  ["1D", "chg_1d"], ["1W", "chg_1w"], ["1M", "chg_1m"],
  ["3M", "chg_3m"], ["YTD", "chg_ytd"], ["1Y", "chg_1y"],
];

function IndexPanel({idx, order}) {
  const ratingColor = cciRatingColor(idx.rating);
  return (
    <div className="idx-group anim-fade-up" style={{animationDelay:(order*90)+"ms"}} title={INDEX_DESCS[idx.ticker] || ""}>
      <div className="metric-card">
        <div className="fw-700">{idx.ticker} <span className="text-faint" style={{fontWeight:400, fontSize:11}}>{INDEX_NAMES[idx.ticker] || "Index"}</span></div>
        <div className="flex gap-2 ai-baseline" style={{marginTop:4}}>
          <span className="stat-lg">{fmtPrice(idx.price)}</span>
          <span className={"stat-value "+pctClass(idx.chg_1d)}>{fmtPct(idx.chg_1d)}</span>
        </div>
      </div>
      <div className="metric-card">
        <div className="stat-label">CCI Rating</div>
        <div className="stat-value" style={{color:ratingColor}}>{idx.rating || "—"}</div>
        <div className="text-faint" style={{fontSize:11, fontFamily:"var(--mono)", marginTop:4}}>
          CCI(34) {idx.cci34!=null ? idx.cci34.toFixed(0) : "—"} · EMA {idx.cci_ema!=null ? idx.cci_ema.toFixed(0) : "—"}
        </div>
        {idx.dt && <div className="text-faint" style={{fontSize:11, fontFamily:"var(--mono)", marginTop:2}}>{idx.dt}</div>}
      </div>
      <div className="metric-card">
        <div className="stat-label">Returns</div>
        <div className="idx-mini-rets">
          {RETURN_PERIODS.map(([label, key])=>(
            <div key={key}>
              <div className="stat-label">{label}</div>
              <div className={idx[key]!=null ? pctClass(idx[key]) : "text-faint"} style={{fontFamily:"var(--mono)", fontSize:12}}>{fmtPct1(idx[key])}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Dashboard({data, onSelectSector, onSelectIndustry, config}) {
  const [rrg] = useApi("/api/rrg", []);
  if(!data) return <div className="loading">Loading dashboard…</div>;
  // Every page uses snapshot.score — the canonical CCI-based sector score
  // (50% performance + 50% CCI).
  const sectors = data.sectors || [];
  const indices = (data.market_summary && data.market_summary.indices) || [];
  const counts = {leader:0, emerging:0, neutral:0, fading:0, lagging:0};
  sectors.forEach(s=>{ const sn = snapOf(s); const st = sn.canonical_state || sn.state || "neutral"; counts[st] = (counts[st]||0)+1; });
  const donutSegs = [
    {label:"Leaders", value:counts.leader, color:"var(--green)"},
    {label:"Emerging", value:counts.emerging, color:"var(--green-soft)"},
    {label:"Neutral", value:counts.neutral, color:"var(--amber)"},
    {label:"Fading", value:counts.fading, color:"var(--red)"},
    {label:"Lagging", value:counts.lagging, color:"#7a8494"},
  ].filter(s=>s.value>0);
  // RRG trails: JDK-style RS-Ratio (x) / RS-Momentum (y) of each sector's
  // benchmark ETF vs SPY on closed weekly bars, from /api/rrg — centered on
  // (100,100). Falls back to the snapshot-derived approximation while the
  // endpoint has no data yet.
  let rrgMid = {x: 100, y: 100};
  let sectorRrgPaths = (rrg && rrg.paths) || [];
  if(!sectorRrgPaths.length){
    rrgMid = {x: 100, y: 0};
    sectorRrgPaths = sectors.map(s=>{
      const hist = (s.history||[]).slice(-12);
      if(hist.length<2) return null;
      const pts = hist.map((h,i)=>({
        x: 95 + (((h.avg_rs_rating??50) - 50)*0.6),
        y: (((h.score??0) - (hist[i-1]?.score ?? h.score ?? 0))*3),
        dt: h.dt,
      }));
      return {etf: s.ticker, color: s.color || "var(--accent)", points: pts};
    }).filter(Boolean);
  }
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Markets</h1>
          <div className="page-subtitle">Benchmark trend, risk environment and cross-sector rotation at a glance</div>
        </div>
        {config && <div className="filter-pill">Mkt cap ≥ {fmtCap(config.min_market_cap_musd)} · Vol(30D) &gt; 1M · ADR ≥ 3%</div>}
      </div>

      {data.strategy && (
        <div className="strategy-strip">
          <span className="strategy-name">{data.strategy.label} dashboard</span>
          <span className="text-dim">Markets is universal. Sector ranking is CCI-based: 50% performance (15% 1W / 50% 1M / 35% 3M, normalized) + 50% CCI (market factor {data.strategy.cci_factor}).</span>
        </div>
      )}

      <div className="section-title">Major Indexes</div>
      <div className="idx-grid">
        {indices.map((idx,i)=> <IndexPanel key={idx.ticker} idx={idx} order={i+2}/>)}
      </div>
      {!indices.length && <div className="empty">No index data available — run a live sync.</div>}

      <div className="section-title">Market Overview</div>
      <div className="anim-fade-up"><MarketSummary market={data.market_summary}/></div>
      <div className="grid-2 market-overview-grid">
        <div className="panel anim-fade-up" style={{animationDelay:"60ms"}}>
          <div className="panel-title">
            <span>Benchmark Trend — Composite</span>
          </div>
          <MarketAreaChart values={data.market_history}/>
        </div>
        <div className="panel anim-fade-up" style={{animationDelay:"90ms"}}>
          <div className="panel-title">
            <span>Relative Rotation Graph — All Sectors</span>
            <span className="hint">Weekly RS-Ratio / RS-Momentum vs SPY · 8-week trails</span>
          </div>
          <RRGChart paths={sectorRrgPaths} midX={rrgMid.x} midY={rrgMid.y}/>
        </div>
      </div>

      <div className="section-title">Risk Environment</div>
      <div className="anim-fade-up" style={{animationDelay:"90ms"}}>
        <RiskStrip sectors={sectors} market={data.market_summary}/>
      </div>

      <div className="section-title">Sector Scoreboard</div>
      <div className="grid-2 scoreboard-grid">
        <div className="panel">
          <div className="panel-title">
            <span>Composite Score by Sector</span>
            <span className="hint">Colored by rotation state · click to drill in</span>
          </div>
          <SectorScoreBars sectors={sectors} onSelectSector={onSelectSector}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>Rotation State Distribution</span></div>
          <Donut segments={donutSegs} size={230} thickness={34} centerLabel={sectors.length+" sectors"}/>
        </div>
      </div>

      <div className="section-title" style={{fontSize:12.5}}>Performance &amp; Breadth Comparison</div>
      <div className="grid-2">
        <div className="panel">
          <div className="panel-title" style={{fontSize:14}}>
            <span>Sector Returns — 1W / 1M / 3M</span>
            <span className="hint">Ranked by 1M · hover bars for values</span>
          </div>
          <PerfCompareBars sectors={sectors} onSelectSector={onSelectSector} compact/>
          <div className="legend">
            <span><span className="legend-dot" style={{background:"var(--accent)"}}></span>1W</span>
            <span><span className="legend-dot" style={{background:"var(--purple)"}}></span>1M</span>
            <span><span className="legend-dot" style={{background:"var(--amber)"}}></span>3M</span>
          </div>
        </div>
        <div className="panel">
          <div className="panel-title" style={{fontSize:14}}>
            <span>Participation — % Above 20 / 50 / 200 MA</span>
            <span className="hint">Share of each sector's constituents above key moving averages</span>
          </div>
          <BreadthCompareBars sectors={sectors} onSelectSector={onSelectSector} compact/>
          <div className="legend">
            <span><span className="legend-dot" style={{background:"var(--green)"}}></span>&gt;20MA</span>
            <span><span className="legend-dot" style={{background:"var(--accent)"}}></span>&gt;50MA</span>
            <span><span className="legend-dot" style={{background:"var(--purple)"}}></span>&gt;200MA</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sector detail
// ---------------------------------------------------------------------------
function HoldingsTable({holdings, filter, chartsOn=false, layout=null, wl=null}) {
  // The # column is a fixed position counter: it always reads 1..N top to
  // bottom in the currently displayed order (across pages) and is not sortable.
  const sort = useSortable((a,b)=> (a.rank||1e9) - (b.rank||1e9));
  const [page, setPage] = useState(1);
  useEffect(()=>{ setPage(1); }, [filter]);
  const shown = sort.apply(withStockScores(holdings).filter(h=> filter==='all' || h.classification===filter), HOLDING_SORT_KEYS);
  const totalPages = Math.max(1, Math.ceil(shown.length / DRILL_PAGE_SIZE));
  const curPage = Math.min(page, totalPages);
  const pageRows = shown.slice((curPage-1)*DRILL_PAGE_SIZE, curPage*DRILL_PAGE_SIZE);
  function toggleSort(k){ sort.toggle(k); setPage(1); }
  const sortCtl = {...sort, toggle: toggleSort};
  const chartIntervals = chartsOn && layout ? layoutIntervals(layout) : [];
  const chartHeight = layout ? (CHART_SIZE_PX[layout.size] || 360) : 360;
  const N_COLS = 20; // keep the chart row spanning the full table width
  // The table itself can be wider than the viewport (horizontal scroll). The
  // chart row must instead match the VISIBLE container width so charts are
  // never cut off — measure the scroll container and pin the chart area to it.
  const [scrollRef, scrollW] = useContainerWidth();
  const chartWidth = scrollW ? Math.max(280, scrollW - 26) : null;
  return (
    <div>
    <div className="table-scroll" ref={scrollRef}>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th title="Watchlist">✓</th>
            <SortTh label="Ticker" k="ticker" sort={sortCtl}/>
            <SortTh label="Price" k="price" sort={sortCtl}/>
            <SortTh label="Mkt Cap" k="mcap" sort={sortCtl}/>
            <SortTh label="Avg Vol" k="avgvol" sort={sortCtl}/>
            <SortTh label="Score" k="score" sort={sortCtl} title="Relative Strength score: percentile rank (0-100) of the performance composite (15% 1W / 50% 1M / 35% 3M) within the full screener universe; the score is universal per stock and identical in every view"/>
            <SortTh label="1D" k="chg_1d" sort={sortCtl}/>
            <SortTh label="1W" k="chg_1w" sort={sortCtl}/>
            <SortTh label="1M" k="chg_1m" sort={sortCtl}/>
            <SortTh label="3M" k="chg_3m" sort={sortCtl}/>
            <SortTh label="6M" k="chg_6m" sort={sortCtl}/>
            <SortTh label="RS" k="rs" sort={sortCtl}/>
            <SortTh label="% fr Hi" k="from_hi" sort={sortCtl}/>
            <SortTh label="Vol x" k="vol" sort={sortCtl}/>
            <SortTh label="Vol.D" k="vold" sort={sortCtl} title="TradingView daily volatility"/>
            <SortTh label="ADR" k="adr" sort={sortCtl} title="Average daily range %"/>
            <SortTh label="Rating" k="rating" sort={sortCtl} title="TradingView analyst rating (0-1)"/>
            <th>MAs</th><th>Class</th>
          </tr>
        </thead>
        <tbody>
          {pageRows.map((h,i)=> (
            <React.Fragment key={h.stock_ticker}>
            <tr className={h.classification}>
              <td>{(curPage-1)*DRILL_PAGE_SIZE + i + 1}</td>
              <td className="watch-cell"><WatchBtn wl={wl} ticker={h.stock_ticker}/></td>
              <td className="mono fw-700">{h.stock_ticker}</td>
              <td>${h.price.toFixed(2)}</td>
              <td>{fmtCap(h.market_cap_musd)}</td>
              <td>{fmtVol(h.avg_volume)}</td>
              <td><div className="score-cell"><span>{(h._score||0).toFixed(0)}</span><ScoreBar value={h._score||0}/></div></td>
              <td className={pctClass(h.chg_1d)}>{fmtPct(h.chg_1d)}</td>
              <td className={pctClass(h.chg_1w)}>{fmtPct(h.chg_1w)}</td>
              <td className={pctClass(h.chg_1m)}>{fmtPct(h.chg_1m)}</td>
              <td className={pctClass(h.chg_3m)}>{fmtPct(h.chg_3m)}</td>
              <td className={pctClass(h.chg_6m)}>{h.chg_6m==null?"—":fmtPct(h.chg_6m)}</td>
              <td>{h.rs_rating.toFixed(0)}</td>
              <td className="neg">{h.pct_from_52w_high.toFixed(1)}%</td>
              <td>{h.volume_ratio.toFixed(2)}{h.volume_ratio>2 && <Icon.flame color="var(--amber)"/>}</td>
              <td>{h.volatility_d==null?"—":h.volatility_d.toFixed(2)+"%"}</td>
              <td>{h.adr_pct==null?"—":h.adr_pct.toFixed(2)+"%"}</td>
              <td className={ratingClass(h.recommend_all)}>{fmtRating(h.recommend_all)}</td>
              <td className="ma-icons">
                {h.above_20d?<Icon.up color="var(--green)"/>:<Icon.down color="var(--red)"/>}
                {h.above_50d?<Icon.up color="var(--green)"/>:<Icon.down color="var(--red)"/>}
                {h.above_200d?<Icon.up color="var(--green)"/>:<Icon.down color="var(--red)"/>}
              </td>
              <td>
                {h.classification==='leader' && <span className="tag-leader">Leader</span>}
                {h.classification==='laggard' && <span className="tag-laggard">Laggard</span>}
                {h.classification==='neutral' && <span className="tag-neutral">—</span>}
              </td>
            </tr>
            {chartsOn && (
              <tr className="chart-row">
                <td colSpan={N_COLS}>
                  <div className="row-charts" data-cols={chartIntervals.length}
                    style={{gridTemplateColumns:"repeat("+chartIntervals.length+",1fr)", width: chartWidth ? chartWidth+"px" : "100%"}}>
                    {chartIntervals.map(iv=>(
                      <div key={iv} className="row-chart-cell">
                        <div className="row-chart-title mono">{h.stock_ticker} · {iv==="D"?"Daily":iv==="W"?"Weekly":iv==="M"?"Monthly":iv+"m"}</div>
                        <TVChart symbol={h.stock_ticker} interval={iv} height={chartHeight}/>
                      </div>
                    ))}
                  </div>
                  {(!layout || layout.showEma) && <EmaStrip emas={h} price={h.price}/>}
                </td>
              </tr>
            )}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
    <Pager page={curPage} totalPages={totalPages} onPage={setPage}/>
    </div>
  );
}

const HOLDING_SORT_KEYS = {
  rank: h=> h.rank||0,
  score: h=> h._score ?? -1,
  ticker: h=> h.stock_ticker,
  weight: h=> h.weight_pct,
  price: h=> h.price,
  mcap: h=> h.market_cap_musd,
  avgvol: h=> h.avg_volume,
  chg_1d: h=> h.chg_1d,
  chg_1w: h=> h.chg_1w,
  chg_1m: h=> h.chg_1m,
  chg_3m: h=> h.chg_3m,
  chg_6m: h=> h.chg_6m,
  rs: h=> h.rs_rating,
  from_hi: h=> h.pct_from_52w_high,
  vol: h=> h.volume_ratio,
  vold: h=> h.volatility_d??-1,
  adr: h=> h.adr_pct??-1,
  rating: h=> h.recommend_all??-1,
};

// ---------------------------------------------------------------------------
// Market Screener — every stock passing the universal filters, ranked and
// paginated (Google-style page bar at the bottom).
// ---------------------------------------------------------------------------
const SCREENER_SORT_KEYS = {
  score: s=> s._score ?? -1,
  rank_3m: s=> s.rank_3m,
  rank_6m: s=> s.rank_6m,
  ticker: s=> s.ticker,
  sector: s=> s.sector_name||"",
  price: s=> s.price,
  mcap: s=> s.market_cap_musd,
  avgvol: s=> s.avg_volume,
  chg_1d: s=> s.chg_1d,
  chg_1w: s=> s.chg_1w,
  chg_1m: s=> s.chg_1m,
  chg_3m: s=> s.chg_3m,
  chg_6m: s=> s.chg_6m,
  rs: s=> s.rs_rating,
  from_hi: s=> s.pct_from_52w_high,
  vol: s=> s.volume_ratio,
  vold: s=> s.volatility_d??-1,
  adr: s=> s.adr_pct??-1,
  rating: s=> s.recommend_all??-1,
};

function pageWindow(page, totalPages){
  // Google-style: first, last, and a window around the current page.
  const pages = new Set([1, totalPages]);
  for(let p=page-2; p<=page+2; p++) if(p>=1 && p<=totalPages) pages.add(p);
  const list = [...pages].sort((a,b)=>a-b);
  const out = [];
  let prev = 0;
  for(const p of list){
    if(p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}

function Pager({page, totalPages, onPage}) {
  if(totalPages <= 1) return null;
  return (
    <div className="pager">
      <span className={"pager-btn "+(page===1?"disabled":"")} onClick={()=>page>1 && onPage(page-1)}>‹ Prev</span>
      {pageWindow(page, totalPages).map((p,i)=> p==="…"
        ? <span key={"e"+i} className="pager-ellipsis">…</span>
        : <span key={p} className={"pager-btn "+(p===page?"active":"")} onClick={()=>onPage(p)}>{p}</span>
      )}
      <span className={"pager-btn "+(page===totalPages?"disabled":"")} onClick={()=>page<totalPages && onPage(page+1)}>Next ›</span>
    </div>
  );
}

const SCREENER_PAGE_SIZE = 10;
const DRILL_PAGE_SIZE = 25;

// ---------------------------------------------------------------------------
// Screener infographic dashboard — every widget below is computed from the
// screener dataset itself (the scored stocks array), no extra API calls.
// ---------------------------------------------------------------------------
// Per-industry aggregates over the scored universe — powers the rotation
// chart, the ranking bars and the "composite score > 50" dominance stats.
function screenerIndustries(stocks){
  const groups = {};
  stocks.forEach(s=>{
    const key = s.industry || "Other";
    (groups[key] = groups[key] || {industry:key, sector:s.sector_name||"Other", members:[]}).members.push(s);
  });
  return Object.values(groups).map(g=>{
    const m = g.members;
    return {
      industry: g.industry, sector: g.sector, count: m.length,
      over50: m.filter(x=>(x._score||0)>50).length,
      avgScore: avg(m.map(x=>x._score||0)),
      chg_1w: avg(m.map(x=>x.chg_1w||0)),
      chg_1m: avg(m.map(x=>x.chg_1m||0)),
      chg_3m: avg(m.map(x=>x.chg_3m||0)),
      rs: avg(m.map(x=> x.rs_rating==null ? 50 : x.rs_rating)),
      top: maxBy(m, x=>x._score||0),
    };
  }).sort((a,b)=> b.avgScore - a.avgScore);
}

function ScrInfo({title, hint, children, grow}) {
  return (
    <div className={"panel scr-info"+(grow?" scr-grow":"")}>
      <div className="panel-title"><span>{title}</span>{hint && <span className="hint">{hint}</span>}</div>
      {children}
    </div>
  );
}

function ScrCallout({label, name, sub, detail, color}) {
  return (
    <div className="scr-callout-wrap">
      <div className="stat-label">{label}</div>
      <div className="scr-callout" style={color?{color}:undefined}>{name}</div>
      {sub && <div className="scr-callout-sub">{sub}</div>}
      {detail && <div className="scr-callout-detail">{detail}</div>}
    </div>
  );
}

// Gamified top-performer podium: top 3 by composite momentum score.
function ScreenerPodium({stocks, wl}) {
  const top3 = [...stocks].sort((a,b)=>(b._score||0)-(a._score||0)).slice(0,3);
  if(top3.length<3) return <div className="empty">Need at least 3 stocks</div>;
  const order = [top3[1], top3[0], top3[2]];
  const ranks = [2, 1, 3];
  return (
    <div className="podium">
      {order.map((s,i)=>(
        <div key={s.ticker} className={"podium-col podium-"+ranks[i]}>
          <div className="podium-tick mono">{s.ticker}</div>
          <div className="podium-sub">{fmtPct1(s.chg_1m)} 1M · score {(s._score||0).toFixed(0)}</div>
          <div className="podium-block">
            <div className="podium-rank">{ranks[i]}</div>
            <WatchBtn wl={wl} ticker={s.ticker}/>
          </div>
        </div>
      ))}
    </div>
  );
}

function ScreenerDashboard({stocks, wl}) {
  if(!stocks || !stocks.length) return null;
  const n = stocks.length;
  const inds = screenerIndustries(stocks);

  // --- aggregate telemetry ---
  const scores = stocks.map(s=>s._score||0);
  const over50 = stocks.filter(s=>(s._score||0)>50);
  const adv1m = stocks.filter(s=>(s.chg_1m||0)>1).length;
  const dec1m = stocks.filter(s=>(s.chg_1m||0)<-1).length;
  const flat1m = n - adv1m - dec1m;
  const above10 = stocks.filter(s=>{ const e=extVsEma10(s); return e!=null && e>0; }).length;
  const avgAdr = avg(stocks.map(s=>s.adr_pct).filter(v=>v!=null));

  // --- industry rotation (RRG): x = avg RS rating, y = weekly momentum vs monthly pace ---
  const rrgRows = inds.filter(i=>i.count>=2).map(i=>({
    industry: i.industry, sector: i.sector,
    x: i.rs, y: i.chg_1w - i.chg_1m/4,
  }));
  const leading = rrgRows.filter(r=> r.x>50 && r.y>0);
  const leadingTop = maxBy(inds.filter(i=> i.rs>50 && (i.chg_1w - i.chg_1m/4)>0), i=>i.avgScore);
  const dominant = maxBy(inds, i=> i.over50*1000 + i.avgScore);
  const hottest = inds[0];
  const weakest = inds[inds.length-1];

  // --- ranking bars: industries by avg composite score ---
  const indBarRows = inds.slice(0, 10).map(i=>({
    label: i.industry.length>20 ? i.industry.slice(0,19)+"…" : i.industry,
    value: Math.round(i.avgScore*10)/10,
    color: i.avgScore>=50 ? "var(--green)" : "var(--amber)",
  }));

  // --- donuts: sector mix, 1M breadth, high-momentum clusters (score > 50) ---
  const secGroups = {};
  stocks.forEach(s=>{
    const k = s.sector_name || "Other";
    (secGroups[k] = secGroups[k] || {label:k, value:0, color:s.sector_color}).value++;
  });
  let secSegs = Object.values(secGroups).sort((a,b)=>b.value-a.value);
  if(secSegs.length>8){
    const rest = secSegs.splice(8);
    secSegs.push({label:"Other", value: rest.reduce((a,s)=>a+s.value,0), color:"#5f6470"});
  }
  secSegs.forEach((s,i)=>{ if(!s.color) s.color = SECTOR_PALETTE[i%SECTOR_PALETTE.length]; });

  const breadthSegs = [
    {label:"Advancing", value: adv1m, color:"var(--green)"},
    {label:"Flat", value: flat1m, color:"var(--amber)"},
    {label:"Declining", value: dec1m, color:"var(--red)"},
  ].filter(s=>s.value>0);

  const byOver50 = [...inds].sort((a,b)=> b.over50-a.over50 || b.avgScore-a.avgScore);
  let cluSegs = byOver50.filter(i=>i.over50>0).slice(0,6)
    .map((i,ix)=>({label: i.industry.length>18 ? i.industry.slice(0,17)+"…" : i.industry, value:i.over50, color:SECTOR_PALETTE[ix%SECTOR_PALETTE.length]}));
  const cluRest = over50.length - cluSegs.reduce((a,s)=>a+s.value,0);
  if(cluRest>0) cluSegs.push({label:"Other", value:cluRest, color:"#5f6470"});
  if(!cluSegs.length) cluSegs = [{label:"None > 50", value:1, color:"#5f6470"}];

  // --- return leaders ---
  const retBars = [...stocks].sort((a,b)=>(b.chg_1m??-1e9)-(a.chg_1m??-1e9)).slice(0,12)
    .map(s=>({label:s.ticker, value:Math.round((s.chg_1m||0)*100)/100, color:"var(--accent)"}));
  const lead1w = maxBy(stocks, s=>s.chg_1w??-1e9);
  const lead1m = maxBy(stocks, s=>s.chg_1m??-1e9);
  const lead3m = maxBy(stocks, s=>s.chg_3m??-1e9);
  const standouts = [...stocks].sort((a,b)=>(b._score||0)-(a._score||0)).slice(0,3);

  return (
    <div className="scr-dash">
      {/* Row 1 — aggregate telemetry */}
      <div className="grid-2">
        <ScrInfo title="Universe Telemetry" hint="computed from all screened stocks">
          <div className="scr-metrics">
            <div className="metric"><div className="stat-label">Stocks</div><div className="stat-value">{n}</div></div>
            <div className="metric"><div className="stat-label">Avg Score</div><div className="stat-value">{avg(scores).toFixed(1)}</div></div>
            <div className="metric"><div className="stat-label">Median 1M</div><div className={"stat-value "+pctClass(median(stocks.map(s=>s.chg_1m||0)))}>{fmtPct1(median(stocks.map(s=>s.chg_1m||0)))}</div></div>
            <div className="metric"><div className="stat-label">Avg ADR</div><div className="stat-value">{avgAdr.toFixed(2)}%</div></div>
            <div className="metric"><div className="stat-label">Above 10 EMA</div><div className="stat-value">{(above10/n*100).toFixed(0)}%</div></div>
            <div className="metric"><div className="stat-label">Score &gt; 50</div><div className="stat-value pos">{over50.length}</div></div>
          </div>
        </ScrInfo>
        <ScrInfo title="Momentum Pulse" hint="mean returns across the universe">
          <div className="scr-metrics">
            <div className="metric"><div className="stat-label">Avg 1W</div><div className={"stat-value "+pctClass(avg(stocks.map(s=>s.chg_1w||0)))}>{fmtPct1(avg(stocks.map(s=>s.chg_1w||0)))}</div></div>
            <div className="metric"><div className="stat-label">Avg 1M</div><div className={"stat-value "+pctClass(avg(stocks.map(s=>s.chg_1m||0)))}>{fmtPct1(avg(stocks.map(s=>s.chg_1m||0)))}</div></div>
            <div className="metric"><div className="stat-label">Avg 3M</div><div className={"stat-value "+pctClass(avg(stocks.map(s=>s.chg_3m||0)))}>{fmtPct1(avg(stocks.map(s=>s.chg_3m||0)))}</div></div>
            <div className="metric"><div className="stat-label">Advancing 1M</div><div className="stat-value pos">{adv1m}</div></div>
            <div className="metric"><div className="stat-label">Declining 1M</div><div className="stat-value neg">{dec1m}</div></div>
            <div className="metric"><div className="stat-label">Industries</div><div className="stat-value">{inds.length}</div></div>
          </div>
        </ScrInfo>
      </div>

      {/* Row 2 — RRG + stacked summary blocks */}
      <div className="scr-rrg-grid">
        <div className="panel">
          <div className="panel-title">
            <span>Industry Rotation — RRG</span>
            <span className="hint">x: avg RS rating (mid 50) · y: 1W momentum vs 1M pace · industries with ≥2 screened stocks · hover a dot</span>
          </div>
          <RRGDots rows={rrgRows} midX={50} midY={0} compact/>
        </div>
        <div className="scr-stack">
          <ScrInfo title="Leading Quadrant" grow>
            <ScrCallout label="RS > 50 & accelerating" name={leading.length+" industries"} color="var(--green)"
              sub={leadingTop ? "Strongest: "+leadingTop.industry+" — avg score "+leadingTop.avgScore.toFixed(0)+" · "+leadingTop.over50+"/"+leadingTop.count+" members score > 50" : "No industry is leading right now"}
              detail={rrgRows.length ? Math.round(leading.length/rrgRows.length*100)+"% of mapped industries are in the leading quadrant" : "Waiting for rotation data"}/>
          </ScrInfo>
          <ScrInfo title="Dominant Cluster" grow>
            <ScrCallout label="Most members scoring > 50" name={dominant ? dominant.industry : "—"} color="var(--accent)"
              sub={dominant ? dominant.over50+" of "+dominant.count+" members above 50 · avg score "+dominant.avgScore.toFixed(0)+" · top: "+(dominant.top?dominant.top.ticker:"—") : ""}
              detail={dominant ? dominant.sector+" · 1W "+fmtPct1(dominant.chg_1w)+" · 1M "+fmtPct1(dominant.chg_1m)+" · 3M "+fmtPct1(dominant.chg_3m) : ""}/>
          </ScrInfo>
          <ScrInfo title="Hottest Industry" grow>
            <ScrCallout label="Highest avg composite score" name={hottest ? hottest.industry : "—"} color="var(--amber)"
              sub={hottest ? "score "+hottest.avgScore.toFixed(0)+" · 1M "+fmtPct1(hottest.chg_1m)+" · 3M "+fmtPct1(hottest.chg_3m) : ""}
              detail={hottest ? "1W "+fmtPct1(hottest.chg_1w)+" · "+hottest.over50+"/"+hottest.count+" stocks above 50 · leader "+(hottest.top?hottest.top.ticker:"—") : ""}/>
          </ScrInfo>
        </div>
      </div>

      {/* Row 3 — industry ranking bars flanked by callouts */}
      <div className="scr-bar-grid">
        <ScrInfo title="Top Industry" grow>
          <ScrCallout label="By avg composite score" name={hottest ? hottest.industry : "—"} color="var(--green)"
            sub={hottest ? "score "+hottest.avgScore.toFixed(0)+" · "+hottest.count+" stocks · "+hottest.over50+" above 50 · "+hottest.sector : ""}
            detail={hottest ? "Returns: 1W "+fmtPct1(hottest.chg_1w)+" · 1M "+fmtPct1(hottest.chg_1m)+" · 3M "+fmtPct1(hottest.chg_3m)+"\nBest member: "+(hottest.top?hottest.top.ticker:"—")+" · score "+(hottest.top?(hottest.top._score||0).toFixed(0):"—") : ""}/>
        </ScrInfo>
        <div className="panel">
          <div className="panel-title">
            <span>Industry Ranking — Avg Momentum Score</span>
            <span className="hint">top 10 · green = avg score ≥ 50</span>
          </div>
          <HBars rows={indBarRows} fmt={v=>v.toFixed(1)} padL={150} refLine={{x:50, label:"50"}}/>
        </div>
        <ScrInfo title="Weakest Industry" grow>
          <ScrCallout label="Lowest avg composite score" name={weakest ? weakest.industry : "—"} color="var(--red)"
            sub={weakest ? "score "+weakest.avgScore.toFixed(0)+" · 1M "+fmtPct1(weakest.chg_1m)+" · "+weakest.sector : ""}
            detail={weakest ? "Returns: 1W "+fmtPct1(weakest.chg_1w)+" · 3M "+fmtPct1(weakest.chg_3m)+"\nBreadth: "+weakest.over50+"/"+weakest.count+" stocks above 50 · best member "+(weakest.top?weakest.top.ticker:"—") : ""}/>
        </ScrInfo>
      </div>

      {/* Row 4 — market breadth pies */}
      <div className="grid-3">
        <div className="panel">
          <div className="panel-title"><span>Sector Mix</span><span className="hint">screened stocks per sector</span></div>
          <Donut segments={secSegs} centerLabel={n}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>1M Market Breadth</span><span className="hint">±1% threshold</span></div>
          <Donut segments={breadthSegs} centerLabel={((adv1m/n)*100).toFixed(0)+"% up"}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>High-Momentum Clusters</span><span className="hint">members with score &gt; 50, by industry</span></div>
          <Donut segments={cluSegs} centerLabel={over50.length}/>
        </div>
      </div>

      {/* Rows 5+6 — leaders module + podium | return-leader bars + standouts */}
      <div className="scr-duo-grid">
        <div className="scr-stack">
          <ScrInfo title="Return Leaders" hint="top ticker per timeframe">
            {[["1W", lead1w, lead1w?lead1w.chg_1w:null],
              ["1M", lead1m, lead1m?lead1m.chg_1m:null],
              ["3M", lead3m, lead3m?lead3m.chg_3m:null]].map(([lbl, s, v])=>(
              <div key={lbl} className="scr-leader-row">
                <span className="lbl">{lbl}</span>
                <WatchBtn wl={wl} ticker={s?s.ticker:null}/>
                <span className="tk">{s?s.ticker:"—"}</span>
                <span className="text-dim" style={{fontSize:11}}>{s?(s.industry||s.sector_name||""):""}</span>
                <span className={"val "+(v!=null?pctClass(v):"")}>{fmtPct(v)}</span>
              </div>
            ))}
          </ScrInfo>
          <div className="panel scr-grow">
            <div className="panel-title"><span>Top Performers — Podium</span><span className="hint">by composite momentum score</span></div>
            <ScreenerPodium stocks={stocks} wl={wl}/>
          </div>
        </div>
        <div className="scr-stack">
          <div className="panel">
            <div className="panel-title"><span>Top Return Leaders — 1M</span><span className="hint">top 12 screened stocks</span></div>
            <HBars rows={retBars} fmt={v=>fmtPct1(v)} padL={70}/>
          </div>
          <ScrInfo title="Standout Tickers" hint="highest composite scores" grow>
            {standouts.map(s=>(
              <div key={s.ticker} className="scr-leader-row">
                <WatchBtn wl={wl} ticker={s.ticker}/>
                <span className="tk">{s.ticker}</span>
                <span className="text-dim" style={{fontSize:11}}>{s.industry||s.sector_name||""}</span>
                <span className={"val "+pctClass(s.chg_1m||0)}>{(s._score||0).toFixed(0)} · {fmtPct1(s.chg_1m)}</span>
              </div>
            ))}
          </ScrInfo>
        </div>
      </div>
    </div>
  );
}

function ScreenerView({strategy, wl}) {
  const [data, loading, , err] = useApi(apiUrl("/api/screener", strategy), [strategy]);
  const sort = useSortable((a,b)=> (b._score||0) - (a._score||0));
  const [page, setPage] = useState(1);
  const [chartsOn, setChartsOn] = useState(false);
  const [chartLayout, updateChartLayout] = useChartLayout();
  if(loading) return <div className="loading">Loading screener…</div>;
  if(err) return <div className="loading error">Error: {err}</div>;
  if(!data) return null;

  const scored = withMomentumScores(data.stocks);
  const stocks = sort.apply(scored, SCREENER_SORT_KEYS);
  const totalPages = Math.max(1, Math.ceil(stocks.length / SCREENER_PAGE_SIZE));
  const curPage = Math.min(page, totalPages);
  const pageRows = stocks.slice((curPage-1)*SCREENER_PAGE_SIZE, curPage*SCREENER_PAGE_SIZE);

  function goTo(p){ setPage(p); }
  function toggleSort(k){ sort.toggle(k); setPage(1); }
  const sortCtl = {...sort, toggle: toggleSort};

  return (
    <div>
      <h1 className="page-title">Market Screener</h1>
      <div className="filter-pills">
        <span className="filter-pill">Mkt cap ≥ $500M</span>
        <span className="filter-pill">Avg vol (30D) &gt; 1M</span>
        <span className="filter-pill">ADR ≥ 2%</span>
        <span className="filter-pill">{data.count} stocks</span>
      </div>
      <ScreenerDashboard stocks={scored} wl={wl}/>
      <div className="panel">
        <div className="panel-title">
          <span>All Stocks — Rankings</span>
          <span className="hint">Click a column heading to sort descending · click again to restore</span>
        </div>
        <div className="toggle-row" style={{alignItems:"center", justifyContent:"flex-end"}}>
          <Switch on={chartsOn} onChange={setChartsOn} label="Charts"
                  title="Show TradingView charts for every stock on this page"/>
        </div>
        {chartsOn && <ChartLayoutSettings layout={chartLayout} onChange={updateChartLayout}/>}
        {chartsOn && <StockChartsGrid stocks={pageRows} layout={chartLayout} renderAction={s=><WatchBtn wl={wl} ticker={s.ticker}/>}/>}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th title="Watchlist">✓</th>
                <SortTh label="3M Rank" k="rank_3m" sort={sortCtl} title="Rank by 3-month return across all screened stocks"/>
                <SortTh label="6M Rank" k="rank_6m" sort={sortCtl} title="Rank by 6-month return across all screened stocks"/>
                <SortTh label="Ticker" k="ticker" sort={sortCtl}/>
                <SortTh label="Sector" k="sector" sort={sortCtl}/>
                <SortTh label="Price" k="price" sort={sortCtl}/>
                <SortTh label="Mkt Cap" k="mcap" sort={sortCtl}/>
                <SortTh label="Avg Vol" k="avgvol" sort={sortCtl}/>
                <SortTh label="Score" k="score" sort={sortCtl} title="Relative Strength score: percentile rank (0-100) of the performance composite (15% 1W / 50% 1M / 35% 3M) within the stocks passing the screener eligibility filters; higher = stronger relative performance"/>
                <SortTh label="1D" k="chg_1d" sort={sortCtl}/>
                <SortTh label="1W" k="chg_1w" sort={sortCtl}/>
                <SortTh label="1M" k="chg_1m" sort={sortCtl}/>
                <SortTh label="3M" k="chg_3m" sort={sortCtl}/>
                <SortTh label="6M" k="chg_6m" sort={sortCtl}/>
                <SortTh label="RS" k="rs" sort={sortCtl}/>
                <SortTh label="% fr Hi" k="from_hi" sort={sortCtl}/>
                <SortTh label="Vol x" k="vol" sort={sortCtl}/>
                <SortTh label="Vol.D" k="vold" sort={sortCtl} title="TradingView daily volatility"/>
                <SortTh label="ADR" k="adr" sort={sortCtl} title="Average daily range %"/>
                <SortTh label="Rating" k="rating" sort={sortCtl} title="TradingView analyst rating (0-1)"/>
              </tr>
            </thead>
            <tbody>
              {pageRows.map(s=> (
                <tr key={s.ticker}>
                  <td className="watch-cell"><WatchBtn wl={wl} ticker={s.ticker}/></td>
                  <td className="mono fw-700">{s.rank_3m ?? "—"}</td>
                  <td className="mono fw-700">{s.rank_6m ?? "—"}</td>
                  <td className="mono fw-700">{s.ticker}</td>
                  <td>{s.sector_color && <span className="dot" style={{background:s.sector_color}}></span>} {s.sector_name || "—"}</td>
                  <td>${(s.price||0).toFixed(2)}</td>
                  <td>{fmtCap(s.market_cap_musd)}</td>
                  <td>{fmtVol(s.avg_volume)}</td>
                  <td><div className="score-cell"><span>{(s._score||0).toFixed(0)}</span><ScoreBar value={s._score||0}/></div></td>
                  <td className={pctClass(s.chg_1d)}>{fmtPct(s.chg_1d)}</td>
                  <td className={pctClass(s.chg_1w)}>{fmtPct(s.chg_1w)}</td>
                  <td className={pctClass(s.chg_1m)}>{fmtPct(s.chg_1m)}</td>
                  <td className={pctClass(s.chg_3m)}>{fmtPct(s.chg_3m)}</td>
                  <td className={pctClass(s.chg_6m)}>{s.chg_6m==null?"—":fmtPct(s.chg_6m)}</td>
                  <td>{(s.rs_rating||0).toFixed(0)}</td>
                  <td className="neg">{(s.pct_from_52w_high||0).toFixed(1)}%</td>
                  <td>{(s.volume_ratio||0).toFixed(2)}</td>
                  <td>{s.volatility_d==null?"—":s.volatility_d.toFixed(2)+"%"}</td>
                  <td>{s.adr_pct==null?"—":s.adr_pct.toFixed(2)+"%"}</td>
                  <td className={ratingClass(s.recommend_all)}>{fmtRating(s.recommend_all)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={curPage} totalPages={totalPages} onPage={goTo}/>
      </div>
    </div>
  );
}

function SectorDetail({sectorId, onBack, onSelectIndustry, strategy, wl}) {
  const [detail, loading, , err] = useApi(apiUrl("/api/sectors/"+sectorId, strategy), [sectorId, strategy]);
  const [stocks] = useApi(apiUrl("/api/sectors/"+sectorId+"/stocks", strategy), [sectorId, strategy]);
  const [industries] = useApi(apiUrl("/api/sectors/"+sectorId+"/industries", strategy), [sectorId, strategy]);
  const [filter, setFilter] = useState("all");
  const [section, setSection] = useState("constituents");
  const [chartsOn, setChartsOn] = useState(false);
  const [chartLayout, updateChartLayout] = useChartLayout();

  // Sector's own chart: proxy ETF (or sector ticker) on TradingView with the
  // 5/10/20/50/200 EMAs in a blue gradient, numeric readout below.
  const etf = detail ? (detail.proxy_etf || detail.ticker) : null;
  const [emas, setEmas] = useState(null);
  useEffect(()=>{
    setEmas(null);
    if(!etf) return;
    fetch(API+"/api/etf-emas?symbol="+encodeURIComponent(etf))
      .then(r=> r.ok ? r.json() : null)
      .then(setEmas)
      .catch(()=>setEmas(null));
  },[etf]);

  // Charts render as per-row panels inside the holdings table, so they always
  // follow the table's current sort and filter.
  function toggleCharts(on){
    setChartsOn(on);
  }

  if(loading) return <div className="loading">Loading sector…</div>;
  if(err) return <div className="loading error">Error: {err}</div>;
  if(!detail) return null;

  const snap = detail.latest_snapshot || {};
  const hist = detail.history || [];
  const primary = detail.primary_etf;
  const holdings = detail.holdings_by_etf[primary]?.holdings || [];

  const priceSeries = hist.map(h=>({date:h.dt, value:h.price}));
  const breadthSeries = hist.map(h=>({date:h.dt, value:h.breadth_pct_above_50ma}));
  const scoreSeries = hist.map(h=>({date:h.dt, value:h.score}));

  const radarAxes = [
    {label:"Breadth", v: snap.breadth_pct_above_50ma||0},
    {label:"Avg RS", v: snap.avg_rs_rating||0},
    {label:"New Highs", v: snap.pct_new_highs||0},
    {label:"Health", v: detail.rotation_health_score||0},
    {label:"Low Conc", v: Math.max(0, 100-(detail.concentration_index||0))},
  ];

  const rrgPaths = detail.etfs.map((e,ei)=>{
    const pts = hist.slice(-12).map((h,i)=> ({
      x: 95 + (h.avg_rs_rating - 50)*0.6 + (ei-1)*2,
      y: (h.score - (hist[i-1]?.score||h.score))*3,
      dt: h.dt
    }));
    return {etf: e.ticker, color: detail.color, points: pts};
  });

  return (
    <div className="page">
      <div className="back" onClick={onBack}><Icon.back/> Back to Markets</div>

      <div className="sector-header" style={{borderLeftColor: detail.color}}>
        <div>
          <div className="flex gap-3 ai-center">
            <span className="dot-lg" style={{background:detail.color}}></span>
            <h1 className="page-title">{detail.name}</h1>
            <span className="mono text-faint">{detail.ticker}</span>
          </div>
          <div className="page-subtitle">{detail.sub} · {detail.tags}</div>
          {detail.strategy_info && (
            <div className="page-subtitle" style={{marginTop:4}}>
              <span style={{color:"var(--accent)", fontWeight:700}}>CCI-based composite</span>
              {" "}· Performance {detail.strategy_info.composite_base !== null && detail.strategy_info.composite_base !== undefined ? detail.strategy_info.composite_base.toFixed(1) : "—"}
              {" "}+ CCI {detail.strategy_info.cci_factor} (50/50) → <span className="mono">{detail.strategy_info.composite_score !== null && detail.strategy_info.composite_score !== undefined ? detail.strategy_info.composite_score.toFixed(1) : "—"}</span>
            </div>
          )}
        </div>
        <div className="sector-header-metrics">
          <div className="metric">
            <div className="stat-label">Score</div>
            <div className="stat-xl">{snap.score!==undefined ? snap.score.toFixed(0) : "—"}</div>
          </div>
          <div className="metric">
            <div className="stat-label">State</div>
            <div className={"state-badge "+stateClass(snap.state)}>{stateLabel(snap.state)}</div>
          </div>
          <div className="metric">
            <div className="stat-label">1M</div>
            <div className={"stat-xl "+pctClass(snap.chg_1m)}>{fmtPct(snap.chg_1m)}</div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>{etf} — Sector Chart</span>
          <span className="hint">EMA 5 / 10 / 20 / 50 / 200 · blue gradient, fastest lightest → slowest darkest{detail.proxy_etf ? "" : " · no mapped ETF — using sector slug"}</span>
        </div>
        <TVChart symbol={etf} interval="D" height={420}/>
        <EmaStrip emas={emas} price={emas ? emas.price : null}/>
      </div>

      <div className="tabs">
        {["overview","constituents","industries","rotation"].map(tab=> (
          <div key={tab} className={"tab "+(section===tab?"active":"")} onClick={()=>setSection(tab)}>
            {tab[0].toUpperCase()+tab.slice(1)}
          </div>
        ))}
      </div>

      {section==="overview" && (
        <div className="sections">
          <div className="panel">
            <div className="panel-title">Key Metrics</div>
            <div className="grid-4">
              <div className="metric-card"><div className="stat-label">Price</div><div className="stat-value">{fmtPrice(snap.price)}</div></div>
              <div className="metric-card"><div className="stat-label">Breadth &gt;50MA</div><div className="stat-value">{(snap.breadth_pct_above_50ma||0).toFixed(0)}%</div></div>
              <div className="metric-card"><div className="stat-label">Avg RS</div><div className="stat-value">{(snap.avg_rs_rating||0).toFixed(0)}</div></div>
              <div className="metric-card"><div className="stat-label">New Highs</div><div className="stat-value">{(snap.pct_new_highs||0).toFixed(0)}%</div></div>
              <div className="metric-card"><div className="stat-label">vs SPY (1M)</div><div className={"stat-value "+pctClass(snap.rs_vs_spy_1m)}>{fmtPct(snap.rs_vs_spy_1m)}</div></div>
              <div className="metric-card"><div className="stat-label">Vol Ratio</div><div className="stat-value">{(snap.avg_volume_ratio||0).toFixed(2)}x</div></div>
              <div className="metric-card"><div className="stat-label">Concentration</div><div className="stat-value">{(detail.concentration_index||0).toFixed(1)}</div></div>
              <div className="metric-card"><div className="stat-label">Rotation Health</div><div className="stat-value">{(detail.rotation_health_score||0).toFixed(0)}</div></div>
            </div>
          </div>

          <div className="grid-2">
            <div className="panel">
              <div className="panel-title">Score Trend</div>
              <AreaChart series={[{values: scoreSeries.map(d=>d.value), color: detail.color, width:2.5}]} colors={[detail.color]} yDomain={[0,100]}/>
            </div>
            <div className="panel">
              <div className="panel-title">Breadth & RS</div>
              <AreaChart series={[
                {values: breadthSeries.map(d=>d.value), color: detail.color, width:2.5},
                {values: hist.map(h=>h.avg_rs_rating), color:"var(--amber)", width:1.5, dasharray:"4,3"}
              ]} colors={[detail.color, "var(--amber)"]} yDomain={[0,100]}/>
              <div className="legend">
                <span><span className="legend-dot" style={{background:detail.color}}></span>Breadth</span>
                <span><span className="legend-dot" style={{background:"var(--amber)"}}></span>Avg RS</span>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">Sector Lifecycle Fingerprint</div>
            <div className="flex jc-center">
              <RadarChart axes={radarAxes} color={detail.color}/>
            </div>
          </div>
        </div>
      )}

      {section==="constituents" && (
        <div className="sections">
          <div className="panel">
            <div className="panel-title">
              <span>Constituents — {stocks ? stocks.length : "…"} stocks</span>
              <span className="hint">Every stock in this sector passing the scanner filters · ranked by score · click a column to sort</span>
            </div>
            <div className="toggle-row" style={{alignItems:"center"}}>
              {["all","leader","laggard","neutral"].map(f=> (
                <div key={f} className={"toggle toggle-"+f+(filter===f?" active":"")} onClick={()=>setFilter(f)}>{f[0].toUpperCase()+f.slice(1)}</div>
              ))}
              <span className="toggle-spacer"/>
              <Switch on={chartsOn} onChange={toggleCharts} label="Charts"
                      title="Show charts under each row (5/10/20/50/200 EMA)"/>
            </div>
            {chartsOn && <ChartLayoutSettings layout={chartLayout} onChange={updateChartLayout}/>}
            {stocks
              ? <HoldingsTable holdings={stocks} filter={filter} chartsOn={chartsOn} layout={chartLayout} wl={wl}/>
              : <div className="loading">Loading constituents…</div>}
          </div>
          <div className="grid-2">
            <div className="panel">
              <div className="panel-title">Leader / Laggard Contribution</div>
              <ContributionBars holdings={holdings}/>
            </div>
            <div className="panel">
              <div className="panel-title">Volume Expansion</div>
              <VolumeExpansionBars holdings={holdings}/>
            </div>
          </div>
        </div>
      )}

      {section==="industries" && (
        <div className="sections">
          {industries && industries.length>0
            ? <IndustryTable industries={industries} onSelectIndustry={(n)=>onSelectIndustry(n, sectorId)}
                title={"Industries within "+detail.name} hint="Ranked by industry leadership score (>=3 stocks · >25 stocks: 65% perf + 35% CCI, else performance only) · click an industry for its analysis page"/>
            : <div className="panel"><div className="empty">No industry breakdown — sync live data to populate TradingView industries</div></div>}
        </div>
      )}

      {section==="rotation" && (
        <div className="sections">
          <div className="grid-2">
            <div className="panel">
              <div className="panel-title">
                <span>Relative Rotation Graph</span>
                <span className="hint">RRG trail over the last 8 snapshots · x: RS vs 50 baseline · y: score momentum · clockwise rotation = healthy cycle (Improving → Leading → Weakening → Lagging)</span>
              </div>
              <RRGChart paths={rrgPaths}/>
            </div>
            <div className="panel">
              <div className="panel-title">Price History</div>
              <AreaChart series={[{values: priceSeries.map(d=>d.value), color: detail.color, width:2}]} colors={[detail.color]}/>
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">New Highs % (last 20 snapshots)</div>
            <div className="new-highs-bars">
              {hist.slice(-20).map((h,i)=> (
                <div key={i} className="nh-bar" style={{height: Math.max(4, h.pct_new_highs)+"%", background: detail.color}} title={h.dt+": "+h.pct_new_highs.toFixed(1)+"%"}></div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ETF Hub — cross-ETF screening workspace
// ---------------------------------------------------------------------------
const ETF_CATEGORIES = ["All", "Broad", "Sector", "Thematic", "Industry", "Commodity/Macro"];
const ETF_CAT_COLORS = {
  "Broad": "var(--accent)", "Sector": "var(--green)", "Thematic": "var(--purple)",
  "Industry": "var(--amber)", "Commodity/Macro": "var(--red)",
};
const ETF_QUAD_COLORS = {
  leading: "var(--green)", weakening: "var(--amber)",
  lagging: "var(--red)", improving: "var(--accent)",
};

// Multi-factor ranking boards (new scoring contract; hidden when the fields
// are absent from the /api/etf-hub payload).
const ETF_BOARDS = [
  {id:"leadership", label:"Leadership", rankKey:"rank_leadership"},
  {id:"opportunity", label:"Opportunity", rankKey:"rank_opportunity"},
  {id:"rotation", label:"Rotation", rankKey:"rank_rotation"},
  {id:"risk", label:"Risk", rankKey:"rank_risk"},
];
const ETF_STATE_COLORS = {
  Leading: "var(--green)", Emerging: "var(--accent)", Recovering: "var(--purple)",
  Extended: "var(--amber)", Fading: "#ff7a59", Lagging: "var(--red)",
  Neutral: "var(--text-dim)",
};
function etfStateBadge(state){
  if(!state) return null;
  return <span className="tag" style={{color: ETF_STATE_COLORS[state] || "var(--text-dim)"}}>{state}</span>;
}

function etfTagBadge(t){
  const map = {
    best_1d: ["Best 1D", "tag-green"], best_1w: ["Best 1W", "tag-green"], best_1m: ["Best 1M", "tag-green"],
    worst_1d: ["Worst 1D", "tag-red"], worst_1w: ["Worst 1W", "tag-red"], worst_1m: ["Worst 1M", "tag-red"],
    high_adr: ["High ADR", "tag-amber"], high_vol_momentum: ["Vol ↑", "tag-purple"],
  };
  const m = map[t];
  return m ? <span key={t} className={"tag "+m[1]}>{m[0]}</span> : null;
}

function fmtAum(v){
  if(v===null||v===undefined||isNaN(v)) return "—";
  return v>=1e9 ? "$"+(v/1e9).toFixed(1)+"B" : "$"+(v/1e6).toFixed(0)+"M";
}

// CCI-34 zone badge: bullish > 100, neutral 0-100, bearish < 0.
function cciZoneBadge(zone){
  const map = {bullish:["Bullish","tag-green"], neutral:["Neutral","tag-amber"], bearish:["Bearish","tag-red"]};
  const m = map[zone];
  if(!m) return <span className="tag">—</span>;
  return <span className={"tag "+m[1]}><span className="risk-dot" style={{width:7,height:7,borderRadius:"50%",background:"currentColor",marginRight:5}}></span>{m[0]}</span>;
}

// Composite score color: green >= 67, amber >= 34, red below.
function scoreTagClass(s){
  return s>=67 ? "tag-green" : s>=34 ? "tag-amber" : "tag-red";
}

// Tiny inline 30-day price sparkline from a closes array.
function Sparkline({data, width=90, height=22}){
  if(!data || data.length<2) return <span className="text-faint">—</span>;
  const mn = Math.min(...data), mx = Math.max(...data), span = (mx-mn)||1;
  const pts = data.map((v,i)=> ((i/(data.length-1))*width).toFixed(1)+","+(height-2-((v-mn)/span)*(height-4)).toFixed(1)).join(" ");
  const up = data[data.length-1] >= data[0];
  return (
    <svg width={width} height={height} style={{display:"block"}}>
      <polyline className="draw" pathLength="1" points={pts} fill="none" stroke={up?"var(--green)":"var(--red)"} strokeWidth="1.5"/>
    </svg>
  );
}

// Alpha contribution waterfall (HBars): top 1M contributors, "other" bucket, net.
function EtfWaterfall({waterfall}){
  if(!waterfall) return <div className="empty">No waterfall data</div>;
  const rows = [
    ...waterfall.positive.map(c=>({label:c.ticker, value:c.contribution, color:"var(--green)"})),
    ...(waterfall.other!==0 ? [{label:"OTHER", value:waterfall.other, color:"var(--text-dim)"}] : []),
    ...waterfall.negative.map(c=>({label:c.ticker, value:c.contribution, color:"var(--red)"})),
  ];
  return (
    <div>
      <HBars rows={rows} fmt={v=>(v>=0?"+":"")+v.toFixed(2)+" pp"}/>
      <div className="flex gap-2 ai-center" style={{marginTop:8}}>
        <span className="stat-label">Net 1M contribution</span>
        <span className={"stat-value "+pctClass(waterfall.net)}>{waterfall.net>=0?"+":""}{waterfall.net.toFixed(2)} pp</span>
      </div>
    </div>
  );
}

// Drill-down: constituent table + sparklines for the selected ETF.
function EtfDrilldown({ticker}){
  const [data, loading] = useApi("/api/etf-hub/"+ticker+"/constituents", [ticker]);
  if(loading) return <div className="loading">Loading {ticker} constituents…</div>;
  if(!data) return <div className="empty">No constituent data for {ticker}</div>;
  if(!data.stocks || data.stocks.length===0) return <div className="empty">{data.note || "No mapped constituents for "+ticker}</div>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr><th>Ticker</th><th>Weight %</th><th>Price</th><th>1D</th><th>1M</th><th>20D ADR %</th><th>% fr 52w Hi</th><th>CCI-34</th><th>Zone</th><th>30D</th></tr>
        </thead>
        <tbody>
          {data.stocks.map(s=>(
            <tr key={s.ticker}>
              <td><span className="mono fw-700">{s.ticker}</span></td>
              <td>{s.weight_pct.toFixed(2)}%</td>
              <td>{fmtPrice(s.price)}</td>
              <td className={pctClass(s.chg_1d)}>{fmtPct(s.chg_1d)}</td>
              <td className={pctClass(s.chg_1m)}>{fmtPct(s.chg_1m)}</td>
              <td>{s.adr_pct!==null&&s.adr_pct!==undefined ? s.adr_pct.toFixed(1)+"%" : "—"}</td>
              <td className="neg">{s.pct_from_52w_high!==null&&s.pct_from_52w_high!==undefined ? s.pct_from_52w_high.toFixed(1)+"%" : "—"}</td>
              <td className="mono">{s.cci!==null&&s.cci!==undefined ? s.cci : "—"}</td>
              <td>{cciZoneBadge(s.cci_zone)}</td>
              <td><Sparkline data={s.spark}/></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const ETF_FACTOR_LABELS = {
  rs:"Relative Strength", momentum:"Momentum", breadth:"Breadth", trend:"Trend", volume:"Volume",
  consistency:"Consistency", risk:"Risk", opportunity:"Opportunity",
};
function fmtFactorInput(v){
  if(v===null||v===undefined) return "—";
  if(typeof v==="boolean") return v?"yes":"no";
  if(typeof v==="number"){
    const a = Math.abs(v);
    return a>=100 ? v.toFixed(0) : a>=10 ? v.toFixed(1) : v.toFixed(2);
  }
  return String(v);
}

// Score Breakdown panel for the drill-down: state/type/warning, the four
// board scores with ranks, per-factor bars (score, weight, percentile) with
// raw inputs, and the explanation bullets. Renders nothing when the backend
// has no breakdown for the ticker (404) so the rest of the drill-down is
// unaffected.
function EtfScoreBreakdown({ticker}){
  const [data, loading, , error] = useApi("/api/etf-hub/"+ticker+"/breakdown", [ticker]);
  if(loading || error || !data) return null;
  const scores = data.scores || {}, ranks = data.ranks || {}, factors = data.factors || {};
  const boardChips = ETF_BOARDS.map(b=>({
    label: b.label, score: scores[b.id], rank: ranks[b.id],
  })).filter(c=>c.score!==null&&c.score!==undefined);
  const factorKeys = ["rs","momentum","breadth","trend","volume","consistency","risk","opportunity"]
    .filter(k=>factors[k]);
  return (
    <div className="panel" style={{marginBottom:16}}>
      <div className="panel-title">
        <span>Score Breakdown — {data.ticker || ticker}</span>
        <span className="hint">multi-factor percentile scores (0–100) with weights and universe percentiles</span>
      </div>
      <div className="flex gap-2 ai-center" style={{flexWrap:"wrap", marginBottom:10}}>
        {etfStateBadge(data.state)}
        {data.etf_type && <span className="tag tag-blue">{data.etf_type}</span>}
        {data.risk_warning && <span className="tag tag-red" title={data.risk_warning}>⚠ {data.risk_warning}</span>}
      </div>
      {boardChips.length>0 && (
        <div className="flex gap-3 ai-center" style={{flexWrap:"wrap", marginBottom:12}}>
          {boardChips.map(c=>(
            <div key={c.label} className="flex gap-2 ai-center">
              <span className="stat-label">{c.label}</span>
              <span className={"tag "+scoreTagClass(c.score)}>{c.score.toFixed(1)}</span>
              {c.rank!==null&&c.rank!==undefined && <span className="hint">#{c.rank}</span>}
            </div>
          ))}
        </div>
      )}
      {factorKeys.map(k=>{
        const f = factors[k];
        const sc = f.score, pct = f.percentile, w = f.weight;
        const inputs = f.inputs || {};
        const inputKeys = Object.keys(inputs);
        return (
          <div key={k} style={{marginBottom:10}}>
            <div className="flex gap-2 ai-center">
              <span className="stat-label" style={{minWidth:110}}>{ETF_FACTOR_LABELS[k]||k}</span>
              <span className="bar-meter" style={{flex:1, maxWidth:420}}>
                <span className="bar-meter-track" style={{flex:1}}>
                  <span className="bar-meter-fill" style={{width:Math.max(0,Math.min(100,sc||0))+"%", background:"var(--accent)"}}></span>
                </span>
              </span>
              <span className="mono" style={{minWidth:38, textAlign:"right"}}>{sc!==null&&sc!==undefined ? sc.toFixed(1) : "—"}</span>
              {w!==null&&w!==undefined && <span className="hint">w {(w*100).toFixed(0)}%</span>}
              {pct!==null&&pct!==undefined && <span className="hint">{pct.toFixed(0)}th pct</span>}
            </div>
            {inputKeys.length>0 && (
              <div className="hint" style={{marginLeft:118, marginTop:2}}>
                {inputKeys.map(ik=>ik.replace(/_/g," ")+" "+fmtFactorInput(inputs[ik])).join(" · ")}
              </div>
            )}
          </div>
        );
      })}
      {data.explanation && data.explanation.length>0 && (
        <ul style={{margin:"10px 0 0", paddingLeft:18}}>
          {data.explanation.map((x,i)=><li key={i} className="hint" style={{marginBottom:3}}>{x}</li>)}
        </ul>
      )}
    </div>
  );
}

// Ranked editorial list row: rank number, category dot, ticker, name, value.
function EtfRankList({rows, onSelect, right}){
  return (
    <div className="etf-rank-list">
      {rows.map((e,i)=>(
        <div key={e.ticker} className="etf-rank-row hover-row" onClick={()=>onSelect && onSelect(e.ticker)}>
          <span className="etf-rank-num mono">{String(i+1).padStart(2,"0")}</span>
          <span className="dot" style={{background:ETF_CAT_COLORS[e.category]}}></span>
          <span className="mono fw-700">{e.ticker}</span>
          <span className="etf-rank-name">{e.name}</span>
          <span className="etf-rank-val">{right(e)}</span>
        </div>
      ))}
      {rows.length===0 && <div className="empty">No data yet</div>}
    </div>
  );
}

// Radial progress ring for the breadth stat (infographic-style SVG circle).
function EtfBreadthRing({pct, size=96}){
  const r = 34, c = 2*Math.PI*r;
  const p = pct===null||pct===undefined ? 0 : Math.max(0, Math.min(100, pct));
  const col = pct===null||pct===undefined ? "var(--text-faint)" : pct>=50 ? "var(--green)" : "var(--red)";
  return (
    <div className="etf-ring" style={{width:size, height:size}}>
      <svg width={size} height={size} viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} fill="none" stroke="var(--panel-2)" strokeWidth="9"/>
        <circle cx="48" cy="48" r={r} fill="none" stroke={col} strokeWidth="9"
          strokeDasharray={c} strokeDashoffset={c*(1-p/100)}
          transform="rotate(-90 48 48)"/>
      </svg>
      <div className="etf-ring-center" style={{color:col}}>{pct===null||pct===undefined?"—":pct.toFixed(0)+"%"}</div>
    </div>
  );
}

function ETFHubView(){
  const [data, loading] = useApi("/api/etf-hub", []);
  const [cat, setCat] = useState("All");
  const [selected, setSelected] = useState(null);
  const [board, setBoard] = useState("leadership");
  const [chartsOn, setChartsOn] = useState(false);
  const [chartLayout, updateChartLayout] = useChartLayout();
  const sort = useSortable((a,b)=>{
    // Default order follows the active board's rank (rank 1 first) when the
    // multi-factor fields are present; otherwise the legacy composite score.
    if(hasScores){
      const k = activeBoard.rankKey;
      return (a[k]??Infinity) - (b[k]??Infinity);
    }
    return (b.score??-Infinity) - (a.score??-Infinity);
  });
  // The master table can be wider than the viewport (horizontal scroll); the
  // per-row chart area is pinned to the visible container width instead.
  const [scrollRef, scrollW] = useContainerWidth();
  const chartWidth = scrollW ? Math.max(280, scrollW - 26) : null;

  const etfsAll = data?.etfs || [];
  // Multi-factor contract detection: hide the new UI when the fields are absent.
  const hasScores = etfsAll.some(e=>e.leadership_score!==null&&e.leadership_score!==undefined);
  const hasStates = etfsAll.some(e=>!!e.state);
  const activeBoard = ETF_BOARDS.find(b=>b.id===board) || ETF_BOARDS[0];
  const rankHl = {background:"rgba(88,166,255,0.10)"};
  const etfs = cat==="All" ? etfsAll : etfsAll.filter(e=>e.category===cat);
  // Default drill-down selection: top 1M performer among ETFs that have
  // mapped local constituents (so the waterfall/drill-down show data);
  // fall back to the overall top performer.
  const byPerf1m = [...etfsAll].sort((a,b)=>(b.chg_1m??-Infinity)-(a.chg_1m??-Infinity));
  const defaultTicker = (byPerf1m.find(e=>e.pct_above_50d!=null) || byPerf1m[0] || {}).ticker || null;
  const selTicker = selected || defaultTicker;
  const selEtf = etfsAll.find(e=>e.ticker===selTicker);
  const waterfallUrl = selTicker ? "/api/etf-hub/"+selTicker+"/constituents" : null;
  const [wfData, wfLoading] = useApi(waterfallUrl || "/api/etf-hub", [selTicker]);

  if(loading) return <div className="loading">Loading ETF hub…</div>;
  if(!data) return <div className="empty">ETF hub data unavailable</div>;

  const rrgPts = etfs.filter(e=>e.rs_ratio!==null && e.rs_momentum!==null).map(e=>({
    x: e.rs_ratio, y: e.rs_momentum, label: e.ticker, color: ETF_QUAD_COLORS[e.quadrant]||"var(--text-dim)",
  }));
  const bubblePts = etfs.filter(e=>e.chg_1m!==null && e.adr_pct!==null).map(e=>{
    const rv = e.rel_vol||0;
    return {
      x: e.chg_1m, y: e.adr_pct, label: e.ticker, r: Math.sqrt(Math.max(e.aum||0, 0)/1e9)/4,
      color: rv>=1.5 ? "var(--amber)" : rv>=0.8 ? "var(--accent)" : "var(--text-dim)",
    };
  });
  const catSegs = Object.keys(ETF_CAT_COLORS).map(c=>({
    label: c, color: ETF_CAT_COLORS[c],
    value: etfs.filter(e=>e.category===c).reduce((a,e)=>a+(e.aum||0), 0)/1e9,
  })).filter(s=>s.value>0).map(s=>({...s, value: Math.round(s.value)}));
  const mapped = etfs.filter(e=>e.pct_above_50d!==null && e.pct_above_50d!==undefined);
  const avgBreadth50 = mapped.length ? avg(mapped.map(e=>e.pct_above_50d)) : null;

  const topScores = [...etfsAll].filter(e=>e.score!==null&&e.score!==undefined)
    .sort((a,b)=>b.score-a.score).slice(0,8);
  // "Charts" toggles TradingView charts under each row of the master table
  // (same pattern as sector constituents) — every other graph stays visible.
  const chartIntervals = chartsOn ? layoutIntervals(chartLayout) : [];
  const chartHeight = CHART_SIZE_PX[chartLayout.size] || 360;
  const zoneCounts = {bullish:0, neutral:0, bearish:0, unknown:0};
  etfsAll.forEach(e=>{ zoneCounts[e.cci_zone||"unknown"]++; });

  const keyFns = {
    ticker: e=> e.ticker,
    category: e=> e.category,
    score: e=> e.score??-Infinity,
    cci: e=> e.cci??-Infinity,
    price: e=> e.price??-Infinity,
    chg_1d: e=> e.chg_1d??-Infinity, chg_1w: e=> e.chg_1w??-Infinity, chg_1m: e=> e.chg_1m??-Infinity,
    chg_3m: e=> e.chg_3m??-Infinity, chg_6m: e=> e.chg_6m??-Infinity,
    chg_ytd: e=> e.chg_ytd??-Infinity, chg_1y: e=> e.chg_1y??-Infinity,
    adr: e=> e.adr_pct??-Infinity, rel_vol: e=> e.rel_vol??-Infinity,
    aum: e=> e.aum??-Infinity, from_hi: e=> e.pct_from_52w_high??-Infinity,
    breadth: e=> e.pct_above_50d??-Infinity,
    state: e=> e.state||"",
    // Negated so the table's descending sort yields rank 1 first.
    rank_leadership: e=> -(e.rank_leadership??9999),
    rank_opportunity: e=> -(e.rank_opportunity??9999),
    rank_rotation: e=> -(e.rank_rotation??9999),
    rank_risk: e=> -(e.rank_risk??9999),
  };
  const sorted = sort.apply(etfs, keyFns);
  const pctCell = (v)=> <td className={pctClass(v)}>{fmtPct1(v)}</td>;

  // Editorial derived lists (respect the active category filter).
  const spy = etfsAll.find(e=>e.ticker==="SPY");
  const has1m = e=> e.chg_1m!==null && e.chg_1m!==undefined;
  const perf1m = [...etfs].filter(has1m).sort((a,b)=>b.chg_1m-a.chg_1m);
  const topAdr = [...etfs].filter(e=>e.adr_pct!==null&&e.adr_pct!==undefined)
    .sort((a,b)=>b.adr_pct-a.adr_pct).slice(0,8);
  const cciBull = [...etfs].filter(e=>e.cci_zone==="bullish")
    .sort((a,b)=>(b.cci??-Infinity)-(a.cci??-Infinity)).slice(0,8);
  const best1m = perf1m[0];
  const worst1m = perf1m.length>1 ? perf1m[perf1m.length-1] : null;

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">ETFs</h1>
        <div className="filter-pills">
          <span className="filter-pill">{data.universe_size} ETFs</span>
          <span className="filter-pill">{data.qualified} qualified (AUM ≥ $300M · avg vol ≥ 200K)</span>
          <span className={"filter-pill clickable "+(chartsOn?"active":"")} onClick={()=>setChartsOn(v=>!v)}>Charts: {chartsOn?"On":"Off"}</span>
          {data.generated_at && <span className="filter-pill hint">as of {new Date(data.generated_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span>}
        </div>
      </div>

      <div className="filter-pills" style={{marginBottom:16}}>
        {ETF_CATEGORIES.map(c=>(
          <span key={c} className={"filter-pill clickable "+(cat===c?"active":"")} onClick={()=>setCat(c)}>{c}</span>
        ))}
      </div>

      <div className="etf-kicker">The Lead — Universe at a Glance</div>
      <div className="etf-canvas">
        <div className="etf-stat etf-tile etf-tile--w3 etf-edge-accent">
          <span className="etf-tile-kicker">01 · Universe</span>
          <span className="etf-stat-num">{data.universe_size}</span>
          <span className="hint">liquid US-listed ETFs across {Object.keys(ETF_CAT_COLORS).length} categories</span>
        </div>
        <div className="etf-stat etf-tile etf-tile--w3 etf-edge-green">
          <span className="etf-tile-kicker">02 · Qualified</span>
          <span className="etf-stat-num" style={{color:"var(--green)"}}>{data.qualified}</span>
          <span className="hint">AUM ≥ $300M · avg vol ≥ 200K</span>
        </div>
        <div className="etf-stat etf-tile etf-tile--w3 etf-edge-amber">
          <span className="etf-tile-kicker">03 · Benchmark · SPY</span>
          <span className="etf-stat-num">{spy ? fmtPrice(spy.price) : "—"}</span>
          <span className="hint">1M <span className={pctClass(spy&&spy.chg_1m)}>{spy ? fmtPct(spy.chg_1m) : "—"}</span>{spy && spy.cci_zone ? " · CCI "+spy.cci_zone : ""}</span>
        </div>
        <div className="etf-stat etf-tile etf-tile--w3 etf-edge-purple">
          <span className="etf-tile-kicker">04 · Breadth</span>
          <span className={"etf-stat-num "+(avgBreadth50===null?"":avgBreadth50>=50?"pos":"neg")}>{avgBreadth50===null?"—":avgBreadth50.toFixed(0)+"%"}</span>
          <span className="hint">breadth behind mapped ETFs</span>
        </div>

        <div className="panel etf-tile etf-tile--w4">
          <div className="etf-tile-kicker">05 · Leaderboard</div>
          <div className="panel-title">
            <span>Top Scores</span>
            <span className="hint">{hasScores ? "multi-factor leadership score" : "0.6 × perf + 0.4 × CCI-34 zone"}</span>
          </div>
          <EtfRankList rows={topScores.slice(0,6)} onSelect={setSelected}
            right={e=><span className={"tag "+scoreTagClass(e.score)}>{e.score.toFixed(1)}</span>}/>
        </div>
        <div className="panel etf-tile etf-tile--w4">
          <div className="etf-tile-kicker">06 · Momentum</div>
          <div className="panel-title">
            <span>Top by 1M Performance</span>
            <span className="hint">click a row to drill down</span>
          </div>
          <EtfRankList rows={perf1m.slice(0,8)} onSelect={setSelected}
            right={e=><span className={pctClass(e.chg_1m)}>{fmtPct(e.chg_1m)}</span>}/>
        </div>
        <div className="panel etf-tile etf-tile--w4">
          <div className="etf-tile-kicker">07 · Volatility</div>
          <div className="panel-title">
            <span>Highest 20D ADR</span>
            <span className="hint">average daily range % — volatility leaders</span>
          </div>
          <EtfRankList rows={topAdr} onSelect={setSelected}
            right={e=><span className="mono">{e.adr_pct.toFixed(1)}%</span>}/>
        </div>
        <div className="panel etf-tile etf-tile--w6">
          <div className="etf-tile-kicker">08 · Rotation</div>
          <div className="panel-title">
            <span>Relative Rotation — RS vs SPY</span>
            <span className="hint">x: 1M RS (100 = SPY) · y: 1W RS</span>
          </div>
          <Scatter points={rrgPts} xMid={100} yMid={100} quad={{
            tl:{label:"IMPROVING", color:"var(--accent)"},
            tr:{label:"LEADING", color:"var(--green)"},
            bl:{label:"LAGGING", color:"var(--red)"},
            br:{label:"WEAKENING", color:"var(--amber)"},
          }}/>
        </div>
        <div className="panel etf-tile etf-tile--w6">
          <div className="etf-tile-kicker">09 · Risk / Range</div>
          <div className="panel-title">
            <span>ADR vs 1M Performance</span>
            <span className="hint">bubble = √AUM · amber = rel vol ≥ 1.5 · blue = ≥ 0.8</span>
          </div>
          <Scatter points={bubblePts} xMid={0} yMid={3} bubble={true}/>
        </div>
        <div className="panel etf-tile etf-tile--w6">
          <div className="etf-tile-kicker">10 · Structure</div>
          <div className="panel-title">
            <span>Category Weighting &amp; Breadth</span>
            <span className="hint">AUM share per category</span>
          </div>
          <div className="flex ai-center gap-3" style={{flexWrap:"wrap"}}>
            <Donut segments={catSegs} size={190} thickness={28} centerLabel={"$"+catSegs.reduce((a,s)=>a+s.value,0)+"B"}/>
            <div className="flex ai-center gap-3">
              <EtfBreadthRing pct={avgBreadth50}/>
              <div>
                <div className="stat-label">Avg % &gt; 50MA (mapped ETFs)</div>
                <div className="hint" style={{maxWidth:190,marginTop:4}}>breadth of sector/industry constituents behind each mapped ETF</div>
              </div>
            </div>
          </div>
        </div>
        <div className="panel etf-tile etf-tile--w6">
          <div className="etf-tile-kicker">11 · CCI Zones</div>
          <div className="panel-title">
            <span>CCI-34 Zones</span>
            <span className="hint">bullish &gt; 100 · neutral 0–100 · bearish &lt; 0</span>
          </div>
          <div className="etf-zone-counts">
            <div className="etf-zone-count"><span className="num" style={{color:"var(--green)"}}>{zoneCounts.bullish}</span><span className="stat-label">Bullish</span></div>
            <div className="etf-zone-count"><span className="num" style={{color:"var(--amber)"}}>{zoneCounts.neutral}</span><span className="stat-label">Neutral</span></div>
            <div className="etf-zone-count"><span className="num" style={{color:"var(--red)"}}>{zoneCounts.bearish}</span><span className="stat-label">Bearish</span></div>
          </div>
          <HBars rows={[
            {label:"Bullish", value:zoneCounts.bullish, color:"var(--green)"},
            {label:"Neutral", value:zoneCounts.neutral, color:"var(--amber)"},
            {label:"Bearish", value:zoneCounts.bearish, color:"var(--red)"},
            ...(zoneCounts.unknown>0 ? [{label:"Unknown", value:zoneCounts.unknown, color:"var(--text-dim)"}] : []),
          ]} fmt={v=>v}/>
          <div className="hint" style={{marginTop:8}}>count of hub ETFs per CCI-34 zone (values rounded to the nearest 10)</div>
        </div>

        <div className="etf-callout-grid etf-tile etf-tile--w8">
          {best1m ? (
            <div className="etf-stat hover-row" style={{cursor:"pointer"}} onClick={()=>setSelected(best1m.ticker)}>
              <span className="etf-tile-kicker">12 · Best 1M</span>
              <span className="etf-stat-num mono" style={{fontSize:22}}><span className="dot" style={{background:ETF_CAT_COLORS[best1m.category],marginRight:8}}></span>{best1m.ticker}</span>
              <span className={"stat-value "+pctClass(best1m.chg_1m)}>{fmtPct(best1m.chg_1m)}</span>
            </div>
          ) : (
            <div className="etf-stat">
              <span className="etf-tile-kicker">12 · Best 1M</span>
              <span className="etf-stat-num mono" style={{fontSize:22}}>—</span>
              <span className="hint">no 1M data in this filter</span>
            </div>
          )}
          {worst1m ? (
            <div className="etf-stat hover-row" style={{cursor:"pointer"}} onClick={()=>setSelected(worst1m.ticker)}>
              <span className="etf-tile-kicker">13 · Worst 1M</span>
              <span className="etf-stat-num mono" style={{fontSize:22}}><span className="dot" style={{background:ETF_CAT_COLORS[worst1m.category],marginRight:8}}></span>{worst1m.ticker}</span>
              <span className={"stat-value "+pctClass(worst1m.chg_1m)}>{fmtPct(worst1m.chg_1m)}</span>
            </div>
          ) : (
            <div className="etf-stat">
              <span className="etf-tile-kicker">13 · Worst 1M</span>
              <span className="etf-stat-num mono" style={{fontSize:22}}>—</span>
              <span className="hint">no 1M data in this filter</span>
            </div>
          )}
          <div className="etf-stat">
            <span className="etf-tile-kicker">14 · CCI Bullish</span>
            <span className="etf-stat-num" style={{fontSize:22,color:"var(--green)"}}>{zoneCounts.bullish}</span>
            <span className="hint">ETFs with CCI-34 &gt; 100</span>
          </div>
          <div className="etf-stat">
            <span className="etf-tile-kicker">15 · CCI Bearish</span>
            <span className="etf-stat-num" style={{fontSize:22,color:"var(--red)"}}>{zoneCounts.bearish}</span>
            <span className="hint">ETFs with CCI-34 &lt; 0</span>
          </div>
        </div>
        <div className="panel etf-tile etf-tile--w4">
          <div className="etf-tile-kicker">16 · Strongest CCI</div>
          <div className="panel-title">
            <span>Strongest CCI Bullish</span>
            <span className="hint">highest CCI-34 readings</span>
          </div>
          <EtfRankList rows={cciBull.slice(0,4)} onSelect={setSelected}
            right={e=><span className="mono pos">{e.cci}</span>}/>
        </div>
      </div>

      <div className="section-title">Master Table</div>
      {hasScores && (
        <div className="flex gap-2 ai-center" style={{marginBottom:8, flexWrap:"wrap"}}>
          <span className="stat-label">Board</span>
          <div className="filter-pills" style={{margin:0}}>
            {ETF_BOARDS.map(b=>(
              <span key={b.id} className={"filter-pill clickable "+(board===b.id?"active":"")} onClick={()=>setBoard(b.id)}>{b.label}</span>
            ))}
          </div>
          <span className="hint">L / O / R / Rk = universe rank on the Leadership / Opportunity / Rotation / Risk board · default order follows the active board</span>
        </div>
      )}
      <div className="panel">
        {chartsOn && <ChartLayoutSettings layout={chartLayout} onChange={updateChartLayout}/>}
        <div className="table-scroll" ref={scrollRef}>
          <table>
            <thead>
              <tr>
                <SortTh label="ETF" k="ticker" sort={sort}/>
                <SortTh label="Category" k="category" sort={sort}/>
                <SortTh label="Score" k="score" sort={sort}/>
                {hasStates && <SortTh label="State" k="state" sort={sort}/>}
                {hasScores && <SortTh label="L" k="rank_leadership" sort={sort} title="Leadership rank" hl={board==="leadership"}/>}
                {hasScores && <SortTh label="O" k="rank_opportunity" sort={sort} title="Opportunity rank" hl={board==="opportunity"}/>}
                {hasScores && <SortTh label="R" k="rank_rotation" sort={sort} title="Rotation rank" hl={board==="rotation"}/>}
                {hasScores && <SortTh label="Rk" k="rank_risk" sort={sort} title="Risk rank" hl={board==="risk"}/>}
                <SortTh label="CCI-34" k="cci" sort={sort}/>
                <SortTh label="Price" k="price" sort={sort}/>
                <SortTh label="1D" k="chg_1d" sort={sort}/>
                <SortTh label="1W" k="chg_1w" sort={sort}/>
                <SortTh label="1M" k="chg_1m" sort={sort}/>
                <SortTh label="3M" k="chg_3m" sort={sort}/>
                <SortTh label="6M" k="chg_6m" sort={sort}/>
                <SortTh label="YTD" k="chg_ytd" sort={sort}/>
                <SortTh label="1Y" k="chg_1y" sort={sort}/>
                <SortTh label="20D ADR" k="adr" sort={sort}/>
                <SortTh label="Vol Rel" k="rel_vol" sort={sort}/>
                <SortTh label="AUM" k="aum" sort={sort}/>
                <SortTh label="% fr 52w Hi" k="from_hi" sort={sort}/>
                <SortTh label="% >50MA" k="breadth" sort={sort}/>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(e=>(
                <React.Fragment key={e.ticker}>
                <tr className={"hover-row "+(e.ticker===selTicker?"sel-row":"")} onClick={()=>setSelected(e.ticker)}>
                  <td><div className="flex gap-2 ai-center"><span className="mono fw-700">{e.ticker}</span>{e.risk_warning && <span className="tag tag-red" title={e.risk_warning}>⚠</span>}<span className="text-faint" style={{whiteSpace:"normal"}}>{e.name}</span></div></td>
                  <td><span className="tag" style={{color:ETF_CAT_COLORS[e.category]}}>{e.category}</span></td>
                  <td>{e.score!==null&&e.score!==undefined ? <span className={"tag score-tag "+scoreTagClass(e.score)}>{e.score.toFixed(1)}</span> : "—"}</td>
                  {hasStates && <td>{etfStateBadge(e.state)}</td>}
                  {hasScores && <td className="mono" style={board==="leadership"?rankHl:undefined} title={e.leadership_score!==null&&e.leadership_score!==undefined ? "Leadership score "+e.leadership_score.toFixed(1) : undefined}>{e.rank_leadership??"—"}</td>}
                  {hasScores && <td className="mono" style={board==="opportunity"?rankHl:undefined} title={e.opportunity_score!==null&&e.opportunity_score!==undefined ? "Opportunity score "+e.opportunity_score.toFixed(1) : undefined}>{e.rank_opportunity??"—"}</td>}
                  {hasScores && <td className="mono" style={board==="rotation"?rankHl:undefined} title={e.rotation_score!==null&&e.rotation_score!==undefined ? "Rotation score "+e.rotation_score.toFixed(1) : undefined}>{e.rank_rotation??"—"}</td>}
                  {hasScores && <td className="mono" style={board==="risk"?rankHl:undefined} title={e.risk_score!==null&&e.risk_score!==undefined ? "Risk score "+e.risk_score.toFixed(1) : undefined}>{e.rank_risk??"—"}</td>}
                  <td><div className="flex gap-2 ai-center"><span className="mono">{e.cci!==null&&e.cci!==undefined ? e.cci : "—"}</span>{cciZoneBadge(e.cci_zone)}</div></td>
                  <td>{fmtPrice(e.price)}</td>
                  {pctCell(e.chg_1d)}{pctCell(e.chg_1w)}{pctCell(e.chg_1m)}{pctCell(e.chg_3m)}
                  {pctCell(e.chg_6m)}{pctCell(e.chg_ytd)}{pctCell(e.chg_1y)}
                  <td>{e.adr_pct!==null&&e.adr_pct!==undefined ? e.adr_pct.toFixed(1)+"%" : "—"}</td>
                  <td>{e.rel_vol!==null&&e.rel_vol!==undefined ? e.rel_vol.toFixed(2)+"x" : "—"}</td>
                  <td>{fmtAum(e.aum)}</td>
                  <td className="neg">{e.pct_from_52w_high!==null&&e.pct_from_52w_high!==undefined ? e.pct_from_52w_high.toFixed(1)+"%" : "—"}</td>
                  <td>{e.pct_above_50d!==null&&e.pct_above_50d!==undefined ? e.pct_above_50d.toFixed(0)+"%" : "—"}</td>
                  <td><span className="tag-list">{e.tags.map(etfTagBadge)}</span></td>
                </tr>
                {chartsOn && (
                  <tr className="chart-row">
                    <td colSpan={18 + (hasStates?1:0) + (hasScores?4:0)}>
                      <div className="row-charts" data-cols={chartIntervals.length}
                        style={{gridTemplateColumns:"repeat("+chartIntervals.length+",1fr)", width: chartWidth ? chartWidth+"px" : "100%"}}>
                        {chartIntervals.map(iv=>(
                          <div key={iv} className="row-chart-cell">
                            <div className="row-chart-title mono">{e.ticker} · {iv==="D"?"Daily":iv==="W"?"Weekly":iv==="M"?"Monthly":iv+"m"}</div>
                            <TVChart symbol={e.ticker} interval={iv} height={chartHeight}/>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selEtf && (
        <React.Fragment>
          <div className="section-title">Drill-down — {selTicker} <span className="text-faint" style={{textTransform:"none", letterSpacing:0}}>{selEtf.name}</span>{selEtf.score!==null&&selEtf.score!==undefined && <span> · Score <span className={"tag "+scoreTagClass(selEtf.score)}>{selEtf.score.toFixed(1)}</span></span>}{selEtf.cci!==null&&selEtf.cci!==undefined && <span> · CCI-34 {selEtf.cci} {cciZoneBadge(selEtf.cci_zone)}</span>}</div>
          <EtfScoreBreakdown ticker={selTicker}/>
          <div className="grid-2">
            <div className="panel">
              <div className="panel-title">
                <span>Alpha Waterfall</span>
                <span className="hint">top constituents' contribution to 1M return (percentage points)</span>
              </div>
              {wfLoading && <div className="loading">Loading waterfall…</div>}
              {!wfLoading && wfData && (wfData.waterfall
                ? <EtfWaterfall waterfall={wfData.waterfall}/>
                : <div className="empty">{wfData.note || "No mapped constituents for "+selTicker}</div>)}
            </div>
            <div className="panel">
              <div className="panel-title">
                <span>Constituents</span>
                <span className="hint">mapped holdings with CCI-34 and 30D sparkline</span>
              </div>
              <EtfDrilldown ticker={selTicker}/>
            </div>
          </div>
        </React.Fragment>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sync panel
// ---------------------------------------------------------------------------
function SyncPanel({status, onClose}) {
  if(!status) return null;
  return (
    <div className="sync-panel">
      <div className="flex" style={{justifyContent:"space-between", alignItems:"center"}}>
        <h4>{status.running ? "Syncing live data…" : "Sync result"}</h4>
        <span className="close-x" onClick={onClose}><Icon.x/></span>
      </div>
      <div className="sync-log">
        {status.progress_log && status.progress_log.map((l,i)=><div key={i}>{l}</div>)}
        {status.running && <div>…</div>}
      </div>
      {status.report && !status.running && (
        <div className="sync-meta">
          {status.report.metrics_computed!==undefined && <div>{status.report.metrics_computed} of {status.report.universe_size} tickers synced</div>}
          {status.report.errors && status.report.errors.length>0 && (
            <div style={{marginTop:8, color:"var(--red)"}}>{status.report.errors.length} issue(s) — see log</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared analytics helpers
// ---------------------------------------------------------------------------
function snapOf(s){ return s.latest_snapshot || {}; }

// ---------------------------------------------------------------------------
// Leadership scoring, tags, sortable tables
// ---------------------------------------------------------------------------
// One sector ranking everywhere: the backend snapshot score,
// tie-broken by 5d score delta.
function sectorScores(sectors){
  return sectors.map(s=> (snapOf(s).score||0) + (s.score_delta_5d||0)/1000);
}

function tagsFor(s){
  const sn = snapOf(s);
  const ph = sn.etf_pct_from_52w_high;
  const tags = [];
  if(ph!==null&&ph!==undefined&&ph>=-2 && (sn.chg_1m||0)>=8) tags.push({label:"Extended", cls:"tag-amber"});
  if(ph!==null&&ph!==undefined&&ph>=-5 && Math.abs(sn.chg_1w||0)<=2) tags.push({label:"Tight near highs", cls:"tag-green"});
  if(sn.state==="emerging" && (s.score_delta_5d||0)>0) tags.push({label:"Early leader", cls:"tag-blue"});
  if((s.score_delta_5d||0)>=3) tags.push({label:"Improving", cls:"tag-green"});
  if((s.score_delta_5d||0)<=-3 || (s.rs_trend||0)<=-2) tags.push({label:"Weakening", cls:"tag-red"});
  if(s.style==="defensive" && (sn.score||0)>=55) tags.push({label:"Defensive strength", cls:"tag-purple"});
  if(sn.state==="lagging" || ((sn.breadth_pct_above_50ma||0)<40 && (sn.avg_rs_rating||0)<45)) tags.push({label:"Avoid", cls:"tag-grey"});
  return tags.slice(0,3);
}

function Tags({sector}) {
  const tags = tagsFor(sector);
  if(!tags.length) return <span className="text-faint">—</span>;
  return <span className="tag-list">{tags.map(t=> <span key={t.label} className={"tag "+t.cls}>{t.label}</span>)}</span>;
}

function sectorReason(s){
  const sn = snapOf(s);
  const parts = ["Score "+(sn.score||0).toFixed(0)];
  parts.push("RS "+fmtPct1(sn.rs_vs_spy_1m)+" vs SPY");
  parts.push((sn.breadth_pct_above_50ma||0).toFixed(0)+"% breadth");
  if(sn.ema10_above_20) parts.push("EMA 10>20");
  if((s.score_delta_5d||0)!==0) parts.push("Score "+((s.score_delta_5d||0)>0?"+":"")+(s.score_delta_5d||0).toFixed(1)+" 5d");
  return parts.join(" · ");
}

function maxBy(arr, fn){ if(!arr.length) return null; return arr.reduce((a,b)=> fn(b)>fn(a)?b:a); }
function minBy(arr, fn){ if(!arr.length) return null; return arr.reduce((a,b)=> fn(b)<fn(a)?b:a); }

// Sortable table: click a header to sort descending; click again to restore default order.
function useSortable(defaultSort){
  const [sortKey, setSortKey] = useState(null);
  function toggle(key){ setSortKey(k=> k===key ? null : key); }
  function apply(rows, keyFns){
    if(!sortKey || !keyFns[sortKey]) return [...rows].sort(defaultSort);
    const fn = keyFns[sortKey];
    return [...rows].sort((a,b)=>{
      const va = fn(a), vb = fn(b);
      if(typeof va==="string" || typeof vb==="string") return String(vb??"").localeCompare(String(va??""));
      return (vb??-Infinity) - (va??-Infinity);
    });
  }
  return {sortKey, toggle, apply};
}

function SortTh({label, k, sort, title, hl}) {
  const active = sort.sortKey===k;
  return (
    <th className={"sortable "+(active?"active":"")} title={title} onClick={()=>sort.toggle(k)}
      style={hl?{color:"var(--accent)"}:undefined}>
      {label}
      {active && <svg className="sort-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 9 L12 15 L18 9"/></svg>}
    </th>
  );
}

function EmaCell({sn}) {
  return (
    <td className="ma-icons" title={(sn.ema10_above_20?"10EMA > 20EMA":"10EMA < 20EMA")+" · "+(sn.above_50ema?"above 50EMA":"below 50EMA")}>
      <span className="ma-flex">
        {sn.ema10_above_20?<Icon.up color="var(--green)"/>:<Icon.down color="var(--red)"/>}
        {sn.above_50ema?<Icon.up color="var(--green)"/>:<Icon.down color="var(--red)"/>}
      </span>
    </td>
  );
}

function qScoreFor(sectors){
  // The stored sector score is the canonical CCI-based score (50% normalized
  // performance + 50% sector CCI), so the Q-style hunting score reads it
  // straight from the snapshot.
  return sectors.map(s=> snapOf(s).score || 0);
}

function capacityFor(sn){
  const b = sn.breadth_pct_above_50ma||0, v = sn.avg_volume_ratio||0;
  let n = 1 + Math.round(b/25);
  if(v>2) n -= 2; else if(v>1.3) n -= 1;
  return Math.max(1, Math.min(5, n));
}

function qBadge(q){
  if(q>=70) return {cls:"prime", label:"Prime breakout territory"};
  if(q>=55) return {cls:"early", label:"Early expansion"};
  if(q>=40) return {cls:"late", label:"Late trend / extended"};
  return {cls:"avoid", label:"Avoid / choppy"};
}

function stratMatch(strategy, s){
  const sn = snapOf(s);
  if(strategy==="all") return true;
  if(strategy==="breakout") return (sn.pct_new_highs||0) >= 25;
  if(strategy==="pullback") return (sn.state==="leader"||sn.state==="fading") && (sn.chg_3m||0) > 0 && (sn.chg_1w||0) <= 0.5;
  return true;
}

function CapacityMeter({n}) {
  const cls = n>=4 ? "on" : n>=2 ? "on mid" : "on low";
  return (
    <span className="cap-meter" title={"Suggested concurrent positions: "+n}>
      {[1,2,3,4,5].map(i=> <span key={i} className={"cap-seg "+(i<=n?cls:"")}></span>)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Dashboard additions
// ---------------------------------------------------------------------------
function cciRatingColor(r){
  return r==="Bullish" ? "var(--green)" : r==="Bearish" ? "var(--red)" : "var(--amber)";
}

function RiskStrip({sectors, market}) {
  const counts = {leader:0, emerging:0, fading:0, lagging:0, neutral:0};
  sectors.forEach(s=>{ const st = snapOf(s).state || "neutral"; counts[st] = (counts[st]||0)+1; });
  const avgBreadth = avg(sectors.map(s=>snapOf(s).breadth_pct_above_50ma||0));
  const avgVol = avg(sectors.map(s=>snapOf(s).avg_volume_ratio||0));
  const healthy = counts.leader + counts.emerging;
  const weak = counts.fading + counts.lagging;
  // Risk gauge: combined CCI(34) rating across SPY / QQQ / DJI / IWM (0-100)
  // when available; otherwise fall back to average sector breadth.
  const cciScore = market && market.risk_score!==null && market.risk_score!==undefined ? market.risk_score : null;
  const riskVal = cciScore!==null ? cciScore : avgBreadth;
  const mktRating = market && market.market_rating;
  // Breadth / state-count verdict
  let level = "warn", verdict = "Mixed — be selective";
  if(healthy >= weak && riskVal >= 55){ level = "good"; verdict = "Risk-on environment"; }
  if(weak > healthy && riskVal < 45){ level = "bad"; verdict = "Risk-off — manage open risk"; }
  // CCI gating: the combined index rating caps how bullish the verdict can be.
  // Bearish -> always risk-off; anything short of Bullish -> never risk-on.
  if(mktRating === "Bearish"){
    level = "bad"; verdict = "Risk-off — manage open risk";
  } else if(mktRating && mktRating !== "Bullish" && level === "good"){
    level = "warn"; verdict = "Mixed — be selective";
  }
  const dotColor = level==="good" ? "var(--green)" : level==="warn" ? "var(--amber)" : "var(--red)";
  return (
    <div className="panel">
      <div className="panel-title">
        <span>Market Environment</span>
      </div>
      <div className="risk-strip">
        <div className={"risk-verdict risk-"+level} title="Verdict combines sector state counts, average breadth and the combined CCI(34) rating of SPY / QQQ / DJI / IWM. Bearish CCI forces risk-off; anything short of Bullish caps the verdict at Mixed."><span className="risk-dot" style={{background:dotColor}}></span>{verdict}</div>
        <div className="risk-cell" title="Sectors in Leader or Emerging rotation state — the offensive side of the market"><div className="stat-label">Leaders / Emerging</div><div className="stat-value pos">{counts.leader} / {counts.emerging}</div></div>
        <div className="risk-cell" title="Sectors in Fading or Lagging rotation state — the defensive side of the market"><div className="stat-label">Fading / Lagging</div><div className="stat-value neg">{counts.fading} / {counts.lagging}</div></div>
        <div className="risk-cell" title="Average % of constituents above their 50-day moving average across all sectors"><div className="stat-label">Avg Breadth</div><div className="stat-value">{avgBreadth.toFixed(0)}%</div></div>
        <div className="risk-cell" title="Average relative volume (today vs 30-day average) across all sectors — above 1.00x means expanding participation"><div className="stat-label">Avg Vol x</div><div className="stat-value">{avgVol.toFixed(2)}x</div></div>
        {market && (
          <div className="risk-cell" title="Combined CCI(34) rating across SPY / QQQ / DJI / IWM">
            <div className="stat-label">Market (CCI)</div>
            <div className="stat-value" style={{color: mktRating ? cciRatingColor(mktRating) : undefined}}>{mktRating || "—"}</div>
          </div>
        )}
        {market && (market.indices||[]).map(idx=>(
          <div className="risk-cell" key={idx.ticker}
               title={idx.ticker+" CCI(34): "+(idx.cci34??"—")+" · EMA: "+(idx.cci_ema??"—")+(idx.dt ? " · "+idx.dt : "")}>
            <div className="stat-label">{idx.ticker} CCI</div>
            <div className="stat-value">
              <span style={{color: cciRatingColor(idx.rating)}}>{idx.rating ? idx.rating.replace("Bullish (Caution)","Bullish ⚠") : "—"}</span>
              {" "}
              <span className="muted" style={{fontSize:11}}>{idx.cci34!==null && idx.cci34!==undefined ? idx.cci34.toFixed(0) : ""}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Momentum page
// ---------------------------------------------------------------------------
function heatBg(v, maxAbs){
  if(v===null||v===undefined||isNaN(v)) return null;
  const t = Math.min(1, Math.abs(v)/(maxAbs||1));
  const a = 0.12 + t*0.55;
  return v>=0 ? "rgba(62,207,142,"+a.toFixed(2)+")" : "rgba(239,91,91,"+a.toFixed(2)+")";
}

function MomentumStrips({sectors}) {
  const sorted = [...sectors].sort((a,b)=> (snapOf(b).chg_1m||0) - (snapOf(a).chg_1m||0));
  const maxAbs = Math.max(...sectors.flatMap(s=>{ const sn=snapOf(s); return [sn.chg_1d,sn.chg_1w,sn.chg_1m,sn.chg_3m].map(v=>Math.abs(v||0)); }), 1);
  return (
    <div className="heat-grid">
      <div className="heat-row head"><span></span><span>1D</span><span>1W</span><span>1M</span><span>3M</span></div>
      {sorted.map(s=>{
        const sn = snapOf(s);
        return (
          <div key={s.id} className="heat-row">
            <span className="heat-label"><span className="dot" style={{background:secColor(s)}}></span><span className="mono">{s.ticker}</span></span>
            {[sn.chg_1d, sn.chg_1w, sn.chg_1m, sn.chg_3m].map((v,i)=>{
              const bg = heatBg(v, maxAbs);
              return <span key={i} className={"heat-cell "+(bg?"":"na")} style={bg?{background:bg}:{}}>{fmtPct1(v)}</span>;
            })}
          </div>
        );
      })}
    </div>
  );
}

function RankingTables({sectors, onSelectSector}) {
  const cols = [
    {title:"Top 3 by 1M", key: s=> snapOf(s).chg_1m||0},
    {title:"Top 3 by 3M", key: s=> snapOf(s).chg_3m||0},
    {title:"Top 3 blended 1M+3M", key: s=> ((snapOf(s).chg_1m||0)+(snapOf(s).chg_3m||0))/2},
  ];
  return (
    <div className="grid-3">
      {cols.map(col=>{
        const top = [...sectors].sort((a,b)=> col.key(b)-col.key(a)).slice(0,3);
        return (
          <div className="panel" key={col.title}>
            <div className="panel-title">{col.title}</div>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Sector</th><th>State</th><th>Score</th><th>1M</th><th>3M</th><th>Breadth</th><th>RS</th></tr></thead>
                <tbody>
                  {top.map(s=>{
                    const sn = snapOf(s);
                    return (
                      <tr key={s.id} className="hover-row" onClick={()=>onSelectSector(s.id)}>
                        <td><span className="dot" style={{background:secColor(s)}}></span> {s.ticker} <span className="text-faint">{s.name}</span></td>
                        <td><span className={"state-badge "+stateClass(sn.state)}>{stateLabel(sn.state)}</span></td>
                        <td>{(sn.score||0).toFixed(0)}</td>
                        <td className={pctClass(sn.chg_1m)}>{fmtPct1(sn.chg_1m)}</td>
                        <td className={pctClass(sn.chg_3m)}>{fmtPct1(sn.chg_3m)}</td>
                        <td>{(sn.breadth_pct_above_50ma||0).toFixed(0)}%</td>
                        <td>{(sn.avg_rs_rating||0).toFixed(0)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Industry momentum strips — top industries by 1M performance (every
// industry with >= 3 stocks), 1D/1W/1M/3M heat grid like the sector strips.
function IndustryMomentumStrips({onSelectIndustry}) {
  const [industries] = useApi("/api/industries", []);
  if(!industries) return <div className="loading">Loading industries…</div>;
  const rows = industries
    .filter(i=> (i.stock_count||0) >= 3)
    .sort((a,b)=> (b.chg_1m??-999)-(a.chg_1m??-999))
    .slice(0, 12);
  if(!rows.length) return null;
  const maxAbs = Math.max(...rows.flatMap(i=> [i.chg_1d, i.chg_1w, i.chg_1m, i.chg_3m].map(v=>Math.abs(v||0))), 1);
  return (
    <div className="heat-grid">
      <div className="heat-row head"><span></span><span>1D</span><span>1W</span><span>1M</span><span>3M</span></div>
      {rows.map(i=>(
        <div key={i.industry} className="heat-row" style={{cursor:"pointer"}} onClick={()=>onSelectIndustry(i.industry, i.sector_id)} title={i.sector_name ? i.sector_name+" sector" : ""}>
          <span className="heat-label"><span className="dot" style={{background:"var(--accent)"}}></span>{i.industry}{(i.benchmark_etf || i.benchmark_kind==="custom") && <span className="mono text-faint">{" "}{i.benchmark_etf || "Custom"}</span>}</span>
          {[i.chg_1d, i.chg_1w, i.chg_1m, i.chg_3m].map((v,j)=>{
            const bg = heatBg(v, maxAbs);
            return <span key={j} className={"heat-cell "+(bg?"":"na")} style={bg?{background:bg}:{}}>{fmtPct1(v)}</span>;
          })}
        </div>
      ))}
    </div>
  );
}

function MomentumPage({data, onSelectSector, onSelectIndustry}) {
  const sectors = data.sectors || [];
  const rsSpyPoints = sectors.map(s=>{
    const sn = snapOf(s);
    return {x: sn.avg_rs_rating||0, y: sn.rs_vs_spy_1m||0, label: s.ticker, color: stateColor(sn.state), r: Math.max(0.3, sn.avg_volume_ratio||0.3)};
  });
  const dumbbellRows = [...sectors]
    .sort((a,b)=> (snapOf(b).chg_1m||0) - (snapOf(a).chg_1m||0))
    .map(s=>({label: s.ticker, v1: snapOf(s).chg_1w||0, v2: snapOf(s).chg_1m||0, color: stateColor(snapOf(s).state)}));
  const slopeRows = sectors
    .filter(s=> (s.history||[]).length >= 11)
    .map(s=>{
      const h = s.history;
      return {label: s.ticker, from: h[h.length-11].score||0, to: h[h.length-1].score||0, color: s.color};
    });
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Momentum</h1>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Timeframe Momentum Strips</span>
        </div>
        <MomentumStrips sectors={sectors}/>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-title">
            <span>RS vs SPY</span>
          </div>
          <Scatter points={rsSpyPoints} xMid={50} yMid={0}/>
        </div>
        <div className="panel">
          <div className="panel-title">
            <span>RS vs SPY — Volume Bubbles</span>
          </div>
          <Scatter points={rsSpyPoints} xMid={50} yMid={0} bubble={true}/>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-title">
            <span>1W vs 1M Dumbbell</span>
          </div>
          <Dumbbell rows={dumbbellRows} fmt={fmtPct1}/>
        </div>
        <div className="panel">
          <div className="panel-title">
            <span>Score Slope (10 days)</span>
          </div>
          <SlopeChart rows={slopeRows}/>
        </div>
      </div>

      <div className="section-title">Rotation Rankings</div>
      <RankingTables sectors={sectors} onSelectSector={onSelectSector}/>

      <div className="section-title">Industry Momentum (top industries by 1M)</div>
      <div className="panel">
        <div className="panel-title"><span>Industry Timeframe Strips</span><span className="hint">industries with &gt;=3 stocks · click to open the industry page</span></div>
        <IndustryMomentumStrips onSelectIndustry={onSelectIndustry}/>
      </div>
      <IndustryLeadershipPanel onSelectIndustry={onSelectIndustry} limit={15}/>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Breadth & Risk page
// ---------------------------------------------------------------------------
function BreadthHistogram({sectors}) {
  const vals = sectors.map(s=>({t: s.ticker, v: snapOf(s).breadth_pct_above_50ma||0, color: s.color}));
  if(!vals.length) return <div className="empty">No data</div>;
  const buckets = [0,0,0,0,0]; // 0-20 ... 80-100
  vals.forEach(o=>{ buckets[Math.min(4, Math.floor(o.v/20))]++; });
  const med = median(vals.map(o=>o.v));
  const top3 = [...vals].sort((a,b)=>b.v-a.v).slice(0,3).map(o=>o.t);
  const width=560, height=240, pad=36;
  const maxB = Math.max(...buckets, 1);
  const slot = (width-pad*2)/5;
  const yFor = v=> height-pad - (v/maxB)*(height-pad*2);
  const medX = pad + (med/100)*(width-pad*2);
  return (
    <div>
      <svg width="100%" viewBox={"0 0 "+width+" "+height}>
        <line x1={pad} x2={width-pad} y1={height-pad} y2={height-pad} stroke="#2a303a"/>
        {buckets.map((b,i)=>{
          const x = pad + i*slot + slot*0.15, w = slot*0.7;
          return (
            <g key={i}>
              <rect x={x} y={yFor(b)} width={w} height={Math.max(2, height-pad-yFor(b))} fill="var(--accent)" opacity="0.8" rx="3"/>
              <text x={x+w/2} y={yFor(b)-6} fontSize="11" fill="var(--text-dim)" textAnchor="middle" fontFamily="var(--mono)">{b}</text>
              <text x={x+w/2} y={height-pad+14} fontSize="9.5" fill="var(--text-faint)" textAnchor="middle">{i*20}-{i*20+20}%</text>
            </g>
          );
        })}
        <line x1={medX} x2={medX} y1={10} y2={height-pad} stroke="var(--amber)" strokeDasharray="5,3"/>
        <text x={medX} y={18} fontSize="9.5" fill="var(--amber)" textAnchor="middle">median {med.toFixed(0)}%</text>
      </svg>
      <div className="hint" style={{marginTop:6}}>Broad leadership (right-skewed) is healthy; narrow = selective entries only. Top breadth: {top3.join(", ")}.</div>
    </div>
  );
}

function BreadthRiskPage({data}) {
  const sectors = data.sectors || [];
  const nhBreadthPts = sectors.map(s=>{
    const sn = snapOf(s);
    return {x: sn.breadth_pct_above_50ma||0, y: sn.pct_new_highs||0, label: s.ticker, color: stateColor(sn.state)};
  });
  const avgNH = avg(sectors.map(s=>snapOf(s).pct_new_highs||0));
  const volRows = [...sectors]
    .sort((a,b)=> (snapOf(b).avg_volume_ratio||0) - (snapOf(a).avg_volume_ratio||0))
    .map(s=>({label: s.ticker, value: snapOf(s).avg_volume_ratio||0, color: stateColor(snapOf(s).state)}));
  const counts = {leader:0, emerging:0, fading:0, lagging:0, neutral:0};
  sectors.forEach(s=>{ const st = snapOf(s).state||"neutral"; counts[st]=(counts[st]||0)+1; });
  const donutSegs = [
    {label:"Leaders", value:counts.leader, color:"var(--green)"},
    {label:"Emerging", value:counts.emerging, color:"var(--accent)"},
    {label:"Fading", value:counts.fading, color:"var(--red)"},
    {label:"Lagging", value:counts.lagging, color:"#8b94a2"},
    {label:"Neutral", value:counts.neutral, color:"var(--amber)"},
  ].filter(s=>s.value>0);
  const spyRows = [...sectors]
    .sort((a,b)=> (snapOf(b).rs_vs_spy_1m||0) - (snapOf(a).rs_vs_spy_1m||0))
    .map(s=>({label: s.ticker, value: snapOf(s).rs_vs_spy_1m||0, color: (snapOf(s).rs_vs_spy_1m||0)>=0?"var(--green)":"var(--red)"}));
  const top = [...sectors].sort((a,b)=> (snapOf(b).score||0)-(snapOf(a).score||0))[0];
  const wSteps = top ? (()=>{
    const sn = snapOf(top);
    const vsSpyNorm = Math.max(0, Math.min(100, 50 + (sn.rs_vs_spy_1m||0)*5));
    const volNorm = Math.max(0, Math.min(100, (sn.avg_volume_ratio||0)*50));
    return [
      {label:"Breadth", value:(sn.breadth_pct_above_50ma||0)*0.25, color:"var(--accent)"},
      {label:"Avg RS", value:(sn.avg_rs_rating||0)*0.25, color:"var(--green)"},
      {label:"New Highs", value:(sn.pct_new_highs||0)*0.15, color:"var(--amber)"},
      {label:"vs SPY", value:vsSpyNorm*0.25, color:"#b07ef0"},
      {label:"Volume", value:volNorm*0.10, color:"#8b94a2"},
    ];
  })() : [];
  const treemapItems = sectors.map(s=>({label: s.ticker, value: Math.max(1, snapOf(s).score||1), color: stateColor(snapOf(s).state)}));
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Breadth &amp; Risk</h1>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <BreadthHistogram sectors={sectors}/>
        </div>
        <div className="panel">
          <Donut segments={donutSegs} centerLabel={sectors.length+" sectors"}/>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-title">
            <span>New Highs vs Breadth</span>
          </div>
          <Scatter points={nhBreadthPts} xMid={50} yMid={avgNH} quad={{
            tl:{label:"NARROW LEADERSHIP", color:"var(--amber)"},
            tr:{label:"STRONG TREND", color:"var(--green)"},
            bl:{label:"AVOID", color:"var(--red)"},
            br:{label:"EARLY EXPANSION", color:"var(--accent)"},
          }}/>
        </div>
        <div className="panel">
          <div className="panel-title">
            <span>Volume Pressure</span>
          </div>
          <HBars rows={volRows} fmt={v=>v.toFixed(2)+"x"} refLine={{x:1, label:"1.0x"}}/>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <HBars rows={spyRows} fmt={fmtPct1}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>Score Anatomy{top ? " — "+top.ticker : ""}</span></div>
          <Waterfall steps={wSteps}/>
        </div>
      </div>

      <div className="panel">
        <Treemap items={treemapItems}/>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Playbook page
// ---------------------------------------------------------------------------
function QStylePanel({sectors, strategy, onSelectSector}) {
  const qs = qScoreFor(sectors);
  const rows = sectors.map((s,i)=>({s, q: qs[i]})).sort((a,b)=>b.q-a.q);
  return (
    <div className="q-grid">
      {rows.map(({s,q})=>{
        const sn = snapOf(s);
        const badge = qBadge(q);
        const dim = !stratMatch(strategy, s);
        return (
          <div key={s.id} className={"q-card "+(dim?"dimmed":"")} style={{borderLeftColor: s.color}} onClick={()=>onSelectSector(s.id)}>
            <div className="q-head">
              <span className="mono fw-700">{s.ticker}</span>
              <span className="q-score">{q.toFixed(0)}</span>
            </div>
            <div className="flex gap-2 ai-center" style={{justifyContent:"space-between"}}>
              <span className={"q-badge "+badge.cls}>{badge.label}</span>
              <CapacityMeter n={capacityFor(sn)}/>
            </div>
            <div className="q-meta">
              <span>1M <span className={pctClass(sn.chg_1m)}>{fmtPct1(sn.chg_1m)}</span></span>
              <span>3M <span className={pctClass(sn.chg_3m)}>{fmtPct1(sn.chg_3m)}</span></span>
              <span>RS {(sn.avg_rs_rating||0).toFixed(0)}</span>
              <span>Br {(sn.breadth_pct_above_50ma||0).toFixed(0)}%</span>
              <span>NH {(sn.pct_new_highs||0).toFixed(0)}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const TL_COLORS = {leader:"#00e676", emerging:"#7ee787", fading:"#ff2e63", lagging:"#7a8494", neutral:"#d9a03f"};

function RotationTimeline({sectors}) {
  return (
    <div>
      {sectors.map(s=>{
        const hist = (s.history||[]).slice(-10);
        return (
          <div key={s.id} className="tl-row">
            <span className="heat-label"><span className="dot" style={{background:secColor(s)}}></span><span className="mono">{s.ticker}</span></span>
            <div className="tl-cells">
              {hist.map((h,i)=>(
                <div key={i} className="tl-cell" style={{background: TL_COLORS[h.state] || "#232830"}}
                  title={h.dt+" — "+stateLabel(h.state)+", score "+(h.score||0).toFixed(0)}>
                  {(h.score||0).toFixed(0)}
                </div>
              ))}
            </div>
          </div>
        );
      })}
      <div className="tl-legend">
        {Object.keys(TL_COLORS).map(k=> <span key={k}><span className="tl-swatch" style={{background:TL_COLORS[k]}}></span>{stateLabel(k)}</span>)}
      </div>
    </div>
  );
}

function MiniChartsGrid({sectors, strategy, onSelectSector}) {
  return (
    <div className="mini-grid">
      {sectors.map(s=>{
        const sn = snapOf(s);
        const vals = (s.history||[]).slice(-40).map(h=>h.price);
        const dim = !stratMatch(strategy, s);
        return (
          <div key={s.id} className={"mini-card "+(dim?"dimmed":"")} style={{borderTopColor: stateColor(sn.state)}} onClick={()=>onSelectSector(s.id)}>
            <div className="mini-head">
              <span className="mini-ticker">{s.ticker}</span>
              <span className={"mini-chg "+pctClass(sn.chg_1m)}>{fmtPct1(sn.chg_1m)}</span>
            </div>
            <MiniPrice values={vals}/>
            <div className="mini-head" style={{marginTop:4}}>
              <span className={"state-badge "+stateClass(sn.state)}>{stateLabel(sn.state)}</span>
              <span className="text-faint" style={{fontSize:10}}>score {(sn.score||0).toFixed(0)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function WatchlistExporter({sectors}) {
  const [copied, setCopied] = useState(false);
  const qs = qScoreFor(sectors);
  const rows = sectors.map((s,i)=>({s, q:qs[i]})).sort((a,b)=>b.q-a.q).slice(0,5);
  function buildText(){
    const lines = ["TOP SECTOR WATCHLIST — "+new Date().toLocaleDateString(), ""];
    rows.forEach(({s,q},i)=>{
      const sn = snapOf(s);
      const etfs = (s.primary_etf ? [s.primary_etf] : [s.ticker]).join(", ");
      lines.push((i+1)+". "+s.name+" ("+s.ticker+") — "+qBadge(q).label);
      lines.push("   ETFs: "+etfs+" | Score "+(sn.score||0).toFixed(0)+" | 1M "+fmtPct1(sn.chg_1m)+" | 3M "+fmtPct1(sn.chg_3m)+" | Breadth "+(sn.breadth_pct_above_50ma||0).toFixed(0)+"% | Hunt "+capacityFor(sn)+" setups");
    });
    return lines.join("\n");
  }
  function doCopy(){
    const txt = buildText();
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).then(()=>{ setCopied(true); setTimeout(()=>setCopied(false), 1500); });
    }
  }
  function doDownload(){
    const blob = new Blob([buildText()], {type:"text/plain"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "sector-watchlist.txt";
    a.click();
    URL.revokeObjectURL(a.href);
  }
  return (
    <div className="panel">
      <div className="panel-title">
        <span>Top Sector Watchlist</span>
        <span className="flex ai-center">
          <button className="btn" onClick={doCopy}>Copy</button>
          <button className="btn" onClick={doDownload} style={{marginLeft:8}}>Download .txt</button>
          {copied && <span className="copy-flash">Copied</span>}
        </span>
      </div>
      {rows.map(({s,q},i)=>{
        const sn = snapOf(s);
        return (
          <div key={s.id} className="watch-item">
            <span className="watch-rank">{i+1}</span>
            <span className="dot" style={{background:secColor(s)}}></span>
            <div className="watch-body">
              <span className="fw-700">{s.name}</span> <span className="mono text-faint">{s.ticker}</span>
              <span className={"q-badge "+qBadge(q).cls} style={{marginLeft:8}}>{qBadge(q).label}</span>
            </div>
            <span className="watch-setups">hunt {capacityFor(sn)} setups · score {(sn.score||0).toFixed(0)}</span>
          </div>
        );
      })}
    </div>
  );
}

function TradePanel({sectors}) {
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [ticker, setTicker] = useState("");
  const [sectorId, setSectorId] = useState(sectors[0] ? sectors[0].id : 1);
  const [risk, setRisk] = useState("");

  function load(){
    fetch("/api/trades").then(r=>r.json()).then(setTrades);
    fetch("/api/trades/summary").then(r=>r.json()).then(setSummary);
  }
  useEffect(()=>{ load(); }, []);

  function addTrade(){
    if(!ticker.trim() || !risk) return;
    fetch("/api/trades", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ticker, sector_id: sectorId, risk_pct: parseFloat(risk)}),
    }).then(()=>{ setTicker(""); setRisk(""); load(); });
  }
  function delTrade(id){
    fetch("/api/trades/"+id, {method:"DELETE"}).then(load);
  }

  const weakShare = summary ? summary.weak_share : 0;
  const totalRisk = summary ? summary.total_risk : 0;
  return (
    <div className="panel">
      <div className="panel-title">
        <span>Trade Tags &amp; Sector Exposure</span>
      </div>
      {weakShare > 50 && (
        <div className="warn-banner"><Icon.warn color="var(--red)"/> {weakShare.toFixed(0)}% of your risk is in fading/lagging sectors — consider rotating exposure.</div>
      )}
      <div className="form-row">
        <input id="trade-ticker" name="trade-ticker" placeholder="Ticker (e.g. AAPL)" value={ticker} onChange={e=>setTicker(e.target.value)}/>
        <select id="trade-sector" name="trade-sector" value={sectorId} onChange={e=>setSectorId(parseInt(e.target.value))}>
          {sectors.map(s=> <option key={s.id} value={s.id}>{s.name} ({s.ticker})</option>)}
        </select>
        <input id="trade-risk" name="trade-risk" className="risk" placeholder="Risk %" type="number" min="0" step="0.1" value={risk} onChange={e=>setRisk(e.target.value)}/>
        <button className="btn primary" onClick={addTrade}>Add Trade</button>
      </div>
      {summary && summary.sectors.length>0 && (
        <div>
          <div className="stat-label" style={{marginBottom:4}}>Risk by sector (total {totalRisk.toFixed(1)}%)</div>
          <div className="exposure-bar">
            {summary.sectors.map(r=>(
              <div key={r.sector_id} className="exposure-seg"
                style={{width:(r.total_risk/totalRisk*100)+"%", background: TL_COLORS[r.state] || "#5b8def"}}
                title={r.sector_name+": "+r.total_risk.toFixed(1)+"% risk ("+stateLabel(r.state)+")"}>
                {r.sector_ticker}
              </div>
            ))}
          </div>
        </div>
      )}
      <div style={{marginTop:10}}>
        {trades.length===0 && <div className="empty">No trades logged yet</div>}
        {trades.map(t=>(
          <div key={t.id} className="trade-row">
            <span className="dot" style={{background:t.color||"#5b8def"}}></span>
            <span className="mono fw-700">{t.ticker}</span>
            <span className="text-dim">{t.sector_name}</span>
            <span className="mono">{t.risk_pct}% risk</span>
            <span className="text-faint">{new Date(t.ts).toLocaleDateString()}</span>
            <span className="trade-del" onClick={()=>delTrade(t.id)}><Icon.x/></span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlaybookPage({data, onSelectSector, onSelectIndustry}) {
  const sectors = data.sectors || [];
  const [strategy, setStrategy] = useState("all");
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Playbook</h1>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          <span>Strategy Filter</span>
        </div>
        <div className="toggle-row" style={{marginBottom:0}}>
          {[["all","All"],["breakout","Breakout"],["pullback","Pullback"]].map(([id,label])=>(
            <div key={id} className={"toggle "+(strategy===id?"active":"")} onClick={()=>setStrategy(id)}>{label}</div>
          ))}
        </div>
      </div>

      <div className="section-title">Hunting Grounds (Q-Style Score)</div>
      <QStylePanel sectors={sectors} strategy={strategy} onSelectSector={onSelectSector}/>

      <div className="section-title">Per-Sector Trend Minis (price vs 20MA)</div>
      <div className="panel"><MiniChartsGrid sectors={sectors} strategy={strategy} onSelectSector={onSelectSector}/></div>

      <div className="section-title">Rotation Timeline (last 10 snapshots)</div>
      <div className="panel">
        <RotationTimeline sectors={sectors}/>
      </div>

      <div className="section-title">Industry Leadership — where to hunt</div>
      <IndustryLeadershipPanel onSelectIndustry={onSelectIndustry} limit={15}/>

      <div className="section-title">Export &amp; Journal</div>
      <WatchlistExporter sectors={sectors}/>
      <TradePanel sectors={sectors}/>
    </div>
  );
}

// ---------------------------------------------------------------------------
// All Sectors page — sector command center
// ---------------------------------------------------------------------------
function cmdOf(s){ return s.command || {}; }

function ArrowChip({value, suffix=""}) {
  if(value===null||value===undefined||isNaN(value)) return <span className="text-faint">—</span>;
  const up = value>=0;
  return (
    <span className={"arrow-chip "+(up?"up":"down")}>
      {up ? <Icon.up/> : <Icon.down/>}
      {up?"+":""}{value.toFixed(suffix==="x"?2:1)}{suffix}
    </span>
  );
}

function BarMeter({value, max=100, color, digits=0, suffix="%"}) {
  if(value===null||value===undefined||isNaN(value)) return <span className="text-faint">—</span>;
  const pct = Math.max(0, Math.min(100, (value/max)*100));
  const c = color || (value>=60 ? "var(--green)" : value>=40 ? "var(--amber)" : "var(--red)");
  return (
    <span className="bar-meter" title={value.toFixed(1)+suffix}>
      <span className="bar-meter-val">{value.toFixed(digits)}{suffix}</span>
      <span className="bar-meter-track"><span className="bar-meter-fill" style={{width:pct+"%", background:c}}></span></span>
    </span>
  );
}

function HeadlineRow({sectors, onSelectSector}) {
  if(!sectors.length) return null;
  const cards = [
    {label:"Highest Score", pick: maxBy(sectors, s=>snapOf(s).score||0), stat: s=>(snapOf(s).score||0).toFixed(0), sub: s=>stateLabel(snapOf(s).state)},
    {label:"Best Improver", pick: maxBy(sectors, s=>s.score_delta_5d||0), stat: s=>"+"+(s.score_delta_5d||0).toFixed(1), sub: s=>"score Δ 5d"},
    {label:"Strongest 3M Trend", pick: maxBy(sectors, s=>snapOf(s).chg_3m||-999), stat: s=>fmtPct1(snapOf(s).chg_3m), sub: s=>"3M return"},
    {label:"Breadth Leader", pick: maxBy(sectors, s=>snapOf(s).breadth_pct_above_50ma||0), stat: s=>(snapOf(s).breadth_pct_above_50ma||0).toFixed(0)+"%", sub: s=>"above 50MA"},
    {label:"Most Extended", pick: (()=>{ const ext = sectors.filter(s=>{ const sn=snapOf(s); return (sn.state==="leader"||sn.state==="emerging") && sn.etf_pct_from_52w_high!==null&&sn.etf_pct_from_52w_high!==undefined&&sn.etf_pct_from_52w_high>=-2; }); return ext.length ? maxBy(ext, s=>snapOf(s).chg_1m||0) : maxBy(sectors, s=>snapOf(s).chg_1m||0); })(), stat: s=>fmtPct1(snapOf(s).chg_1m), sub: s=>"1M · "+(snapOf(s).etf_pct_from_52w_high!==null&&snapOf(s).etf_pct_from_52w_high!==undefined ? snapOf(s).etf_pct_from_52w_high.toFixed(1)+"% fr Hi" : "")},
    {label:"Weakest Sector", pick: minBy(sectors, s=>snapOf(s).score||0), stat: s=>(snapOf(s).score||0).toFixed(0), sub: s=>stateLabel(snapOf(s).state)},
  ];
  return (
    <div className="headline-cards">
      {cards.map(c=>{
        if(!c.pick) return null;
        const s = c.pick;
        const spark = (s.history||[]).slice(-20).map(h=>h.score);
        return (
          <div key={c.label} className="hl-card" onClick={()=>onSelectSector(s.id)}>
            <div className="stat-label">{c.label}</div>
            <div className="hl-name">
              <span className="dot" style={{background:secColor(s)}}></span>
              <span className="mono fw-700">{s.ticker}</span>
              <span className="hl-stat">{c.stat(s)}</span>
            </div>
            <div className="hl-sub">{c.sub(s)}</div>
            <LineSpark values={spark} width={120} height={26} color={secColor(s)}/>
          </div>
        );
      })}
    </div>
  );
}

function rankColor(rank, n){
  const t = n>1 ? (rank-1)/(n-1) : 0; // 0 = best
  if(t<=0.5){ const a = 0.85 - t*1.1; return "rgba(0,230,118,"+Math.max(0.15,a).toFixed(2)+")"; }
  const a = 0.25 + (t-0.5)*0.9; return "rgba(255,46,99,"+a.toFixed(2)+")";
}

function RankHeatmap({sectors}) {
  const hists = sectors.map(s=>({s, h: (s.history||[]).slice(-10)}));
  const nDates = Math.max(...hists.map(o=>o.h.length), 0);
  if(!nDates) return <div className="empty">No history</div>;
  // rank per date column (column index aligned from the right)
  const cols = [];
  for(let c=0;c<nDates;c++){
    const vals = hists.map(o=>{
      const idx = o.h.length - nDates + c;
      return {id:o.s.id, score: idx>=0 ? (o.h[idx].score||0) : -1};
    });
    const ordered = [...vals].sort((a,b)=>b.score-a.score);
    const ranks = {};
    ordered.forEach((v,i)=> ranks[v.id]=i+1);
    cols.push(ranks);
  }
  const latest = cols[cols.length-1];
  const rows = [...hists].sort((a,b)=> (latest[a.s.id]||99)-(latest[b.s.id]||99));
  return (
    <div className="rk-grid">
      <div className="rk-row rk-head">
        <span></span>
        {cols.map((_,i)=> <span key={i} className="rk-d">{i===cols.length-1?"now":"-"+(cols.length-1-i)}</span>)}
      </div>
      {rows.map(o=>(
        <div key={o.s.id} className="rk-row">
          <span className="heat-label"><span className="dot" style={{background:secColor(o.s)}}></span><span className="mono">{o.s.ticker}</span></span>
          {cols.map((ranks,i)=>{
            const r = ranks[o.s.id]||sectors.length;
            return <span key={i} className="rk-cell" style={{background:rankColor(r, sectors.length)}} title={o.s.ticker+" rank "+r}>{r}</span>;
          })}
        </div>
      ))}
    </div>
  );
}

function BreadthDecomp({sectors}) {
  const rows = [...sectors].sort((a,b)=> (cmdOf(b).breadth_50||0)-(cmdOf(a).breadth_50||0));
  if(!rows.length) return <div className="empty">No data</div>;
  const width=560,rowH=19,padL=64,padR=40;
  const h = rows.length*rowH+28;
  const xFor = v=> padL + (v/100)*(width-padL-padR);
  const series = [
    {k:"breadth_20", color:"#8ecae6", label:">20EMA"},
    {k:"breadth_50", color:"#f0b429", label:">50EMA"},
    {k:"breadth_200", color:"#a87f0a", label:">200EMA"},
  ];
  return (
    <div>
      <svg width="100%" viewBox={"0 0 "+width+" "+h}>
        {[0,25,50,75,100].map(g=>(
          <g key={g}>
            <line x1={xFor(g)} x2={xFor(g)} y1={0} y2={h-22} stroke="#23231a" strokeWidth="1"/>
            <text x={xFor(g)} y={h-10} fontSize="8.5" fill="var(--text-faint)" textAnchor="middle">{g}%</text>
          </g>
        ))}
        {rows.map((s,i)=>{
          const y = i*rowH+3;
          return (
            <g key={s.id}>
              <text x={padL-6} y={y+9} fontSize="10" fill="var(--text-dim)" fontFamily="var(--mono)" textAnchor="end">{s.ticker}</text>
              {series.map((se,si)=>{
                const v = cmdOf(s)[se.k];
                if(v===null||v===undefined) return null;
                return <rect key={se.k} x={padL} y={y+si*4.5} width={Math.max(1,xFor(v)-padL)} height={3.2} fill={se.color} opacity="0.9" rx="1"/>;
              })}
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {series.map(se=> <span key={se.k}><span className="legend-dot" style={{background:se.color}}></span>{se.label}</span>)}
      </div>
    </div>
  );
}

function PullbackZones({sectors, onSelectSector}) {
  const zones = sectors.filter(s=>{
    const sn = snapOf(s), c = cmdOf(s);
    return (sn.state==="leader"||sn.state==="emerging") && sn.above_50ema
      && (sn.chg_1w||0)<=1.5 && (c.dist_pivot===null||c.dist_pivot===undefined||c.dist_pivot>=-6);
  }).sort((a,b)=> (cmdOf(b).dist_pivot??-99)-(cmdOf(a).dist_pivot??-99));
  return (
    <div className="panel">
      <div className="panel-title"><span>Pullback Buy Zones</span><span className="hint">leader/emerging · above 50EMA · resting near pivot</span></div>
      {zones.length===0 && <div className="empty">No sectors in a buy zone right now</div>}
      {zones.map(s=>{
        const sn = snapOf(s), c = cmdOf(s);
        const buy = (c.dist_pivot??-99)>=-3 && (sn.chg_1w||0)<=0.5;
        return (
          <div key={s.id} className="zone-row" onClick={()=>onSelectSector(s.id)}>
            <span className="dot" style={{background:secColor(s)}}></span>
            <span className="mono fw-700">{s.ticker}</span>
            <span className="zone-meta">score {(sn.score||0).toFixed(0)}</span>
            <span className="zone-meta">pivot {c.dist_pivot!==null&&c.dist_pivot!==undefined ? c.dist_pivot.toFixed(1)+"%" : "—"}</span>
            <span className={"zone-meta "+pctClass(sn.chg_1w)}>1W {fmtPct1(sn.chg_1w)}</span>
            <span className={"q-badge "+(buy?"prime":"early")}>{buy?"Buy zone":"Watch"}</span>
          </div>
        );
      })}
    </div>
  );
}

function RiskSizer({sectors}) {
  const ls = sectorScores(sectors);
  const rows = sectors.map((s,i)=>({s, ls:ls[i]})).sort((a,b)=>b.ls-a.ls).slice(0,5);
  return (
    <div className="panel">
      <div className="panel-title"><span>Vol &amp; Risk Sizer</span><span className="hint">top 5 leadership · stop = 2×ATR%</span></div>
      <div className="rs-table">
        <div className="rs-row rs-head">
          <span>Sector</span><span>ATR%</span><span>Stop</span><span>Vol</span><span>Beta</span><span>Regime</span>
        </div>
        {rows.map(({s})=>{
          const c = cmdOf(s);
          const atr = c.atr_pct, vol = c.realized_vol;
          const regime = vol===null||vol===undefined ? null : vol<15 ? {l:"Low", cls:"prime"} : vol<30 ? {l:"Normal", cls:"late"} : {l:"High", cls:"avoid"};
          return (
            <div key={s.id} className="rs-row">
              <span><span className="dot" style={{background:secColor(s)}}></span> <span className="mono fw-700">{s.ticker}</span></span>
              <span className="mono">{atr!==null&&atr!==undefined ? atr.toFixed(2)+"%" : "—"}</span>
              <span className="mono">{atr!==null&&atr!==undefined ? (atr*2).toFixed(1)+"%" : "—"}</span>
              <span className="mono">{vol!==null&&vol!==undefined ? vol.toFixed(0)+"%" : "—"}</span>
              <span className="mono">{c.beta!==null&&c.beta!==undefined ? c.beta.toFixed(2) : "—"}</span>
              <span>{regime ? <span className={"q-badge "+regime.cls}>{regime.l}</span> : "—"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SectorCommandTable({sectors, onClick}) {
  const sort = useSortable((a,b)=> (snapOf(b).score||0) - (snapOf(a).score||0));
  const heatCols = ["chg_1d","chg_1w","chg_1m","chg_3m","rs_vs_spy_1m"];
  const maxAbs = {};
  heatCols.forEach(k=>{
    maxAbs[k] = Math.max(...sectors.map(s=>Math.abs(snapOf(s)[k]||0)), 1);
  });
  const keyFns = {
    ticker: s=> s.ticker,
    state: s=> snapOf(s).state||"",
    score: s=> snapOf(s).score||0,
    score_delta: s=> s.score_delta_5d||0,
    rank_delta: s=> s.rank_delta||0,
    trend: s=> s.score_delta_5d||0,
    chg_1d: s=> snapOf(s).chg_1d||0,
    chg_1w: s=> snapOf(s).chg_1w||0,
    chg_1m: s=> snapOf(s).chg_1m||0,
    chg_3m: s=> snapOf(s).chg_3m||0,
    breadth: s=> snapOf(s).breadth_pct_above_50ma||0,
    b20: s=> cmdOf(s).breadth_20??-1,
    b50: s=> cmdOf(s).breadth_50??-1,
    b200: s=> cmdOf(s).breadth_200??-1,
    bo: s=> cmdOf(s).breakouts??-1,
    bd: s=> cmdOf(s).breakdowns??-1,
    nh: s=> snapOf(s).pct_new_highs||0,
    rs: s=> snapOf(s).avg_rs_rating||0,
    rs_delta: s=> s.rs_trend||0,
    rs_pct: s=> cmdOf(s).rs_percentile??-1,
    rs_slope: s=> cmdOf(s).rs_slope??-999,
    vs_spy: s=> snapOf(s).rs_vs_spy_1m||0,
    atr: s=> cmdOf(s).atr_pct??-1,
    vol: s=> cmdOf(s).realized_vol??-1,
    beta: s=> cmdOf(s).beta??-999,
    dd: s=> cmdOf(s).drawdown??-999,
    from_hi: s=> snapOf(s).etf_pct_from_52w_high??-999,
    pivot: s=> cmdOf(s).dist_pivot??-999,
  };
  const sorted = sort.apply(sectors, keyFns);
  const heatTd = (k, v)=> (
    <td className={pctClass(v)} style={heatBg(v, maxAbs[k])?{background:heatBg(v, maxAbs[k])}:{}}>{fmtPct(v)}</td>
  );
  return (
    <div className="panel">
      <div className="panel-title"><span>Sector Command Table</span></div>
      <div className="table-scroll">
        <table className="cmd-table">
          <thead>
            <tr className="cg-row">
              <th className="sticky-col" rowSpan="2">Sector</th>
              <th className="cg-head" colSpan="5">Score &amp; Rank</th>
              <th className="cg-head" colSpan="4">Momentum</th>
              <th className="cg-head" colSpan="7">Participation</th>
              <th className="cg-head" colSpan="5">Relative Strength</th>
              <th className="cg-head" colSpan="6">Risk</th>
              <th rowSpan="2">Tags</th>
            </tr>
            <tr>
              <SortTh label="State" k="state" sort={sort}/>
              <SortTh label="Score" k="score" sort={sort}/>
              <SortTh label="Score Δ" k="score_delta" sort={sort} title="5-day score change"/>
              <SortTh label="Rank Δ" k="rank_delta" sort={sort} title="5-day rank change (positive = moved up)"/>
              <SortTh label="Trend" k="trend" sort={sort} title="Score history, last 20 snapshots"/>
              <SortTh label="1D" k="chg_1d" sort={sort}/>
              <SortTh label="1W" k="chg_1w" sort={sort}/>
              <SortTh label="1M" k="chg_1m" sort={sort}/>
              <SortTh label="3M" k="chg_3m" sort={sort}/>
              <SortTh label="Breadth" k="breadth" sort={sort} title="% of constituents above 50MA"/>
              <SortTh label="&gt;20E" k="b20" sort={sort} title="% of constituents above 20EMA"/>
              <SortTh label="&gt;50E" k="b50" sort={sort} title="% of constituents above 50EMA"/>
              <SortTh label="&gt;200E" k="b200" sort={sort} title="% of constituents above 200EMA"/>
              <SortTh label="BO" k="bo" sort={sort} title="Breakouts: constituents within 3% of 52w high"/>
              <SortTh label="BD" k="bd" sort={sort} title="Breakdowns: constituents within 3% of 52w low"/>
              <SortTh label="NH%" k="nh" sort={sort} title="% new highs"/>
              <SortTh label="Avg RS" k="rs" sort={sort}/>
              <SortTh label="RS Δ" k="rs_delta" sort={sort} title="RS rating change, 5 days"/>
              <SortTh label="RS %" k="rs_pct" sort={sort} title="Cross-sectional RS percentile"/>
              <SortTh label="RS Slope" k="rs_slope" sort={sort} title="Slope of avg RS rating, last 10 snapshots"/>
              <SortTh label="vs SPY" k="vs_spy" sort={sort} title="1M relative strength vs SPY"/>
              <SortTh label="ATR%" k="atr" sort={sort} title="Mean absolute daily move, 14d"/>
              <SortTh label="Vol" k="vol" sort={sort} title="Annualized realized volatility, 30d"/>
              <SortTh label="Beta" k="beta" sort={sort} title="Beta vs benchmark, 30d"/>
              <SortTh label="DD" k="dd" sort={sort} title="Worst drawdown from 52w high, last 20d"/>
              <SortTh label="% fr Hi" k="from_hi" sort={sort} title="Distance from 52-week high"/>
              <SortTh label="Pivot" k="pivot" sort={sort} title="Distance below 20d pivot high"/>
            </tr>
          </thead>
          <tbody>
            {sorted.map(s=>{
              const sn = snapOf(s), c = cmdOf(s);
              const spark = (s.history||[]).slice(-20).map(h=>h.score);
              return (
                <tr key={s.id} onClick={()=>onClick(s.id)} className="hover-row">
                  <td className="sticky-col">
                    <div className="flex gap-2 ai-center">
                      <span className="dot" style={{background:secColor(s)}}></span>
                      <span className="mono fw-700">{s.ticker}</span>
                      <span className="text-dim">{s.name}</span>
                    </div>
                  </td>
                  <td><span className={"state-badge "+stateClass(sn.state)}>{stateLabel(sn.state)}</span></td>
                  <td><div className="score-cell"><span>{(sn.score||0).toFixed(0)}</span><ScoreBar value={sn.score||0}/></div></td>
                  <td><ArrowChip value={s.score_delta_5d}/></td>
                  <td><ArrowChip value={s.rank_delta}/></td>
                  <td><MiniSpark values={spark} width={72} height={20} positive={(s.score_delta_5d||0)>=0}/></td>
                  {heatTd("chg_1d", sn.chg_1d)}
                  {heatTd("chg_1w", sn.chg_1w)}
                  {heatTd("chg_1m", sn.chg_1m)}
                  {heatTd("chg_3m", sn.chg_3m)}
                  <td><BarMeter value={sn.breadth_pct_above_50ma}/></td>
                  <td><BarMeter value={c.breadth_20}/></td>
                  <td><BarMeter value={c.breadth_50}/></td>
                  <td><BarMeter value={c.breadth_200}/></td>
                  <td className="pos">{c.breakouts!==undefined ? c.breakouts : "—"}</td>
                  <td className="neg">{c.breakdowns!==undefined ? c.breakdowns : "—"}</td>
                  <td>{(sn.pct_new_highs||0).toFixed(0)}%</td>
                  <td><BarMeter value={sn.avg_rs_rating}/></td>
                  <td><ArrowChip value={s.rs_trend}/></td>
                  <td><BarMeter value={c.rs_percentile} suffix=""/></td>
                  <td><ArrowChip value={c.rs_slope}/></td>
                  {heatTd("rs_vs_spy_1m", sn.rs_vs_spy_1m)}
                  <td>{c.atr_pct!==null&&c.atr_pct!==undefined ? c.atr_pct.toFixed(2)+"%" : "—"}</td>
                  <td>{c.realized_vol!==null&&c.realized_vol!==undefined ? c.realized_vol.toFixed(0)+"%" : "—"}</td>
                  <td>{c.beta!==null&&c.beta!==undefined ? c.beta.toFixed(2) : "—"}</td>
                  <td className="neg">{c.drawdown!==null&&c.drawdown!==undefined ? c.drawdown.toFixed(1)+"%" : "—"}</td>
                  <td className="neg">{sn.etf_pct_from_52w_high!==null&&sn.etf_pct_from_52w_high!==undefined ? sn.etf_pct_from_52w_high.toFixed(1)+"%" : "—"}</td>
                  <td className="neg">{c.dist_pivot!==null&&c.dist_pivot!==undefined ? c.dist_pivot.toFixed(1)+"%" : "—"}</td>
                  <td><Tags sector={s}/></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AllSectorsPage({sectors, onSelectSector, onSelectIndustry, strategy}) {
  const [filter, setFilter] = useState("all");
  const ls = sectorScores(sectors);
  const lsById = {};
  sectors.forEach((s,i)=> lsById[s.id]=ls[i]);

  const isExtended = s=>{ const sn=snapOf(s); const ph=sn.etf_pct_from_52w_high; return ph!==null&&ph!==undefined&&ph>=-2 && (sn.chg_1m||0)>=8; };
  const isWeak = s=>{ const sn=snapOf(s); return sn.state==="lagging" || ((sn.breadth_pct_above_50ma||0)<40 && (sn.avg_rs_rating||0)<45); };
  const FILTERS = [
    ["all","All"],
    ["leaders","Leaders", s=> snapOf(s).state==="leader"],
    ["improving","Improving", s=> (s.score_delta_5d||0)>=3],
    ["offensive","Offensive", s=> s.style==="offensive"],
    ["defensive","Defensive", s=> s.style==="defensive"],
    ["extended","Extended", isExtended],
    ["weak","Weak", isWeak],
  ];
  const active = FILTERS.find(f=>f[0]===filter);
  const shown = active && active[2] ? sectors.filter(active[2]) : sectors;

  const extPts = sectors.map(s=>({
    x: lsById[s.id], y: snapOf(s).etf_pct_from_52w_high??-50, label: s.ticker, color: stateColor(snapOf(s).state),
  }));
  const medLs = median(ls);
  const deltaRows = [...sectors]
    .sort((a,b)=> (b.score_delta_5d||0)-(a.score_delta_5d||0))
    .map(s=>({label: s.ticker, value: s.score_delta_5d||0, color: (s.score_delta_5d||0)>=0?"var(--green)":"var(--red)"}));
  const rsBreadthPts = sectors.map(s=>({
    x: snapOf(s).breadth_pct_above_50ma||0, y: snapOf(s).avg_rs_rating||0, label: s.ticker, color: stateColor(snapOf(s).state),
  }));
  const persistRows = [...sectors]
    .sort((a,b)=> (cmdOf(b).top5_persistence||0)-(cmdOf(a).top5_persistence||0))
    .map(s=>({label: s.ticker, value: cmdOf(s).top5_persistence||0, color: stateColor(snapOf(s).state)}));

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">All Sectors</h1>
        </div>
      </div>

      {strategy && (
        <div className="strategy-strip">
          <span className="strategy-name">{strategyLabel(strategy)} engine</span>
          <span className="text-dim">Scores, states and rankings below are computed with the {strategyLabel(strategy)} composite (CCI included).</span>
        </div>
      )}

      <HeadlineRow sectors={sectors} onSelectSector={onSelectSector}/>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-title">
            <span>Leadership vs Extension</span>
          </div>
          <Scatter points={extPts} xMid={medLs} yMid={-5} quad={{
            tl:{label:"WEAK / EXTENDED", color:"var(--amber)"},
            tr:{label:"LEADERS — EXTENDED", color:"var(--red)"},
            bl:{label:"LAGGING", color:"#8b94a2"},
            br:{label:"LEADERS — ROOM TO RUN", color:"var(--green)"},
          }}/>
        </div>
        <div className="panel">
          <div className="panel-title">
            <span>Score Δ (5d)</span>
          </div>
          <HBars rows={deltaRows} fmt={v=>(v>0?"+":"")+v.toFixed(1)}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>Rank Heatmap (last 10 snapshots)</span></div>
          <RankHeatmap sectors={sectors}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>Breadth Decomposition</span></div>
          <BreadthDecomp sectors={sectors}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>RS vs Breadth</span></div>
          <Scatter points={rsBreadthPts} xMid={50} yMid={50} quad={{
            tl:{label:"STRONG RS / NARROW", color:"var(--amber)"},
            tr:{label:"CONFIRMED LEADERS", color:"var(--green)"},
            bl:{label:"LAGGARDS", color:"var(--red)"},
            br:{label:"BROAD / WEAK RS", color:"#8b94a2"},
          }}/>
        </div>
        <div className="panel">
          <div className="panel-title"><span>Leadership Persistence (top-5 time)</span></div>
          <HBars rows={persistRows} fmt={v=>v.toFixed(0)+"%"} refLine={{x:50, label:"50%"}}/>
        </div>
      </div>

      <div className="toggle-row">
        {FILTERS.map(([id,label])=>(
          <div key={id} className={"toggle "+(filter===id?"active":"")} onClick={()=>setFilter(id)}>{label}</div>
        ))}
      </div>

      <div className="grid-2">
        <PullbackZones sectors={sectors} onSelectSector={onSelectSector}/>
        <RiskSizer sectors={sectors}/>
      </div>

      <div className="section-title">Industry Leadership</div>
      <IndustryLeadershipPanel strategy={strategy} onSelectIndustry={onSelectIndustry} limit={15}/>

      <SectorCommandTable sectors={shown} onClick={onSelectSector}/>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Watchlist page — ranked by the weighted formula:
//   Final = performance 75% (1W 15 + 1M 42.5 + 3M 42.5) + ADR 20% + EMA proximity 5%
// every input min-max normalized across the watchlist (backend computes it).
// Each stock also carries a Breakout rank (Qullamaggie setup composite).
// EPs are tracked separately in the EP section's own watchlist.
// ---------------------------------------------------------------------------
const WL_SORT_KEYS = {
  wl_rank: e=> e.wl_rank ?? 1e9,
  ticker: e=> e.ticker,
  score: e=> e.watchlist_score ?? -1,
  adr: e=> e.adr_pct ?? -1,
  ema: e=> e.ema_dist ?? 1e9,
  chg_1w: e=> e.chg_1w ?? -999,
  chg_1m: e=> e.chg_1m ?? -999,
  chg_3m: e=> e.chg_3m ?? -999,
  breakout_rank: e=> e.breakout_rank ?? 1e9,
  breakout_score: e=> e.breakout_score ?? -1,
};

// Three ways to organize the list: flat (as before), sector-wise, industry-wise.
const WL_VIEW_MODES = [["flat","Flat"],["sector","By Sector"],["industry","By Industry"]];

function wlAvgKey(items, key){
  const vals = items.map(e=>e[key]).filter(v=> v!=null && !isNaN(v));
  return vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null;
}
function wlCountBy(items, key){
  const m = new Map();
  items.forEach(e=>{ const k = e[key]||"Unknown"; m.set(k,(m.get(k)||0)+1); });
  return [...m.entries()].sort((a,b)=> b[1]-a[1] || a[0].localeCompare(b[0]));
}

// Minimalist infographic: composition (where the stocks come from), average
// performance across timeframes, trend breadth, and score stats — all computed
// client-side from the watchlist entries.
function WatchlistAnalytics({items}){
  const st = useMemo(()=>{
    const n = items.length;
    const sectors = wlCountBy(items,"sector_name");
    const industries = wlCountBy(items,"industry");
    const above = k=>{
      const known = items.filter(e=> e[k]!==null && e[k]!==undefined);
      return known.length ? 100*known.filter(e=>e[k]).length/known.length : null;
    };
    const withBo = items.filter(e=> e.breakout_score!=null);
    const by3m = items.filter(e=> e.chg_3m!=null).sort((a,b)=> b.chg_3m-a.chg_3m);
    return {
      n, sectors, industries,
      topSector: sectors[0]||null, topIndustry: industries[0]||null,
      a1w: wlAvgKey(items,"chg_1w"), a1m: wlAvgKey(items,"chg_1m"),
      a3m: wlAvgKey(items,"chg_3m"), a6m: wlAvgKey(items,"chg_6m"),
      aytd: wlAvgKey(items,"chg_ytd"),
      avgFinal: wlAvgKey(items,"watchlist_score"),
      medBo: withBo.length ? median(withBo.map(e=>e.breakout_score)) : null,
      b20: above("above_20d"), b50: above("above_50d"), b200: above("above_200d"),
      best: by3m[0]||null, worst: by3m[by3m.length-1]||null,
    };
  }, [items]);
  if(!st.n) return null;
  // Infographic tile: group accent bar on top, index number, label, value, sub.
  let tileIdx = 0;
  const tile = (label, main, sub, bar)=>( 
    <div className="wl-stat" key={label} style={{borderTopColor:bar}}>
      <span className="stat-label"><span className="wl-num" style={{color:bar}}>{String(++tileIdx).padStart(2,"0")}</span>{label}</span>
      {main}
      {sub||null}
    </div>
  );
  const ret = (label, v, bar)=> tile("Avg "+label,
    <span className={"wl-v "+(v==null?"":pctClass(v))}>{fmtPct1(v)}</span>, null, bar);
  const breadth = (label, v, bar)=> tile(label,
    <span className="wl-v">{v==null?"—":v.toFixed(0)+"%"}</span>,
    <div className="bar-bg" style={{height:4}}><div className="bar-fill" style={{width:(v||0)+"%", background:bar}}></div></div>, bar);
  // Three rows of exactly five tiles — a fully symmetric 5×3 infographic grid,
  // no ragged last row. Colors: composition accent, returns green, breadth purple.
  const C1 = "var(--accent)", C2 = "var(--green)", C3 = "var(--purple)";
  const rows = [
    ["Composition", [
      tile("Stocks", <span className="wl-v">{st.n}</span>,
        <span className="wl-s">{st.sectors.length} sectors · {st.industries.length} industries</span>, C1),
      tile("Top Sector",
        <span className="wl-v-sm" title={st.topSector ? st.topSector[0] : ""}>{st.topSector ? st.topSector[0] : "—"}</span>,
        st.topSector && <span className="wl-s">{st.topSector[1]} stocks · {(st.topSector[1]/st.n*100).toFixed(0)}%</span>, C1),
      tile("Top Industry",
        <span className="wl-v-sm" title={st.topIndustry ? st.topIndustry[0] : ""}>{st.topIndustry ? st.topIndustry[0] : "—"}</span>,
        st.topIndustry && <span className="wl-s">{st.topIndustry[1]} stocks · {(st.topIndustry[1]/st.n*100).toFixed(0)}%</span>, C1),
      tile("Avg Final", <span className="wl-v accent">{st.avgFinal==null?"—":st.avgFinal.toFixed(1)}</span>, null, C1),
      tile("Median Bo Score", <span className="wl-v">{st.medBo==null?"—":st.medBo.toFixed(1)}</span>, null, C1),
    ]],
    ["Average Returns", [
      ret("1W", st.a1w, C2), ret("1M", st.a1m, C2), ret("3M", st.a3m, C2), ret("6M", st.a6m, C2), ret("YTD", st.aytd, C2),
    ]],
    ["Trend Breadth & Extremes", [
      breadth("Above 20EMA", st.b20, C3), breadth("Above 50EMA", st.b50, C3), breadth("Above 200EMA", st.b200, C3),
      tile("Best 3M", <span className="wl-v pos">{st.best ? st.best.ticker : "—"}</span>,
        st.best && <span className="wl-s pos">{fmtPct(st.best.chg_3m)}</span>, C3),
      tile("Worst 3M", <span className="wl-v neg">{st.worst ? st.worst.ticker : "—"}</span>,
        st.worst && <span className="wl-s neg">{fmtPct(st.worst.chg_3m)}</span>, C3),
    ]],
  ];
  return (
    <div className="panel">
      <div className="panel-title"><span>Watchlist Snapshot</span>
        <span className="hint">Composition, average returns and trend breadth across your {st.n} names</span></div>
      <div className="wl-info">
        {rows.map(([group, tiles])=>(
          <div className="wl-info-group" key={group}>
            <span className="wl-info-caption">{group}</span>
            <div className="wl-stats">{tiles}</div>
          </div>
        ))}
      </div>
      {st.sectors.length>1 && (
        <div className="wl-secbars">
          <span className="stat-label">Sector Concentration</span>
          {st.sectors.slice(0,5).map(([name,c],i)=>(
            <div className="wl-secbar" key={name}>
              <span className="wl-secbar-name" title={name}>{name}</span>
              <div className="bar-bg" style={{height:6}}>
                <div className="bar-fill" style={{width:(c/st.n*100)+"%", background:SECTOR_PALETTE[i%SECTOR_PALETTE.length]}}></div>
              </div>
              <span className="mono text-dim">{c} · {(c/st.n*100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// One watchlist table. In grouped mode an extra "Grp Bo" column shows the
// breakout score min-max re-normalized within that sector/industry, so each
// stock is ranked against its own group's constituents.
function WlTable({wl, sort, rows, grouped}) {
  const keys = grouped ? {...WL_SORT_KEYS, grp_bo: e=> e._grpBo ?? -1} : WL_SORT_KEYS;
  const sorted = sort.apply(rows, keys);
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th title="Remove from watchlist">✓</th>
            <SortTh label="Ticker" k="ticker" sort={sort}/>
            <SortTh label="Rank" k="wl_rank" sort={sort} title="Watchlist rank by the weighted final score"/>
            <SortTh label="Final" k="score" sort={sort} title="Performance 75% (1W 15 / 1M 42.5 / 3M 42.5) + ADR 20% + EMA proximity 5%, normalized"/>
            <SortTh label="ADR" k="adr" sort={sort} title="Raw ADR % (normalized value in tooltip)"/>
            <SortTh label="EMA Δ" k="ema" sort={sort} title="Distance % to the nearest of the 10/20/50 EMA (lower = tighter; normalized value in cell tooltip)"/>
            <SortTh label="1W" k="chg_1w" sort={sort}/>
            <SortTh label="1M" k="chg_1m" sort={sort}/>
            <SortTh label="3M" k="chg_3m" sort={sort}/>
            <SortTh label="Bo Rk" k="breakout_rank" sort={sort} title="Rank as a breakout (Qullamaggie setup composite)"/>
            <SortTh label="Bo Score" k="breakout_score" sort={sort}/>
            {grouped && <SortTh label="Grp Bo" k="grp_bo" sort={sort} title="Breakout score re-normalized 0-100 within this group only"/>}
          </tr>
        </thead>
        <tbody>
          {sorted.map(e=>(
            <tr key={e.ticker}>
              <td className="watch-cell"><WatchBtn wl={wl} ticker={e.ticker}/></td>
              <td className="mono fw-700">{e.ticker}</td>
              <td className="mono fw-700">{e.wl_rank ?? "—"}</td>
              <td className="mono fw-700 accent">{e.watchlist_score!=null ? e.watchlist_score.toFixed(1) : "—"}</td>
              <td title={e.norm ? "normalized "+e.norm.adr : ""}>{e.adr_pct==null?"—":e.adr_pct.toFixed(2)+"%"}</td>
              <td title={e.norm ? "normalized "+e.norm.ema_prox : ""}>{e.ema_dist!=null ? e.ema_dist.toFixed(2)+"%" : "—"}</td>
              <td className={pctClass(e.chg_1w)} title={e.norm ? "normalized "+e.norm.p1w : ""}>{fmtPct(e.chg_1w)}</td>
              <td className={pctClass(e.chg_1m)} title={e.norm ? "normalized "+e.norm.p1m : ""}>{fmtPct(e.chg_1m)}</td>
              <td className={pctClass(e.chg_3m)} title={e.norm ? "normalized "+e.norm.p3m : ""}>{fmtPct(e.chg_3m)}</td>
              <td className="mono">{e.breakout_rank ?? "—"}</td>
              <td className="mono">{e.breakout_score!=null ? e.breakout_score.toFixed(1) : "—"}</td>
              {grouped && <td className="mono accent">{e._grpBo==null ? "—" : e._grpBo.toFixed(1)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WatchlistPage({wl}) {
  const sort = useSortable((a,b)=> (a.wl_rank||1e9)-(b.wl_rank||1e9));
  const [chartsOn, setChartsOn] = useState(false);
  const [chartLayout, updateChartLayout] = useChartLayout();
  const [viewMode, setViewMode] = useState(()=>{
    try{ return localStorage.getItem("wl.viewMode") || "flat"; }catch(e){ return "flat"; }
  });
  function changeView(v){ setViewMode(v); try{ localStorage.setItem("wl.viewMode", v); }catch(e){} }
  const wlItems = (wl.items||[]).filter(e=>e.category!=="ep");
  const items = sort.apply(wlItems, WL_SORT_KEYS);
  const groups = useMemo(()=>{
    if(viewMode==="flat") return null;
    const key = viewMode==="sector" ? "sector_name" : "industry";
    const m = new Map();
    wlItems.forEach(e=>{ const k = e[key]||"Unknown"; if(!m.has(k)) m.set(k,[]); m.get(k).push(e); });
    return [...m.entries()].map(([name, arr])=>{
      const bos = arr.map(e=>e.breakout_score).filter(v=> v!=null);
      const mn = bos.length ? Math.min(...bos) : 0, mx = bos.length ? Math.max(...bos) : 0;
      const span = (mx-mn)||1;
      return {
        name,
        items: arr.map(e=>({...e, _grpBo: e.breakout_score==null ? null : Math.round((e.breakout_score-mn)/span*1000)/10})),
        a1m: wlAvgKey(arr,"chg_1m"), a3m: wlAvgKey(arr,"chg_3m"), aBo: wlAvgKey(arr,"breakout_score"),
      };
    }).sort((a,b)=> b.items.length-a.items.length || a.name.localeCompare(b.name));
  }, [wlItems, viewMode]);
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Watchlist</h1>
          <div className="page-subtitle">
            Final = performance 75% (1W 15% · 1M 42.5% · 3M 42.5%) + ADR 20% + EMA proximity 5% — inputs min-max normalized across the list
          </div>
        </div>
      </div>
      <div className="filter-pills">
        <span className="filter-pill">{wlItems.length} stocks</span>
        <span className="filter-pill hint">Add stocks with the ✓ icon anywhere in the app</span>
        <span className="filter-pill hint" style={{border:"none"}}>Organize:</span>
        {WL_VIEW_MODES.map(([id,label])=>(
          <span key={id} className={"filter-pill clickable "+(viewMode===id?"active":"")} onClick={()=>changeView(id)}>{label}</span>
        ))}
      </div>
      {wlItems.length>0 && <WatchlistAnalytics items={wlItems}/>}
      <div className="panel">
        <div className="toggle-row" style={{alignItems:"center", justifyContent:"flex-end"}}>
          <Switch on={chartsOn} onChange={setChartsOn} label="Charts"
                  title="Show TradingView charts for every stock in the list"/>
        </div>
        {chartsOn && <ChartLayoutSettings layout={chartLayout} onChange={updateChartLayout}/>}
        {chartsOn && items.length>0 && !groups &&
          <StockChartsGrid stocks={items} layout={chartLayout} renderAction={s=><WatchBtn wl={wl} ticker={s.ticker}/>}/>}
        {chartsOn && items.length>0 && groups && groups.map(g=>(
          <div key={g.name} className="wl-group">
            <div className="wl-group-head">
              <span className="wl-group-name">{g.name}</span>
              <span className="mono text-dim">{g.items.length} stocks</span>
              <span className={"mono "+(g.a1m==null?"":pctClass(g.a1m))}>1M {fmtPct1(g.a1m)}</span>
              <span className={"mono "+(g.a3m==null?"":pctClass(g.a3m))}>3M {fmtPct1(g.a3m)}</span>
              <span className="mono text-dim">avg Bo {g.aBo==null ? "—" : g.aBo.toFixed(1)}</span>
            </div>
            <StockChartsGrid stocks={sort.apply(g.items, {...WL_SORT_KEYS, grp_bo: e=> e._grpBo ?? -1})} layout={chartLayout} renderAction={s=><WatchBtn wl={wl} ticker={s.ticker}/>}/>
          </div>
        ))}
        {!wl.items && <div className="loading">Loading watchlist…</div>}
        {wl.items && items.length===0 &&
          <div className="empty">Watchlist is empty — click the ✓ next to any stock (constituents, screener…) to add it.</div>}
        {wl.items && items.length>0 && viewMode==="flat" && <WlTable wl={wl} sort={sort} rows={items}/>}
        {wl.items && items.length>0 && groups && groups.map(g=>(
          <div key={g.name} className="wl-group">
            <div className="wl-group-head">
              <span className="wl-group-name">{g.name}</span>
              <span className="mono text-dim">{g.items.length} stocks</span>
              <span className={"mono "+(g.a1m==null?"":pctClass(g.a1m))}>1M {fmtPct1(g.a1m)}</span>
              <span className={"mono "+(g.a3m==null?"":pctClass(g.a3m))}>3M {fmtPct1(g.a3m)}</span>
              <span className="mono text-dim">avg Bo {g.aBo==null ? "—" : g.aBo.toFixed(1)}</span>
            </div>
            <WlTable wl={wl} sort={sort} rows={g.items} grouped/>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EP section — a fully independent Episodic Pivot workspace. Own data feed
// (/api/ep-dashboard), infographic-style research dashboard (KPIs, funnel,
// analytics grid, dense candidate rows), charts and watchlist. All EP
// preferences persist in localStorage under "ep.*" keys and are never shared
// with the rest of the app.
// ---------------------------------------------------------------------------
function epLoad(key, def){
  try{ const v = localStorage.getItem("ep."+key); return v===null ? def : JSON.parse(v); }
  catch(e){ return def; }
}
function epSave(key, val){
  try{ localStorage.setItem("ep."+key, JSON.stringify(val)); }catch(e){}
}

// EP-only watchlist: a plain list of tickers in localStorage.
function useEpWatchlist(){
  const [items, setItems] = useState(()=> epLoad("watchlist", []));
  function save(next){ setItems(next); epSave("watchlist", next); }
  function toggle(t){
    save(items.indexOf(t) >= 0 ? items.filter(x=>x!==t) : items.concat([t]));
  }
  return {items, toggle, has: t=> items.indexOf(t) >= 0};
}

const EP_TABS = [
  ["dashboard","Dashboard"], ["charts","Charts"], ["watchlist","Watchlist"],
];

// Star button toggling the EP watchlist (independent from the app watchlist).
function EpWatchBtn({epwl, ticker}){
  const active = epwl.has(ticker);
  return (
    <button className={"watch-btn star "+(active?"active":"")}
      title={active ? "In EP watchlist — click to remove" : "Add to EP watchlist"}
      onClick={e=>{ e.stopPropagation(); epwl.toggle(ticker); }}>
      <Icon.star filled={active}/>
    </button>
  );
}

// --- EP classification + score meta (research dashboard) ---
const EP_CLASS = {
  confirmed:   {label:"Confirmed EP",   color:"var(--green)"},
  possible:    {label:"Possible EP",    color:"var(--amber)"},
  momentum:    {label:"Momentum Mover", color:"var(--accent)"},
  speculative: {label:"News Spike",     color:"var(--purple)"},
  rejected:    {label:"Rejected",       color:"var(--red)"},
};
const EP_CLASS_ORDER = ["confirmed","possible","momentum","speculative","rejected"];
function epClass(c){ return EP_CLASS[c] || EP_CLASS.momentum; }

const EP_PART_META = [
  ["catalyst","Catalyst","#00e676"],
  ["expansion","Expansion","#6ea8fe"],
  ["volume","Volume","#d9a03f"],
  ["structure","Structure","#4cc9f0"],
  ["continuation","Continuation","#8a7bd8"],
  ["risk","Risk","#ff9f7a"],
];

const EP_DEFAULT_FILTERS = {
  classes: ["confirmed","possible","momentum","speculative"],
  ctype: "", sector: "",
  minCap: "", minPrice: "", minDollarVol: "", minRelVol: "", minGap: "", minScore: "",
};

function EpClassBadge({cls}){
  const m = epClass(cls);
  return <span className="ep-badge" style={{color:m.color, borderColor:m.color}}>{m.label}</span>;
}

// Catalyst status pill — never implies news that does not exist.
function EpStatusPill({status}){
  if(status==="verified") return <span className="ep-pill verified">verified</span>;
  if(status==="unverified") return <span className="ep-pill unverified">unverified</span>;
  return <span className="ep-pill unavailable">no verified news</span>;
}

// Tiny perf-trend sparkline: 3M → 1M → 1W → 1D as sequential points.
function EpTrendSpark({trend, width=64, height=20}){
  const t = trend || {};
  const vals = [t.chg_3m, t.chg_1m, t.chg_1w, t.chg_1d];
  if(vals.some(v=> v==null || isNaN(v))) return <span className="text-faint" style={{fontSize:10}}>—</span>;
  const min = Math.min(...vals, 0), max = Math.max(...vals, 0);
  const span = (max-min) || 1;
  const pts = vals.map((v,i)=> (2 + i*(width-4)/(vals.length-1)) + "," + (height-2 - ((v-min)/span)*(height-4))).join(" ");
  const up = vals[vals.length-1] >= vals[0];
  return (
    <svg width={width} height={height} title={"perf trend 3M→1M→1W→1D: "+vals.map(v=>fmtPct1(v)).join(" · ")}>
      <polyline points={pts} fill="none" stroke={up?"var(--green)":"var(--red)"} strokeWidth="1.4"/>
    </svg>
  );
}

// Close position inside the day's range (0-100) as a micro bar.
function EpRangeMicro({pos}){
  if(pos==null || isNaN(pos)) return <span className="text-faint" style={{fontSize:10}}>—</span>;
  const p = Math.max(0, Math.min(100, pos));
  return (
    <span className="ep-range" title={"close position in range: "+p.toFixed(0)+"%"}>
      <span className="ep-range-fill" style={{left:p+"%", background: p>=70?"var(--green)":(p>=40?"var(--amber)":"var(--red)")}}></span>
    </span>
  );
}

// --- KPI strip ---
function EpKpiStrip({kpis}){
  const k = kpis || {};
  const defs = [
    ["confirmed","Confirmed","var(--green)"],
    ["high_quality_catalyst","High-Quality Catalysts","var(--green)"],
    ["strong_volume","Strong Volume","var(--green)"],
    ["expansion","Expansion Moves","var(--accent)"],
    ["watchlist","Watchlist Candidates","var(--amber)"],
    ["rejected","Rejected","var(--red)"],
  ];
  return (
    <div className="ep-kpi-grid">
      {defs.map(([key,label,color])=>(
        <div key={key} className="ep-kpi" style={{borderTopColor:color}}>
          <div className="ep-kpi-val mono" style={{color}}>{k[key]!=null ? k[key] : "—"}</div>
          <div className="ep-kpi-label">{label}</div>
        </div>
      ))}
    </div>
  );
}

// --- scan funnel: universe → movers → filters → verified → confirmed ---
function EpFunnel({stages}){
  const rows = stages || [];
  if(!rows.length) return null;
  const max = Math.max(...rows.map(s=> s.count||0), 1);
  return (
    <div className="ep-funnel">
      {rows.map((s,i)=>(
        <div key={s.key||i} className="ep-funnel-stage">
          <div className="ep-funnel-meta"><span>{s.label}</span><span className="mono">{s.count}</span></div>
          <div className="ep-funnel-bar" style={{width: Math.max(2,(s.count||0)/max*100)+"%"}} title={s.label+": "+s.count}></div>
        </div>
      ))}
    </div>
  );
}

// --- stacked score composition for the top 8 candidates ---
function EpPartsStack({cands}){
  const rows = (cands||[]).filter(c=> c.score_parts).slice(0,8);
  if(!rows.length) return <div className="empty">No score breakdown available</div>;
  return (
    <div>
      {rows.map(c=>{
        const parts = c.score_parts || {};
        const total = EP_PART_META.reduce((a,[k])=> a+Math.max(0,parts[k]||0), 0) || 1;
        return (
          <div key={c.ticker} className="ep-stack-row"
            title={EP_PART_META.map(([k,label])=> label+" "+(parts[k]||0)).join(" · ")}>
            <span className="ep-stack-label mono">{c.ticker}</span>
            <span className="ep-stack-track">
              {EP_PART_META.map(([k,,color])=>{
                const v = Math.max(0, parts[k]||0);
                if(!v) return null;
                return <span key={k} className="ep-stack-seg" style={{width:(v/total*100)+"%", background:color}}></span>;
              })}
            </span>
            <span className="mono ep-stack-val">{(c.ep_score||0).toFixed(0)}</span>
          </div>
        );
      })}
      <div className="ep-stack-legend">
        {EP_PART_META.map(([k,label,color])=>(
          <span key={k}><span className="dot" style={{background:color}}></span>{label}</span>
        ))}
      </div>
    </div>
  );
}

// --- sector strength list (score + avg 1D change, green/red) ---
function EpSectorBars({sectors}){
  const rows = sectors || [];
  if(!rows.length) return <div className="empty">No sector data</div>;
  const m = Math.max(...rows.map(s=> Math.abs(s.score||0)), 1);
  return (
    <div>
      {rows.map((s,i)=>(
        <div key={s.name||i} className="ep-hbar-row">
          <span className="ep-hbar-label">{s.name}</span>
          <span className="ep-hbar-track">
            <span className="ep-hbar-fill" style={{width: Math.max(2, Math.abs(s.score||0)/m*100)+"%",
              background: (s.avg_chg||0)>=0 ? "var(--green)" : "var(--red)"}}></span>
          </span>
          <span className="mono ep-hbar-val">{(s.score||0).toFixed(0)}</span>
          <span className={"mono "+pctClass(s.avg_chg||0)} style={{width:52, textAlign:"right", fontSize:11}}>{fmtPct1(s.avg_chg)}</span>
        </div>
      ))}
    </div>
  );
}

// --- catalyst-type breakdown; unverified/unavailable labeled honestly ---
function EpCatalystTypes({cands}){
  const counts = {};
  (cands||[]).forEach(c=>{
    const cat = c.catalyst || {};
    let key;
    if(cat.ctype && cat.status==="verified") key = cat.ctype;
    else if(cat.ctype && cat.status==="unverified") key = cat.ctype+" (unverified)";
    else key = "no verified news";
    counts[key] = (counts[key]||0)+1;
  });
  const rows = Object.keys(counts).map(name=>({name, count:counts[name]})).sort((a,b)=> b.count-a.count);
  if(!rows.length) return <div className="empty">No catalyst data</div>;
  const m = Math.max(...rows.map(r=>r.count), 1);
  return (
    <div>
      {rows.map(r=>(
        <div key={r.name} className="ep-hbar-row">
          <span className="ep-hbar-label">{r.name}</span>
          <span className="ep-hbar-track"><span className="ep-hbar-fill" style={{width:Math.max(2, r.count/m*100)+"%", background:"var(--purple)"}}></span></span>
          <span className="mono ep-hbar-val">{r.count}</span>
        </div>
      ))}
    </div>
  );
}

// --- dense filter row above the candidate list ---
function EpFiltersRow({filters, onChange, sectors, ctypes, scanTime}){
  function set(patch){ onChange(Object.assign({}, filters, patch)); }
  function toggleClass(cls){
    const cur = filters.classes || [];
    set({classes: cur.indexOf(cls)>=0 ? cur.filter(x=>x!==cls) : cur.concat([cls])});
  }
  const mins = [
    ["minCap","Cap $M"],["minPrice","Price $"],["minDollarVol","$Vol $M"],
    ["minRelVol","RelVol x"],["minGap","Gap %"],["minScore","Score"],
  ];
  return (
    <div className="ep-filter-row">
      {EP_CLASS_ORDER.map(cls=>{
        const on = (filters.classes||[]).indexOf(cls)>=0;
        return (
          <div key={cls} className={"toggle "+(on?"active":"")}
            style={on ? {borderColor:EP_CLASS[cls].color, color:EP_CLASS[cls].color, background:"transparent"} : null}
            onClick={()=>toggleClass(cls)}>{EP_CLASS[cls].label}</div>
        );
      })}
      <select className="ep-select" value={filters.ctype} onChange={e=>set({ctype:e.target.value})}>
        <option value="">All catalysts</option>
        {ctypes.map(t=><option key={t} value={t}>{t}</option>)}
      </select>
      <select className="ep-select" value={filters.sector} onChange={e=>set({sector:e.target.value})}>
        <option value="">All sectors</option>
        {sectors.map(s=><option key={s} value={s}>{s}</option>)}
      </select>
      {mins.map(([k,label])=>(
        <label key={k} className="ep-num">min {label}
          <input type="number" value={filters[k]} onChange={e=>set({[k]:e.target.value})}/>
        </label>
      ))}
      {scanTime && <span className="text-faint mono" style={{marginLeft:"auto", fontSize:10.5}}>scan: {scanTime}</span>}
    </div>
  );
}

// --- amber empty-state panel: why nothing confirmed + biggest movers ---
function EpEmptyPanel({cands}){
  const counts = {};
  (cands||[]).forEach(c=>{
    (c.penalties||[]).concat(c.missing||[]).forEach(p=>{ counts[p]=(counts[p]||0)+1; });
  });
  const top = Object.keys(counts).map(k=>[k,counts[k]]).sort((a,b)=> b[1]-a[1]).slice(0,5);
  const movers = [...(cands||[])].sort((a,b)=> Math.abs(b.chg_1d||0)-Math.abs(a.chg_1d||0)).slice(0,5);
  return (
    <div className="ep-empty-panel">
      <div className="fw-700" style={{color:"var(--amber)"}}>No confirmed EPs right now — strongest candidates are listed below.</div>
      {top.length>0 && (
        <div className="ep-empty-reasons">
          <span className="text-dim">Main failure reasons:</span>
          {top.map(([label,n])=> <span key={label} className="ep-pill missing">{label} <b className="mono">{n}</b></span>)}
        </div>
      )}
      {movers.length>0 && (
        <div className="ep-empty-movers">
          <span className="text-dim">Biggest movers:</span>
          {movers.map(mo=> <span key={mo.ticker} className="mono">{mo.ticker} <span className={pctClass(mo.chg_1d||0)}>{fmtPct1(mo.chg_1d)}</span></span>)}
        </div>
      )}
    </div>
  );
}

// --- inline detail drawer under a candidate row ---
function EpRowDetail({c, metaTime, note, onNote}){
  const cat = c.catalyst || {};
  const parts = c.score_parts || {};
  const partTotal = EP_PART_META.reduce((a,[k])=> a+Math.max(0,parts[k]||0), 0) || 1;
  const hi52 = (c.price!=null && c.pct_from_52w_high!=null) ? c.price/(1+c.pct_from_52w_high/100) : null;
  return (
    <div className="ep-detail">
      <div className="ep-detail-col">
        <div className="ep-detail-title">Catalyst &amp; Source</div>
        {cat.headline
          ? <div className="ep-detail-headline">{cat.headline}</div>
          : <div className="text-faint" style={{fontSize:11.5}}>No verified news — do not treat as an EP without a catalyst.</div>}
        <div className="ep-detail-kv">
          <span>Source</span><span>{cat.source || "—"}</span>
          <span>Type</span><span>{cat.ctype || "—"}</span>
          <span>Status</span><span><EpStatusPill status={cat.status}/></span>
          <span>News age</span><span className="mono">{cat.age_h!=null ? cat.age_h.toFixed(1)+"h" : "—"}</span>
          <span>Last scan</span><span className="mono">{metaTime || "—"}</span>
        </div>
        <div className="ep-detail-title">Price / Volume Evidence</div>
        <div className="ep-detail-kv">
          <span>Price</span><span className="mono">{fmtPrice(c.price)}</span>
          <span>Gap</span><span className={"mono "+pctClass(c.gap_pct||0)}>{c.gap_pct==null?"—":fmtPct(c.gap_pct)}</span>
          <span>1D</span><span className={"mono "+pctClass(c.chg_1d||0)}>{fmtPct(c.chg_1d)}</span>
          <span>From open</span><span className={"mono "+pctClass(c.chg_from_open||0)}>{c.chg_from_open==null?"—":fmtPct(c.chg_from_open)}</span>
          <span>Rel vol</span><span className="mono">{c.volume_ratio==null?"—":c.volume_ratio.toFixed(2)+"x"}</span>
          <span>$ vol</span><span className="mono">{c.dollar_vol==null?"—":"$"+fmtVol(c.dollar_vol)}</span>
          <span>Avg vol</span><span className="mono">{c.avg_volume==null?"—":fmtVol(c.avg_volume)}</span>
        </div>
      </div>
      <div className="ep-detail-col">
        <div className="ep-detail-title">Checklist</div>
        {(c.checklist||[]).length===0 && <div className="text-faint" style={{fontSize:11.5}}>No checklist available.</div>}
        {(c.checklist||[]).map((it,i)=>(
          <div key={i} className="ep-check-row">
            <span className={"dot ep-dot-"+(it.state||"caution")}></span>
            <span className="ep-check-label">{it.label}</span>
            <span className="ep-check-detail">{it.detail}</span>
          </div>
        ))}
        <div className="ep-detail-title">Score Breakdown</div>
        {EP_PART_META.map(([k,label,color])=>{
          const v = Math.max(0, parts[k]||0);
          return (
            <div key={k} className="ep-part-row">
              <span className="ep-part-label">{label}</span>
              <span className="ep-hbar-track"><span className="ep-hbar-fill" style={{width:(v/partTotal*100)+"%", background:color}}></span></span>
              <span className="mono ep-part-val">{v.toFixed(0)}</span>
            </div>
          );
        })}
        {c.sector_bonus!=null && c.sector_bonus!==0 &&
          <div className="ep-part-row">
            <span className="ep-part-label">Sector bonus</span>
            <span className="ep-hbar-track"><span className="ep-hbar-fill" style={{width:Math.min(100,Math.abs(c.sector_bonus))+"%", background:"var(--amber)"}}></span></span>
            <span className="mono ep-part-val">{c.sector_bonus>0?"+":""}{c.sector_bonus}</span>
          </div>}
      </div>
      <div className="ep-detail-col">
        <div className="ep-detail-title">Tags · Penalties · Missing</div>
        <div className="ep-pill-row">
          {(c.tags||[]).map(t=><span key={"t"+t} className="ep-pill tag">{t}</span>)}
          {(c.penalties||[]).map(t=><span key={"p"+t} className="ep-pill penalty">{t}</span>)}
          {(c.missing||[]).map(t=><span key={"m"+t} className="ep-pill missing">{t}</span>)}
          {!(c.tags||[]).length && !(c.penalties||[]).length && !(c.missing||[]).length &&
            <span className="text-faint" style={{fontSize:11.5}}>None</span>}
        </div>
        {c.reject_reason && <div className="ep-reject-reason">Reject reason: {c.reject_reason}</div>}
        <div className="ep-detail-title">Risk Plan</div>
        <div className="ep-detail-kv">
          <span>Invalidation</span><span className="mono">{c.risk_level!=null?fmtPrice(c.risk_level):"—"}</span>
          <span>Resistance (52wH)</span><span className="mono">{hi52!=null?fmtPrice(hi52):"—"}{c.pct_from_52w_high!=null?" ("+fmtPct1(c.pct_from_52w_high)+")":""}</span>
        </div>
        <div className="ep-detail-title">Notes</div>
        <textarea className="ep-notes" value={note} placeholder="Your notes for this candidate…"
          onClick={e=>e.stopPropagation()}
          onChange={e=>onNote(e.target.value)}/>
      </div>
    </div>
  );
}

// --- dense candidate row (click expands the detail drawer) ---
function EpCandidateRow({c, epwl, onChart, rejected, onReject, expanded, onToggle, metaTime, note, onNote}){
  const cat = c.catalyst || {};
  return (
    <div className={"ep-crow"+(rejected?" rejected":"")+(expanded?" open":"")}>
      <div className="ep-crow-main" onClick={onToggle}>
        <span><EpClassBadge cls={c.classification}/></span>
        <span className="ep-c-id">
          <span className="mono fw-700">{c.ticker} <span className="ep-c-name">{c.name || ""}</span></span>
          <span className="ep-c-sec">{c.sector_name || "—"}{c.industry ? " · "+c.industry : ""}</span>
        </span>
        <span className="mono">{fmtPrice(c.price)}</span>
        <span className={"mono "+pctClass(c.chg_1d||0)}>{fmtPct(c.chg_1d)}</span>
        <span className={"mono "+pctClass(c.gap_pct||0)}>{c.gap_pct==null?"—":fmtPct(c.gap_pct)}</span>
        <span className="mono">{c.volume_ratio==null?"—":c.volume_ratio.toFixed(1)+"x"}</span>
        <span className="mono">{c.dollar_vol==null?"—":"$"+fmtVol(c.dollar_vol)}</span>
        <span className="ep-c-cat">
          {cat.headline
            ? <span className="ep-c-headline" title={cat.headline+(cat.source?" — "+cat.source:"")}>{cat.headline}</span>
            : <span className="text-faint" style={{fontSize:10.5}}>No verified news</span>}
          <span><EpStatusPill status={cat.status}/></span>
        </span>
        <span className="ep-c-score"><ScoreBar value={c.ep_score||0}/><span className="mono fw-700 accent">{(c.ep_score||0).toFixed(0)}</span></span>
        <span title="Perf trend 3M→1M→1W→1D"><EpTrendSpark trend={c.trend}/></span>
        <span><EpRangeMicro pos={c.range_pos}/></span>
        <span className="ep-c-flags">
          <span className="dot" title={c.consolidated?"in base / consolidated":"no base"} style={{background: c.consolidated?"var(--green)":"var(--text-faint)"}}></span>
          <span className="text-faint mono" style={{fontSize:10}}>
            {c.dist_ema20!=null? "20E "+fmtPct1(c.dist_ema20):""}{c.dist_ema50!=null? " 50E "+fmtPct1(c.dist_ema50):""}
          </span>
        </span>
        <span className="mono" title="risk level (invalidation)">{c.risk_level!=null? fmtPrice(c.risk_level) : "—"}</span>
        <span className="ep-c-actions" onClick={e=>e.stopPropagation()}>
          <EpWatchBtn epwl={epwl} ticker={c.ticker}/>
          <button className="watch-btn" title="Open chart" onClick={()=>onChart(c.ticker)}><Icon.chart/></button>
          <button className={"watch-btn"+(rejected?" active":"")} title={rejected?"Restore candidate":"Reject (local only)"} onClick={onReject}><Icon.x/></button>
        </span>
      </div>
      {expanded && <EpRowDetail c={c} metaTime={metaTime} note={note} onNote={onNote}/>}
    </div>
  );
}

// --- small svg charts for the EP analytics tab ---
function EpHistogram({data, color="var(--accent)", height=150}){
  if(!data || !data.length) return <div className="empty">No data</div>;
  const max = Math.max(...data.map(d=>d.count), 1);
  return (
    <div className="ep-hist" style={{height}}>
      {data.map((d,i)=>(
        <div key={i} className="ep-hist-col" title={d.bucket.replace("&gt;",">")+": "+d.count}>
          <span className="ep-hist-n">{d.count||""}</span>
          <div className="ep-hist-bar" style={{height: Math.max(2, d.count/max*100)+"%", background:color}}></div>
          <span className="ep-hist-x" dangerouslySetInnerHTML={{__html:d.bucket}}></span>
        </div>
      ))}
    </div>
  );
}

function EpScatter({points, height=260}){
  const pts = (points||[]).filter(p=>p.chg_1d!=null && p.volume_ratio!=null);
  if(!pts.length) return <div className="empty">No data</div>;
  const W=620, H=height, P=34;
  const xs = pts.map(p=>p.chg_1d), ys = pts.map(p=>p.volume_ratio);
  const xMin=Math.min(...xs,0), xMax=Math.max(...xs,1), yMax=Math.max(...ys,1);
  const xFor = v=> P + (v-xMin)/((xMax-xMin)||1)*(W-P*2);
  const yFor = v=> H - P - (v/ (yMax||1))*(H-P*2);
  return (
    <svg width="100%" viewBox={"0 0 "+W+" "+H}>
      <line x1={P} x2={W-P} y1={H-P} y2={H-P} stroke="#1c2027"/>
      <line x1={P} x2={P} y1={P} y2={H-P} stroke="#1c2027"/>
      <text x={W/2} y={H-6} fontSize="10" fill="var(--text-faint)" textAnchor="middle">Move % (1D)</text>
      <text x={10} y={P-8} fontSize="10" fill="var(--text-faint)">Rel Vol x</text>
      <text x={xFor(xMin)} y={H-P+14} fontSize="9" fill="var(--text-faint)">{xMin.toFixed(0)}</text>
      <text x={xFor(xMax)-14} y={H-P+14} fontSize="9" fill="var(--text-faint)">{xMax.toFixed(0)}</text>
      <text x={P-6} y={yFor(yMax)+3} fontSize="9" fill="var(--text-faint)" textAnchor="end">{yMax.toFixed(0)}x</text>
      {pts.map((p,i)=>(
        <circle key={i} cx={xFor(p.chg_1d)} cy={yFor(p.volume_ratio)} r={3+Math.min(6,Math.abs(p.chg_1d||0)/4)}
          fill={epClass(p.classification).color} opacity="0.65">
          <title>{p.ticker} · {fmtPct(p.chg_1d)} · {p.volume_ratio.toFixed(1)}x · {epClass(p.classification).label}</title>
        </circle>
      ))}
    </svg>
  );
}

function EpDonut({rows, size=180}){
  const data = (rows||[]).filter(r=>r.count>0);
  if(!data.length) return <div className="empty">No EP candidates yet</div>;
  const total = data.reduce((a,r)=>a+r.count,0);
  const R=size/2, ir=R*0.55;
  let a0 = -Math.PI/2;
  const arcs = data.map((r,i)=>{
    const frac = r.count/total;
    const a1 = a0 + frac*Math.PI*2;
    const large = frac>0.5?1:0;
    const p = (a,rad)=> (R+rad*Math.cos(a))+","+(R+rad*Math.sin(a));
    const d = "M"+p(a0,R)+" A"+R+","+R+" 0 "+large+" 1 "+p(a1,R)+" L"+p(a1,ir)
      +" A"+ir+","+ir+" 0 "+large+" 0 "+p(a0,ir)+" Z";
    const col = r.color || SEC_YELLOWS[i%SEC_YELLOWS.length];
    a0 = a1;
    return <path key={i} d={d} fill={col} opacity="0.85"><title>{r.name}: {r.count}</title></path>;
  });
  return (
    <div className="flex gap-16 ai-center" style={{flexWrap:"wrap"}}>
      <svg width={size} height={size}>{arcs}
        <text x={R} y={R+4} fontSize="18" fontWeight="700" fill="var(--text)" textAnchor="middle" fontFamily="var(--mono)">{total}</text>
      </svg>
      <div>
        {data.map((r,i)=>(
          <div key={i} className="ep-legend-row">
            <span className="dot" style={{background:r.color||SEC_YELLOWS[i%SEC_YELLOWS.length]}}></span>
            <span>{r.name}</span><span className="mono text-dim">{r.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- EP rankings tab ---
const EP_WL_SORT_KEYS = {
  ticker: r=> r.ticker || "",
  price: r=> r.price ?? -1,
  chg_1d: r=> r.chg_1d ?? -999,
  gap: r=> r.gap_pct ?? -999,
  from_open: r=> r.chg_from_open ?? -999,
  pm: r=> r.pm_chg ?? -999,
  relvol: r=> r.volume_ratio ?? -1,
  dollar_vol: r=> r.dollar_vol ?? -1,
  ep_score: r=> r.ep_score ?? -1,
};

// --- the EP section root ---
function EpSection() {
  const [tab, setTabRaw] = useState(()=>{
    const t = epLoad("tab", "dashboard");
    return EP_TABS.some(([id])=> id===t) ? t : "dashboard";
  });
  const [chartTicker, setChartTicker] = useState(()=> epLoad("chartTicker", null));
  const [chartInterval, setChartInterval] = useState(()=> epLoad("chartInterval", "D"));
  const [scanKey, setScanKey] = useState(0);
  const [data, loading, , err] = useApi("/api/ep-dashboard", [scanKey]);
  const epwl = useEpWatchlist();
  // One shared sort for the EP watchlist: the watchlist table and every chart
  // grid built from it stay in the same order.
  const wlSort = useSortable(()=>0);
  const [wlChartsOn, setWlChartsOn] = useState(false);
  const [chartLayout, updateChartLayout] = useChartLayout();
  const [filters, setFiltersRaw] = useState(()=> Object.assign({}, EP_DEFAULT_FILTERS, epLoad("filters", {})||{}));
  const [rejected, setRejectedRaw] = useState(()=> epLoad("rejected", []));
  const [notes, setNotes] = useState(()=> epLoad("notes", {}));
  const [expanded, setExpanded] = useState(null);

  function goTab(t){ setTabRaw(t); epSave("tab", t); }
  function openChart(t){ setChartTicker(t); epSave("chartTicker", t); goTab("charts"); }
  function setFilters(f){ setFiltersRaw(f); epSave("filters", f); }
  function toggleReject(t){
    const next = rejected.indexOf(t)>=0 ? rejected.filter(x=>x!==t) : rejected.concat([t]);
    setRejectedRaw(next); epSave("rejected", next);
  }
  function setNote(t, v){ const next = Object.assign({}, notes, {[t]:v}); setNotes(next); epSave("notes", next); }

  const cands = useMemo(()=> (data && data.candidates) || [], [data]);
  const byTicker = useMemo(()=>{
    const m = {};
    cands.forEach(c=>{ m[c.ticker] = c; });
    return m;
  }, [cands]);

  // Drop a stale persisted chart ticker (e.g. from an older scan) once data is
  // in: if it's neither a current candidate nor on the EP watchlist, clear it.
  useEffect(()=>{
    if(!data || !chartTicker) return;
    if(!byTicker[chartTicker] && epwl.items.indexOf(chartTicker)<0){
      setChartTicker(null); epSave("chartTicker", null);
    }
  }, [data, chartTicker, byTicker, epwl.items]);

  if(loading) return <div className="page"><div className="loading">Scanning for episodic pivots…</div></div>;
  if(err) return (
    <div className="page">
      <div className="loading error">EP data failed to load: {err}</div>
      <button className="btn primary" onClick={()=>setScanKey(k=>k+1)}>Retry</button>
    </div>
  );
  if(!data) return null;

  const meta = data.meta || {};
  const wlRows = wlSort.apply(epwl.items.map(t=> byTicker[t] || {ticker:t}), EP_WL_SORT_KEYS);

  // --- dashboard derivations ---
  const numF = v=> (v==="" || v===null || v===undefined || isNaN(Number(v))) ? null : Number(v);
  const sectorOpts = [...new Set(cands.map(c=>c.sector_name).filter(Boolean))].sort();
  const ctypeOpts = [...new Set(cands.map(c=> (c.catalyst||{}).ctype).filter(Boolean))].sort();
  const filtered = cands.filter(c=>{
    const cls = c.classification || "momentum";
    if((filters.classes||[]).length && filters.classes.indexOf(cls)<0) return false;
    if(filters.ctype && (c.catalyst||{}).ctype !== filters.ctype) return false;
    if(filters.sector && c.sector_name !== filters.sector) return false;
    if(numF(filters.minCap)!=null && (c.market_cap_musd||0) < numF(filters.minCap)) return false;
    if(numF(filters.minPrice)!=null && (c.price||0) < numF(filters.minPrice)) return false;
    if(numF(filters.minDollarVol)!=null && (c.dollar_vol||0) < numF(filters.minDollarVol)*1e6) return false;
    if(numF(filters.minRelVol)!=null && (c.volume_ratio||0) < numF(filters.minRelVol)) return false;
    if(numF(filters.minGap)!=null && Math.abs(c.gap_pct||0) < numF(filters.minGap)) return false;
    if(numF(filters.minScore)!=null && (c.ep_score||0) < numF(filters.minScore)) return false;
    return true;
  });
  const visible = filtered.filter(c=> rejected.indexOf(c.ticker)<0);
  const rejectedCands = filtered.filter(c=> rejected.indexOf(c.ticker)>=0);
  const noConfirmed = visible.every(c=> c.classification!=="confirmed");
  const histData = (()=>{
    const b = [];
    for(let lo=0; lo<100; lo+=10) b.push({bucket: lo+"–"+(lo+10), count:0});
    cands.forEach(c=>{ const i = Math.min(9, Math.max(0, Math.floor((c.ep_score||0)/10))); b[i].count++; });
    return b;
  })();
  const donutRows = EP_CLASS_ORDER
    .map(cls=>({name:EP_CLASS[cls].label, color:EP_CLASS[cls].color,
      count: cands.filter(c=> (c.classification||"momentum")===cls).length}))
    .filter(r=> r.count>0);

  function renderRow(c, isRejected){
    return (
      <EpCandidateRow key={c.ticker} c={c} epwl={epwl} onChart={openChart}
        rejected={isRejected} onReject={()=>toggleReject(c.ticker)}
        expanded={expanded===c.ticker}
        onToggle={()=>setExpanded(t=> t===c.ticker ? null : c.ticker)}
        metaTime={meta.time} note={notes[c.ticker]||""} onNote={v=>setNote(c.ticker, v)}/>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">EPs — Episodic Pivots</h1>
          <div className="page-subtitle">News-driven institutional repricing candidates — review before adding to watchlist.</div>
          <div className="page-subtitle mono">
            {meta.candidates != null ? meta.candidates : cands.length} candidates · {meta.movers ?? 0} movers scanned · {meta.universe ?? 0} stocks
            {meta.time ? " · last scan "+meta.time : (data.generated_at ? " · "+new Date(data.generated_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : "")}
          </div>
        </div>
        <button className="btn" onClick={()=>setScanKey(k=>k+1)}><Icon.refresh/> Rescan</button>
      </div>

      <div className="toggle-row ep-tabs">
        {EP_TABS.map(([id,label])=>(
          <div key={id} className={"toggle "+(tab===id?"active":"")} onClick={()=>goTab(id)}>
            {label}
          </div>
        ))}
      </div>

      {tab==="dashboard" && (
        <div>
          <EpKpiStrip kpis={data.kpis}/>
          <EpFunnel stages={data.funnel}/>

          <div className="section-title">Analytics</div>
          <div className="ep-analytics-grid">
            <div className="panel">
              <div className="panel-title"><span>EP Score Distribution</span></div>
              <EpHistogram data={histData} color="var(--accent)"/>
            </div>
            <div className="panel">
              <div className="panel-title"><span>Move % vs Relative Volume</span></div>
              <EpScatter points={cands}/>
              <div className="ep-stack-legend">
                {EP_CLASS_ORDER.filter(cls=> cls!=="rejected").map(cls=>(
                  <span key={cls}><span className="dot" style={{background:EP_CLASS[cls].color}}></span>{EP_CLASS[cls].label}</span>
                ))}
              </div>
            </div>
            <div className="panel">
              <div className="panel-title"><span>Score Composition — Top 8</span></div>
              <EpPartsStack cands={cands}/>
            </div>
            <div className="panel">
              <div className="panel-title"><span>Classification Mix</span></div>
              <EpDonut rows={donutRows}/>
            </div>
            <div className="panel">
              <div className="panel-title"><span>Sector Strength</span></div>
              <EpSectorBars sectors={data.sectors}/>
            </div>
            <div className="panel">
              <div className="panel-title"><span>Catalyst Types</span></div>
              <EpCatalystTypes cands={cands}/>
            </div>
          </div>

          <div className="section-title">Candidates ({visible.length}{rejectedCands.length ? " · "+rejectedCands.length+" rejected" : ""})</div>
          <EpFiltersRow filters={filters} onChange={setFilters} sectors={sectorOpts} ctypes={ctypeOpts} scanTime={meta.time}/>
          {noConfirmed && visible.length>0 && <EpEmptyPanel cands={visible}/>}
          <div className="ep-clist">
            {visible.map(c=> renderRow(c, false))}
            {rejectedCands.map(c=> renderRow(c, true))}
          </div>
          {filtered.length===0 && <div className="empty">No candidates match the current filters.</div>}
        </div>
      )}

      {tab==="charts" && (
        <div>
          <div className="panel">
            <div className="panel-title">
              <span style={{display:"inline-flex", alignItems:"center", gap:6}}>
                {chartTicker && <EpWatchBtn epwl={epwl} ticker={chartTicker}/>}
                Chart — {chartTicker || "pick a stock"}
              </span>
              <span className="toggle-row" style={{margin:0}}>
                {["15","60","D","W"].map(iv=>(
                  <div key={iv} className={"toggle "+(chartInterval===iv?"active":"")}
                    onClick={()=>{ setChartInterval(iv); epSave("chartInterval", iv); }}>{iv==="D"?"1D":iv==="W"?"1W":iv+"m"}</div>
                ))}
              </span>
            </div>
            {chartTicker
              ? <TVChart symbol={chartTicker} interval={chartInterval} height={440}/>
              : <div className="empty">Open a chart from any EP card, ranking row, or the watchlist.</div>}
            {chartTicker && byTicker[chartTicker] && byTicker[chartTicker].ema5!=null &&
              <EmaStrip emas={byTicker[chartTicker]} price={byTicker[chartTicker].price}/>}
          </div>

          {epwl.items.length>0 && (
            <div>
              <div className="section-title">EP Watchlist Charts</div>
              <div className="ep-chart-grid">
                {wlRows.map(r=>(
                  <div key={r.ticker} className="panel" style={{padding:10}}>
                    <div style={{display:"flex", alignItems:"center", gap:6, marginBottom:6}}>
                      <EpWatchBtn epwl={epwl} ticker={r.ticker}/>
                      <div className="mono fw-700" style={{cursor:"pointer"}} onClick={()=>openChart(r.ticker)}>{r.ticker}</div>
                    </div>
                    <TVChart symbol={r.ticker} interval={chartInterval} height={240}/>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab==="watchlist" && (
        <div className="panel">
          <div className="panel-title">
            <span>EP Watchlist ({epwl.items.length})</span>
            <span className="hint">Click a column heading to sort descending · click again to restore</span>
          </div>
          {epwl.items.length>0 && (
            <div className="toggle-row" style={{alignItems:"center", justifyContent:"flex-end"}}>
              <Switch on={wlChartsOn} onChange={setWlChartsOn} label="Charts"
                      title="Show TradingView charts for every stock in the list"/>
            </div>
          )}
          {wlChartsOn && epwl.items.length>0 && <ChartLayoutSettings layout={chartLayout} onChange={updateChartLayout}/>}
          {wlChartsOn && epwl.items.length>0 && <StockChartsGrid stocks={wlRows} layout={chartLayout} renderAction={s=><EpWatchBtn epwl={epwl} ticker={s.ticker}/>}/>}
          {epwl.items.length===0 &&
            <div className="empty">EP watchlist is empty — click the ☆ on any EP card to add it here.</div>}
          {epwl.items.length>0 && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>★</th>
                    <SortTh label="Ticker" k="ticker" sort={wlSort}/>
                    <SortTh label="Price" k="price" sort={wlSort}/>
                    <SortTh label="1D" k="chg_1d" sort={wlSort}/>
                    <SortTh label="Gap" k="gap" sort={wlSort}/>
                    <SortTh label="From Open" k="from_open" sort={wlSort}/>
                    <SortTh label="Pre-Mkt" k="pm" sort={wlSort}/>
                    <SortTh label="Rel Vol" k="relvol" sort={wlSort}/>
                    <SortTh label="$ Vol" k="dollar_vol" sort={wlSort}/>
                    <SortTh label="EP Score" k="ep_score" sort={wlSort}/>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {wlRows.map(r=>(
                    <tr key={r.ticker}>
                      <td className="watch-cell"><EpWatchBtn epwl={epwl} ticker={r.ticker}/></td>
                      <td className="mono fw-700">{r.ticker}</td>
                      <td className="mono">{fmtPrice(r.price)}</td>
                      <td className={pctClass(r.chg_1d)}>{fmtPct(r.chg_1d)}</td>
                      <td className={pctClass(r.gap_pct)}>{r.gap_pct==null?"—":fmtPct(r.gap_pct)}</td>
                      <td className={pctClass(r.chg_from_open)}>{r.chg_from_open==null?"—":fmtPct(r.chg_from_open)}</td>
                      <td className={pctClass(r.pm_chg)}>{r.pm_chg==null?"—":fmtPct(r.pm_chg)}</td>
                      <td className="mono">{r.volume_ratio==null?"—":r.volume_ratio.toFixed(2)+"x"}</td>
                      <td className="mono">{r.dollar_vol==null?"—":"$"+fmtVol(r.dollar_vol)}</td>
                      <td className="mono fw-700 accent">{r.ep_score!=null ? r.ep_score.toFixed(1) : "—"}</td>
                      <td><button className="btn" onClick={()=>openChart(r.ticker)}>Chart</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Industry leaderboards — the two-stage 100-point ranking (eligibility
// status gate + Leadership Score) rendered as a perfectly symmetrical grid
// (uniform 6-column layout: row 1 two span-3 cards, row 2 three span-2
// cards, rows 3-4 full-width tables; every card in a row stretches to equal
// height). Data from GET /api/leaderboards (percentile-ranked RS / momentum /
// breadth / trend / rotation / volume / opportunity components, weight
// profiles, four ranked lists). Lives on the Industries page, superseding
// the old leadership snapshot.
// ---------------------------------------------------------------------------
const LEADERBOARD_GRID_CSS = `
.lb-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:16px;align-items:stretch;}
.lb-grid .panel{margin-bottom:0;display:flex;flex-direction:column;}
.lb-grid .panel .table-scroll{flex:1;}
.lb-a{grid-column:span 3;}
.lb-b{grid-column:span 2;}
.lb-full{grid-column:1 / -1;}
.lb-rank-half{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;text-align:center;}
.lb-rank-num{font-size:44px;font-weight:800;font-family:var(--mono);line-height:1;color:var(--accent);}
.lb-rank-name{font-size:16px;font-weight:800;margin:4px 0 2px;}
.lb-mover-row{display:flex;align-items:center;gap:10px;padding:7px 2px;border-bottom:1px solid var(--border);}
.lb-mover-row:last-child{border-bottom:none;}
.lb-mover-rank{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--text-faint);width:20px;text-align:right;}
.lb-mover-name{flex:1;min-width:0;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lb-mover-score{width:110px;flex-shrink:0;}
.lb-mover-val{font-family:var(--mono);font-size:12px;width:34px;text-align:right;color:var(--text-dim);}
.lb-badge{display:inline-block;font-size:9.5px;font-weight:700;font-family:var(--mono);padding:1px 6px;border-radius:2px;letter-spacing:.4px;}
.lb-badge.ok{color:var(--green);background:rgba(0,230,118,0.10);}
.lb-badge.cap{color:var(--amber);background:rgba(255,209,102,0.10);}
.lb-badge.ext{color:var(--red);background:rgba(239,91,91,0.10);}
.lb-badge.pb{color:var(--accent);background:rgba(91,141,239,0.14);}
@media(max-width:1100px){
  .lb-a{grid-column:span 6;}
}
@media(max-width:650px){
  .lb-b{grid-column:span 6;}
}`;

function LeaderboardRankHalf({row, label}){
  if(!row) return (
    <div className="lb-rank-half">
      <div className="section-title" style={{margin:"0 0 10px"}}>{label}</div>
      <div className="empty">No scored industries</div>
    </div>
  );
  return (
    <div className="lb-rank-half">
      <div className="section-title" style={{margin:"0 0 10px"}}>{label}</div>
      <div className="lb-rank-num">#1</div>
      <div className="lb-rank-name">{row.industry}</div>
      <div className="page-subtitle">{row.sector || "—"} · {row.stocks} stocks</div>
      <Gauge value={row.score} label="SCORE"/>
    </div>
  );
}

function IndustryLeaderboards({onSelectIndustry}){
  const [profile, setProfile] = useState("swing");
  const [board, setBoard] = useState("actionable"); // leadership | actionable
  const [expanded, setExpanded] = useState(null);   // industry with open score breakdown
  const [data, loading] = useApi("/api/leaderboards?profile="+profile, [profile]);
  if(loading || !data) return <div className="panel"><div className="loading">Loading leaderboards…</div></div>;

  const rows = data.rows || [];
  const lists = data.lists || {};
  const pullback = data.pullback || [];
  const profiles = data.profiles || [];

  // RRG-style scatter: x = recent momentum component, y = sustained RS
  // component. Dots only — hover a circle to see the industry; colored by sector.
  const rrgRows = rows.map(r=>({industry: r.industry, sector: r.sector,
              x: r.components.recent_mom, y: r.components.sustained_rs}));
  const midRecent = rows.length ? [...rows].sort((a,b)=>a.components.recent_mom-b.components.recent_mom)[Math.floor(rows.length/2)].components.recent_mom : 50;
  const midSus = rows.length ? [...rows].sort((a,b)=>a.components.sustained_rs-b.components.sustained_rs)[Math.floor(rows.length/2)].components.sustained_rs : 50;

  // Eligibility status donut across the scored universe.
  const STATUS_SEGS = [["actionable","Actionable","var(--green)"],["emerging","Emerging","var(--green-soft)"],
                       ["extended","Extended","var(--red)"],["watchlist","Watchlist","var(--amber)"],
                       ["avoid","Avoid","var(--text-dim)"]];
  const statusSegs = STATUS_SEGS.map(([k,label,color])=>({
    label, color, value: rows.filter(r=>r.status===k).length })).filter(s=>s.value>0);

  // Average % extension over the EMA50 by sector (extension risk view).
  const extBySector = {};
  rows.forEach(r=>{
    const s = r.sector || "Other";
    extBySector[s] = extBySector[s] || {sum:0, n:0};
    extBySector[s].sum += (r.ext_ema50||0);
    extBySector[s].n += 1;
  });
  const extRows = Object.entries(extBySector)
    .map(([label, v])=>({label, value: Math.round(v.sum/v.n*10)/10, color:"var(--amber)"}))
    .sort((a,b)=> b.value-a.value).slice(0,6);

  const BOARDS = [
    ["leadership", "Leadership", r=>r.leadership_score,
     "Leadership Score (0-100): percentile-ranked sustained RS / recent momentum / breadth / trend / rotation / volume / opportunity, weighted by the selected profile"],
    ["actionable", "Actionable Now", r=>r.actionable_score,
     "0.65 × Leadership + 0.35 × Opportunity — actionable leaders only (extended leaders excluded)"],
  ];
  const cur = BOARDS.find(b=>b[0]===board) || BOARDS[0];
  const boardRows = board==="actionable"
    ? (lists.actionable||[])
    : [...rows].sort((a,b)=> cur[2](b)-cur[2](a) || a.industry.localeCompare(b.industry)).slice(0,15);

  const COMP_LABELS = {sustained_rs:"RS", recent_mom:"Recent", breadth:"Breadth",
                       trend:"Trend", rotation:"Rotation", volume:"Volume", opportunity:"Opportunity"};
  const confClass = c=> c==="High"?"conf-hi":c==="Medium"?"conf-md":"conf-lo";
  const fmtRankChg = v=> v==null ? "—" : (v>0?"+":"")+v;
  const breakdownText = r=>{
    const parts = Object.entries(r.breakdown||{}).map(([k,v])=> (COMP_LABELS[k]||k)+" "+v.points+"/"+v.max);
    if(r.mom_bonus) parts.push("+"+r.mom_bonus+" momentum bonus");
    return r.leadership_score.toFixed(0)+" = "+parts.join(" · ");
  };
  const top10Actionable = (lists.actionable||[]).slice(0,10);

  return (
    <div>
      <style>{LEADERBOARD_GRID_CSS}</style>
      <div className="tabs" style={{marginBottom:16}}>
        {profiles.map(p=>(
          <div key={p.id} className={"tab "+(profile===p.id?"active":"")} onClick={()=>setProfile(p.id)}>
            {p.label}
          </div>
        ))}
      </div>
      <div className="lb-grid">
        <div className="panel lb-a">
          <div className="panel-title">
            <span>Sustained RS vs Recent Momentum</span>
            <span className="hint">x: recent momentum percentile · y: sustained RS percentile</span>
          </div>
          <RRGDots rows={rrgRows} midX={midRecent} midY={midSus}
            labels={{tr:"LEADING", tl:"FADING", bl:"LAGGING", br:"EMERGING"}}
            onSelect={onSelectIndustry}/>
        </div>
        <div className="panel lb-a">
          <div className="panel-title">
            <span>Actionable Now</span>
            <span className="hint">top 10 by actionable score</span>
          </div>
          {top10Actionable.length===0 && <div className="empty">No scored industries</div>}
          <div style={{flex:1, display:"flex", flexDirection:"column"}}>
            {top10Actionable.map((r,i)=>(
              <div key={r.industry} className={"lb-mover-row "+(onSelectIndustry?"hover-row":"")}
                   style={{cursor:onSelectIndustry?"pointer":undefined, flex:1, display:"flex", alignItems:"center"}}
                   onClick={onSelectIndustry? ()=>onSelectIndustry(r.industry, null) : undefined}>
                <span className="lb-mover-rank">{i+1}</span>
                <span className="lb-mover-name">{r.industry}</span>
                {r.pattern.detected && <span className="lb-badge pb">PB</span>}
                <span className="lb-mover-score"><ScoreBar value={r.actionable_score}/></span>
                <span className="lb-mover-val">{r.actionable_score.toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="panel lb-b">
          <div className="panel-title"><span>Eligibility Status</span></div>
          <div style={{flex:1, display:"flex", alignItems:"center", justifyContent:"center"}}>
            <Donut segments={statusSegs} size={150} thickness={22} centerLabel={String(rows.length)}/>
          </div>
        </div>
        <div className="panel lb-b">
          <div className="panel-title"><span>Extension by Sector</span></div>
          <div style={{flex:1, display:"flex", alignItems:"center", justifyContent:"center"}}>
            <HBars rows={extRows} width={420} rowH={24} padL={150} padR={48} fmt={v=>v.toFixed(1)+"%"}/>
          </div>
        </div>
        <div className="panel lb-b">
          <div className="panel-title"><span>#1 Leaders</span></div>
          <div style={{flex:1, display:"flex", gap:16, alignItems:"flex-start", justifyContent:"space-around", flexWrap:"wrap"}}>
            <LeaderboardRankHalf row={(lists.leadership||[])[0]} label="Leadership"/>
            <LeaderboardRankHalf row={(lists.actionable||[])[0]} label="Actionable Now"/>
          </div>
        </div>
        <div className="panel lb-full">
          <div className="panel-title">
            <span>Industry Rankings</span>
            <span className="hint">{cur[3]}</span>
          </div>
          <div className="tabs" style={{marginBottom:12}}>
            {BOARDS.map(b=>(
              <div key={b[0]} className={"tab "+(board===b[0]?"active":"")} onClick={()=>setBoard(b[0])}>
                {b[1]}
              </div>
            ))}
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Industry</th><th>Sector</th>
                  <th title={cur[3]}>Score</th>
                  <th title="Opportunity score: 100 = constructive pullback near the 10/20EMA, lower = extended or breaking down">Opp</th>
                  <th title="Leading / Emerging / Fading / Lagging / Recovering">State</th>
                  <th title="Eligibility: Actionable / Emerging / Extended / Watchlist / Avoid">Status</th>
                  <th title="Confidence from constituent count and breadth coverage">Conf</th>
                  <th title="Leadership rank change vs 5 snapshots ago (positive = improved)">Rk Δ5</th>
                  <th title="Leadership rank change vs 20 snapshots ago (positive = improved)">Rk Δ20</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {boardRows.length===0 && (
                  <tr><td colSpan="11" className="text-faint">No industries qualify for this list right now.</td></tr>
                )}
                {boardRows.map((r,i)=>(
                  <React.Fragment key={r.industry}>
                    <tr onClick={onSelectIndustry? ()=>onSelectIndustry(r.industry, null) : undefined}
                        className={onSelectIndustry?"hover-row":""}>
                      <td className="mono text-faint">{i+1}</td>
                      <td className="fw-700">{r.industry}</td>
                      <td className="text-dim">{r.sector || "—"}</td>
                      <td style={{minWidth:110}} onClick={e=>{e.stopPropagation(); setExpanded(expanded===r.industry?null:r.industry);}}>
                        <div style={{display:"flex", alignItems:"center", gap:8, cursor:"pointer"}}
                             title="Click for the score breakdown">
                          <div style={{flex:1}}><ScoreBar value={cur[2](r)}/></div>
                          <span className="mono" style={{fontSize:12}}>{cur[2](r).toFixed(0)}</span>
                        </div>
                      </td>
                      <td className="mono">{r.opportunity_score.toFixed(0)}</td>
                      <td><span className={"state-badge "+stateClass(r.state.toLowerCase())}>{r.state}</span></td>
                      <td><StatusBadge status={r.status}/></td>
                      <td className={confClass(r.confidence)}>{r.confidence}</td>
                      <td className={"mono "+(r.rank_chg_5d==null?"text-faint":pctClass(r.rank_chg_5d))}>{fmtRankChg(r.rank_chg_5d)}</td>
                      <td className={"mono "+(r.rank_chg_20d==null?"text-faint":pctClass(r.rank_chg_20d))}>{fmtRankChg(r.rank_chg_20d)}</td>
                      <td><ReasonChips reasons={r.reasons}/></td>
                    </tr>
                    {expanded===r.industry && (
                      <tr><td colSpan="11" className="mono text-dim" style={{fontSize:11, padding:"6px 12px"}}>
                        {breakdownText(r)}
                      </td></tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="panel lb-full">
          <div className="panel-title">
            <span>MA-Pullback Leaders</span>
            <span className="hint">green-candle pullback into the EMA10–EMA20 zone within the last 5 sessions · body &gt; 1.6× avg · close in top 25% of range · vol &gt; 1.2×</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Industry</th><th>Sector</th><th>Signal Date</th>
                  <th title="Candle body / 20-day average body">Body ×</th>
                  <th title="Close position within the candle range (1 = at the high)">Close Pos</th>
                  <th title="Volume / 20-day average volume">Vol ×</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {pullback.length===0 && (
                  <tr><td colSpan="8" className="text-faint">No MA-pullback signals detected in the last 5 sessions.</td></tr>
                )}
                {pullback.map((r,i)=>(
                  <tr key={r.industry}
                      onClick={onSelectIndustry? ()=>onSelectIndustry(r.industry, null) : undefined}
                      className={onSelectIndustry?"hover-row":""}>
                    <td className="mono text-faint">{i+1}</td>
                    <td className="fw-700">{r.industry}</td>
                    <td className="text-dim">{r.sector || "—"}</td>
                    <td className="mono">{r.pattern.date || "—"}</td>
                    <td className="mono">{r.pattern.body_ratio==null?"—":r.pattern.body_ratio.toFixed(2)+"x"}</td>
                    <td className="mono">{r.pattern.close_pos==null?"—":r.pattern.close_pos.toFixed(2)}</td>
                    <td className="mono">{r.pattern.vol_ratio==null?"—":r.pattern.vol_ratio.toFixed(2)+"x"}</td>
                    <td className="mono fw-700">{r.leadership_score.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
function App() {
  const [view, setView] = useState("dashboard"); // dashboard | sectors | etf | sector | industry
  const [sectorId, setSectorId] = useState(null);
  const [industry, setIndustry] = useState(null);
  const [industrySectorId, setIndustrySectorId] = useState(null); // sector the industry was opened from (Back target)
  const [sidebarOpen, setSidebarOpen] = useState(()=>window.innerWidth>720);
  const [theme, setTheme] = useState(()=>document.documentElement.dataset.theme==="light"?"light":"dark");
  const [strategy, setStrategy] = useState("qullamaggie"); // qullamaggie
  const [dashboard, dashLoading] = useApi(apiUrl("/api/dashboard", strategy), [strategy]);
  const [config] = useApi("/api/config", []);
  const [syncStatus, setSyncStatus] = useState(null);
  const [showSyncPanel, setShowSyncPanel] = useState(false);
  const [polling, setPolling] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const wl = useWatchlist(refreshKey);

  function fetchStatus(){
    fetch("/api/sync/status").then(r=>r.json()).then(setSyncStatus);
  }

  useEffect(()=>{ fetchStatus(); }, []);

  useEffect(()=>{
    document.documentElement.dataset.theme=theme;
    const meta=document.querySelector('meta[name="theme-color"]');
    if(meta) meta.setAttribute("content", theme==="dark"?"#0d0f12":"#f5f2ec");
    try{ localStorage.setItem("rc-theme",theme); }catch(e){}
  },[theme]);

  useEffect(()=>{
    if(!polling) return;
    const id = setInterval(()=>{
      fetch("/api/sync/status").then(r=>r.json()).then(s=>{
        setSyncStatus(s);
        if(!s.running){ setPolling(false); setRefreshKey(k=>k+1); }
      });
    }, 1500);
    return ()=> clearInterval(id);
  },[polling]);

  function doRefresh(){
    fetch("/api/refresh", {method:"POST"}).then(()=> setRefreshKey(k=>k+1));
  }

  function doSync(){
    setShowSyncPanel(true);
    fetch("/api/sync", {method:"POST"}).then(r=>r.json()).then(()=>{ setPolling(true); fetchStatus(); });
  }

  function onSelectSector(id){
    setSectorId(id);
    setView("sector");
  }

  function onSelectIndustry(name, fromSectorId){
    setIndustry(name);
    setIndustrySectorId(fromSectorId!=null ? fromSectorId : null);
    setView("industry");
  }

  function onIndustryBack(){
    if(industrySectorId!=null){
      setSectorId(industrySectorId);
      setIndustry(null);
      setIndustrySectorId(null);
      setView("sector");
    } else {
      setIndustry(null);
      setView("dashboard");
    }
  }

  function onNavigate(id){
    setSectorId(null);
    setIndustry(null);
    setIndustrySectorId(null);
    setView(id);
  }

  const dashboardData = dashboard ? {...dashboard, refreshKey} : null;

  return (
    <ThemeContext.Provider value={theme}>
      <div className="app">
        <Sidebar open={sidebarOpen} setOpen={setSidebarOpen} current={view} onNavigate={onNavigate}/>
        <div className={"main "+(sidebarOpen?"sidebar-open":"sidebar-collapsed")}>
          <TopBar
            mode={dashboardData?.mode || "demo"}
            lastSynced={dashboardData?.last_synced}
            market={dashboardData?.market_summary}
            marketHistory={dashboardData?.market_history}
            onSync={doSync}
            onRefresh={doRefresh}
            syncing={syncStatus?.running || false}
            strategy={strategy}
            onStrategy={setStrategy}
            theme={theme}
            onToggleTheme={()=>setTheme(t=>t==="dark"?"light":"dark")}
          />
          <main className="content">
            {dashLoading && <div className="loading">Loading…</div>}
            {!dashLoading && view==="dashboard" && <Dashboard data={dashboardData} onSelectSector={onSelectSector} onSelectIndustry={onSelectIndustry} config={config}/>}
            {!dashLoading && view==="sectors" && dashboardData && <AllSectorsPage sectors={dashboardData.sectors} onSelectSector={onSelectSector} onSelectIndustry={onSelectIndustry} strategy={strategy}/>}
            {!dashLoading && view==="industries" && <IndustriesPage onSelectIndustry={onSelectIndustry} strategy={strategy} wl={wl}/>}
            {!dashLoading && view==="etf" && <ETFHubView/>}
            {!dashLoading && view==="watchlist" && <WatchlistPage wl={wl}/>}
            {view==="ep" && <EpSection/>}
            {!dashLoading && view==="screener" && <ScreenerView strategy={strategy} wl={wl}/>}
            {!dashLoading && view==="sector" && <SectorDetail sectorId={sectorId} onBack={()=>setView("dashboard")} onSelectIndustry={onSelectIndustry} strategy={strategy} wl={wl}/>}
            {!dashLoading && view==="industry" && <IndustryDetail industry={industry} onBack={onIndustryBack} onSelectSector={onSelectSector} strategy={strategy} wl={wl}/>}
          </main>
        </div>
        {showSyncPanel && <SyncPanel status={syncStatus} onClose={()=>setShowSyncPanel(false)}/>}
      </div>
    </ThemeContext.Provider>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
