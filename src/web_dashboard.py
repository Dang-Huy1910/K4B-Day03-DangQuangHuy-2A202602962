"""Zero-dependency web dashboard for the LIMS Extraction ReAct Agent.

Run with: python src/web_dashboard.py
Then open: http://localhost:8000
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlparse

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
sys.path.append(SRC_DIR)

from app import load_test_cases, run_react_agent, run_test_suite, save_waterfall_trace
from mcp_server import MCPLIMSServer
from providers import get_llm_provider
from tools import execute_query_extraction_lot, reset_mock_database


HOST = os.getenv("DASHBOARD_HOST", "localhost")
PORT = int(os.getenv("DASHBOARD_PORT", "8000"))
PROVIDER = get_llm_provider()
MCP_SERVER = MCPLIMSServer()
AGENT_LOCK = Lock()


def _trace_data() -> list:
    trace_path = os.path.join(PROJECT_ROOT, "docs", "trace_waterfall.json")
    try:
        with open(trace_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _lot_data() -> dict:
    payload = json.loads(execute_query_extraction_lot("LOT-EXT-2026-01"))
    return payload.get("data", {})


DASHBOARD_HTML = r'''<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0B0F17">
  <title>Helix Control · LIMS Extraction Agent</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
    :root {
      --bg: #0B0F17; --surface: #111827; --surface-2: #172033; --raised: #1E293B;
      --line: rgba(255,255,255,.075); --line-strong: rgba(255,255,255,.13);
      --text: #E8EEF8; --muted: #8D9AB0; --dim: #5E6B80;
      --emerald: #10B981; --rose: #FB7185; --amber: #F59E0B;
      --cyan: #22D3EE; --violet: #A78BFA; --radius: 18px;
      --ease: cubic-bezier(.16,1,.3,1);
    }
    * { box-sizing: border-box; }
    html { color-scheme: dark; }
    body { margin: 0; min-height: 100vh; color: var(--text); background: var(--bg); font: 14px/1.5 Inter, system-ui, sans-serif; }
    body::before { content:""; position:fixed; inset:0; z-index:-1; pointer-events:none; background:radial-gradient(circle at 18% -5%,rgba(34,211,238,.075),transparent 29%),radial-gradient(circle at 90% 18%,rgba(16,185,129,.05),transparent 25%); }
    button, textarea { font: inherit; }
    button { color: inherit; }
    button:focus-visible, textarea:focus-visible { outline: 2px solid rgba(34,211,238,.6); outline-offset: 2px; }
    .shell { width:min(1500px, calc(100% - 48px)); margin:auto; padding:24px 0 56px; }
    .topbar { display:flex; align-items:center; justify-content:space-between; min-height:52px; margin-bottom:28px; }
    .brand { display:flex; align-items:center; gap:12px; }
    .mark { width:36px; height:36px; border:1px solid rgba(34,211,238,.28); display:grid; place-items:center; border-radius:10px; background:rgba(34,211,238,.06); box-shadow:inset 0 1px rgba(255,255,255,.1); }
    .mark svg { width:21px; color:var(--cyan); }
    .brand-name { font-weight:700; letter-spacing:-.02em; }
    .brand-sub { color:var(--muted); font-size:11px; letter-spacing:.12em; text-transform:uppercase; }
    .live { display:flex; align-items:center; gap:9px; color:#B7C3D5; font:500 11px JetBrains Mono, monospace; letter-spacing:.08em; text-transform:uppercase; }
    .live-dot { position:relative; width:8px; height:8px; border-radius:50%; background:var(--emerald); box-shadow:0 0 12px var(--emerald); }
    .live-dot::after { content:""; position:absolute; inset:-5px; border:1px solid rgba(16,185,129,.35); border-radius:50%; animation:pulse 2s infinite; }
    @keyframes pulse { 50% { transform:scale(1.35); opacity:0; } }
    .hero { display:flex; align-items:end; justify-content:space-between; gap:24px; margin-bottom:24px; }
    .eyebrow, .label { color:var(--muted); font-size:10px; font-weight:700; letter-spacing:.13em; text-transform:uppercase; }
    h1 { margin:5px 0 4px; font-size:clamp(26px,3vw,40px); line-height:1.08; letter-spacing:-.045em; }
    .hero p { margin:0; color:var(--muted); max-width:680px; }
    .operator { text-align:right; font-family:JetBrains Mono,monospace; color:#AAB6C8; font-size:12px; }
    .operator b { display:block; color:var(--text); font-weight:500; }
    .metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
    .metric { min-height:108px; padding:18px; border:1px solid var(--line); background:rgba(17,24,39,.72); box-shadow:inset 0 1px rgba(255,255,255,.06); border-radius:14px; }
    .metric-top { display:flex; justify-content:space-between; align-items:center; }
    .metric-icon { color:var(--dim); font:600 11px JetBrains Mono,monospace; }
    .metric-value { margin-top:13px; font:600 24px/1 JetBrains Mono,monospace; letter-spacing:-.04em; font-variant-numeric:tabular-nums; }
    .metric-note { margin-top:7px; color:var(--muted); font-size:11px; }
    .workspace { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(340px,.6fr); gap:16px; align-items:start; }
    .panel { border:1px solid var(--line); background:rgba(17,24,39,.82); backdrop-filter:blur(14px); border-radius:var(--radius); box-shadow:inset 0 1px rgba(255,255,255,.07); overflow:hidden; }
    .panel-head { min-height:65px; padding:16px 20px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .panel-title { font-weight:650; letter-spacing:-.015em; }
    .panel-kicker { color:var(--muted); font-size:11px; margin-top:2px; }
    .badge { display:inline-flex; align-items:center; gap:6px; border:1px solid; border-radius:999px; padding:5px 9px; font:600 10px JetBrains Mono,monospace; letter-spacing:.04em; white-space:nowrap; }
    .badge::before { content:""; width:5px; height:5px; border-radius:50%; background:currentColor; box-shadow:0 0 8px currentColor; }
    .badge-progress { color:#67E8F9; border-color:rgba(34,211,238,.2); background:rgba(34,211,238,.07); }
    .plate-wrap { padding:24px; }
    .plate-meta { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:18px; }
    .plate-id { font:600 13px JetBrains Mono,monospace; }
    .legend { display:flex; flex-wrap:wrap; gap:12px; color:var(--muted); font-size:10px; }
    .legend span { display:flex; gap:5px; align-items:center; }
    .legend i { width:7px; height:7px; border-radius:50%; display:inline-block; }
    .plate-frame { position:relative; padding:30px 28px 24px 34px; border:1px solid var(--line-strong); border-radius:28px; background:#0D1420; box-shadow:inset 0 0 0 5px rgba(255,255,255,.015),inset 0 20px 50px rgba(0,0,0,.24); }
    .plate-grid { display:grid; grid-template-columns:repeat(8,minmax(36px,1fr)); gap:clamp(8px,1.15vw,15px); }
    .well { position:relative; aspect-ratio:1; min-width:0; border:1px solid rgba(255,255,255,.08); border-radius:50%; background:#141E2D; cursor:pointer; transition:transform 180ms var(--ease),border-color 180ms,background 260ms; box-shadow:inset 0 3px 7px rgba(0,0,0,.5),inset 0 -1px rgba(255,255,255,.05); }
    .well:hover { transform:translateY(-2px) scale(1.04); border-color:rgba(255,255,255,.24); }
    .well:active { transform:scale(.97); }
    .well.empty { cursor:default; opacity:.42; }
    .well.passed { color:var(--emerald); background:rgba(16,185,129,.16); border-color:rgba(16,185,129,.38); box-shadow:inset 0 3px 8px rgba(0,0,0,.46),0 0 13px rgba(16,185,129,.1); }
    .well.low_yield { color:var(--amber); background:rgba(245,158,11,.17); border-color:rgba(245,158,11,.45); box-shadow:inset 0 3px 8px rgba(0,0,0,.46),0 0 15px rgba(245,158,11,.13); }
    .well.failed { color:var(--rose); background:rgba(251,113,133,.17); border-color:rgba(251,113,133,.52); box-shadow:inset 0 3px 8px rgba(0,0,0,.46),0 0 17px rgba(251,113,133,.17); animation:failFlash .75s var(--ease); }
    @keyframes failFlash { 0% { background:rgba(251,113,133,.62); transform:scale(1.08); } }
    .well-code { position:absolute; inset:0; display:grid; place-items:center; font:600 clamp(8px,1vw,11px) JetBrains Mono,monospace; }
    .well-label { position:absolute; top:-17px; left:50%; transform:translateX(-50%); color:var(--dim); font:500 8px JetBrains Mono,monospace; }
    .well-row { position:absolute; left:-20px; top:50%; transform:translateY(-50%); color:var(--dim); font:500 9px JetBrains Mono,monospace; }
    .inspector { min-height:74px; margin-top:18px; padding:13px 15px; border:1px solid var(--line); background:rgba(30,41,59,.45); border-radius:10px; display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .inspect-main { font:600 12px JetBrains Mono,monospace; }
    .inspect-sub { color:var(--muted); font-size:11px; margin-top:4px; }
    .status-text { font:600 11px JetBrains Mono,monospace; }
    .passed-text { color:var(--emerald); } .failed-text { color:var(--rose); } .low_yield-text { color:var(--amber); }
    .console-body { padding:18px; }
    textarea { width:100%; min-height:112px; resize:vertical; border:1px solid var(--line-strong); border-radius:12px; padding:13px 14px; color:var(--text); background:#0D1420; line-height:1.55; transition:border-color 150ms; }
    textarea::placeholder { color:#657188; }
    textarea:hover { border-color:rgba(255,255,255,.2); }
    .quick { display:flex; gap:7px; flex-wrap:wrap; margin:12px 0 16px; }
    .chip { border:1px solid var(--line); border-radius:7px; background:var(--surface-2); padding:6px 9px; color:#A9B5C7; font:600 10px JetBrains Mono,monospace; cursor:pointer; transition:all 150ms var(--ease); }
    .chip:hover { color:var(--cyan); border-color:rgba(34,211,238,.27); background:rgba(34,211,238,.07); }
    .chip:active { transform:scale(.97); }
    .actions { display:grid; grid-template-columns:1fr auto; gap:8px; }
    .button { border:1px solid transparent; border-radius:10px; min-height:42px; padding:0 15px; font-weight:650; cursor:pointer; transition:all 150ms var(--ease); }
    .button:hover { transform:translateY(-1px); }
    .button:active { transform:scale(.98); }
    .button:disabled { opacity:.4; pointer-events:none; }
    .button-primary { color:#06242A; background:var(--cyan); box-shadow:0 0 20px rgba(34,211,238,.12); }
    .button-secondary { border-color:var(--line-strong); background:var(--surface-2); }
    .suite { padding:16px 18px 18px; border-top:1px solid var(--line); }
    .suite-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:11px; }
    .progress-track { height:4px; border-radius:4px; overflow:hidden; background:#263246; }
    .progress-fill { height:100%; width:0; background:var(--emerald); box-shadow:0 0 10px rgba(16,185,129,.5); transition:width 300ms var(--ease); }
    .suite-results { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin-top:12px; }
    .test-pill { height:31px; display:grid; place-items:center; border:1px solid var(--line); border-radius:7px; color:var(--dim); background:#0F1724; font:600 9px JetBrains Mono,monospace; }
    .test-pill.pass { color:var(--emerald); border-color:rgba(16,185,129,.24); background:rgba(16,185,129,.07); }
    .trace { grid-column:1/-1; margin-top:0; }
    .trace-tools { display:flex; gap:8px; }
    .icon-button { width:34px; height:34px; border:1px solid var(--line); border-radius:8px; background:var(--surface-2); cursor:pointer; color:var(--muted); }
    .icon-button:hover { color:var(--text); border-color:var(--line-strong); }
    .timeline { padding:8px 20px 24px; }
    .empty-state { padding:44px 20px; text-align:center; color:var(--muted); }
    .trace-group { position:relative; padding:17px 0 4px 42px; }
    .trace-group::before { content:""; position:absolute; left:15px; top:0; bottom:-4px; width:1px; background:var(--line-strong); }
    .trace-step { position:absolute; left:3px; top:20px; width:25px; height:25px; display:grid; place-items:center; border:1px solid var(--line-strong); border-radius:50%; background:var(--bg); color:var(--muted); font:600 9px JetBrains Mono,monospace; }
    .trace-card { margin-bottom:8px; border:1px solid var(--line); border-left:2px solid; border-radius:9px; padding:12px 14px; background:rgba(13,20,32,.72); }
    .trace-card.thought { border-left-color:var(--violet); } .trace-card.action { border-left-color:#38BDF8; } .trace-card.observation { border-left-color:var(--emerald); } .trace-card.final { border-left-color:#F8FAFC; box-shadow:inset 0 0 22px rgba(255,255,255,.025); }
    .trace-title { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:5px; color:#CCD6E5; font-size:11px; font-weight:650; }
    .trace-title span:first-child { letter-spacing:.08em; text-transform:uppercase; }
    .trace-content { color:#A9B5C7; font-size:12px; }
    .thought .trace-content { font-style:italic; color:#B8A8E8; }
    .tool-name { color:#7DD3FC; font:600 12px JetBrains Mono,monospace; }
    details { margin-top:9px; }
    summary { width:max-content; color:var(--muted); cursor:pointer; font-size:10px; }
    pre { overflow:auto; margin:9px 0 0; padding:12px; border:1px solid var(--line); border-radius:7px; background:#080D14; color:#B9C7D9; font:10px/1.6 JetBrains Mono,monospace; }
    .latency { color:var(--muted); font:500 10px JetBrains Mono,monospace; font-variant-numeric:tabular-nums; }
    .toast { position:fixed; right:24px; bottom:24px; max-width:360px; padding:12px 15px; border:1px solid var(--line-strong); border-radius:10px; background:#182235; box-shadow:0 16px 40px rgba(0,0,0,.4); transform:translateY(20px); opacity:0; pointer-events:none; transition:all 220ms var(--ease); }
    .toast.show { transform:none; opacity:1; }
    @media (max-width:1000px) { .workspace { grid-template-columns:1fr; } .trace { grid-column:auto; } .metrics { grid-template-columns:repeat(2,1fr); } }
    @media (max-width:620px) { .shell { width:calc(100% - 24px); padding-top:14px; } .hero { display:block; } .operator { text-align:left; margin-top:15px; } .metrics { grid-template-columns:1fr 1fr; } .metric { min-height:96px; padding:14px; } .plate-wrap { padding:14px; } .plate-frame { padding:26px 16px 18px 25px; border-radius:20px; } .plate-grid { grid-template-columns:repeat(8,minmax(25px,1fr)); gap:6px; } .legend { display:none; } .topbar .live span:last-child { display:none; } }
  </style>
</head>
<body>
  <main class="shell">
    <nav class="topbar">
      <div class="brand"><div class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M7 3c6 4 4 14 10 18M17 3C11 7 13 17 7 21M8.5 6h7M7.5 11h9M7.5 16h9"/></svg></div><div><div class="brand-name">Helix Control</div><div class="brand-sub">LIMS Extraction Agent</div></div></div>
      <div class="live"><i class="live-dot"></i><span id="providerName">MCP ONLINE</span><span>· JSON-RPC 2.0</span></div>
    </nav>
    <section class="hero"><div><div class="eyebrow">Extraction operations / Live overview</div><h1>Precision at every well.</h1><p>Tác tử ReAct giám sát DNA yield, thực thi QC qua MCP và bảo toàn tính toàn vẹn của từng lô tách chiết.</p></div><div class="operator"><span>OPERATOR</span><b>LabTech-2A202602962</b></div></section>
    <section class="metrics">
      <article class="metric"><div class="metric-top"><span class="label">Lot status</span><span class="metric-icon">01</span></div><div class="metric-value" id="mStatus">—</div><div class="metric-note" id="mProtocol">Đang đồng bộ</div></article>
      <article class="metric"><div class="metric-top"><span class="label">Occupied wells</span><span class="metric-icon">02</span></div><div class="metric-value" id="mWells">—</div><div class="metric-note">Capacity · 48 wells</div></article>
      <article class="metric"><div class="metric-top"><span class="label">Mean DNA yield</span><span class="metric-icon">03</span></div><div class="metric-value" id="mYield">—</div><div class="metric-note">SOP threshold · ≥ 10.0 ng/µL</div></article>
      <article class="metric"><div class="metric-top"><span class="label">QC exceptions</span><span class="metric-icon">04</span></div><div class="metric-value" id="mExceptions">—</div><div class="metric-note" id="mExceptionNote">Low yield + failed</div></article>
    </section>
    <section class="workspace">
      <article class="panel">
        <header class="panel-head"><div><div class="panel-title">QIAvac Tray Visualizer</div><div class="panel-kicker" id="trayName">Loading instrument map…</div></div><span class="badge badge-progress" id="lotBadge">IN PROGRESS</span></header>
        <div class="plate-wrap"><div class="plate-meta"><span class="plate-id">LOT-EXT-2026-01</span><div class="legend"><span><i style="background:var(--emerald)"></i>PASSED</span><span><i style="background:var(--amber)"></i>LOW YIELD</span><span><i style="background:var(--rose)"></i>FAILED</span></div></div><div class="plate-frame"><div class="plate-grid" id="plateGrid"></div></div><div class="inspector" id="inspector"><div><div class="inspect-main">Select a populated well</div><div class="inspect-sub">Yield, specimen type and QC reason will appear here.</div></div></div></div>
      </article>
      <aside class="panel">
        <header class="panel-head"><div><div class="panel-title">ReAct Operator Console</div><div class="panel-kicker">Natural language · controlled execution</div></div><span class="badge badge-progress">READY</span></header>
        <div class="console-body"><label class="label" for="query">Technician instruction</label><textarea id="query" placeholder="Ví dụ: Kiểm tra lô LOT-EXT-2026-01 và xử lý mẫu dưới ngưỡng SOP…"></textarea><div class="quick" id="quickPrompts"></div><div class="actions"><button class="button button-primary" id="sendBtn">Run ReAct agent</button><button class="button button-secondary" id="resetBtn" title="Khôi phục dữ liệu mock">Reset</button></div></div>
        <div class="suite"><div class="suite-head"><span class="label">Acceptance suite</span><span class="latency" id="suiteScore">0 / 5</span></div><div class="progress-track"><div class="progress-fill" id="progress"></div></div><div class="suite-results" id="suiteResults"></div><button class="button button-secondary" id="suiteBtn" style="width:100%;margin-top:12px">Run all five test cases</button></div>
      </aside>
      <article class="panel trace"><header class="panel-head"><div><div class="panel-title">ReAct Waterfall Trace</div><div class="panel-kicker">Thought → Action → Observation → Final Answer</div></div><div class="trace-tools"><button class="icon-button" id="refreshBtn" title="Refresh trace">↻</button><button class="icon-button" id="copyBtn" title="Copy trace JSON">⧉</button></div></header><div class="timeline" id="timeline"></div></article>
    </section>
  </main>
  <div class="toast" id="toast"></div>
  <script>
    const el = id => document.getElementById(id);
    let state = { lot: {}, traces: [], tests: [] };
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const pretty = obj => JSON.stringify(obj, null, 2);
    const toast = message => { el('toast').textContent = message; el('toast').classList.add('show'); setTimeout(() => el('toast').classList.remove('show'), 2600); };
    async function api(path, options={}) { const res = await fetch(path, {headers:{'Content-Type':'application/json'},...options}); const data = await res.json(); if(!res.ok) throw new Error(data.error || 'Request failed'); return data; }
    function renderMetrics() {
      const lot=state.lot, samples=lot.samples||[], sum=lot.summary||{};
      el('mStatus').textContent=(lot.status||'—').replace('_',' '); el('mProtocol').textContent=lot.protocol||'No protocol';
      el('mWells').textContent=`${samples.length} / ${lot.capacity||48}`;
      const mean=samples.length ? samples.reduce((n,s)=>n+Number(s.yield_ng_ul||0),0)/samples.length : 0;
      el('mYield').textContent=`${mean.toFixed(1)} ng/µL`; const exceptions=(sum.low_yield||0)+(sum.failed||0);
      el('mExceptions').textContent=String(exceptions).padStart(2,'0'); el('mExceptionNote').textContent=`${sum.low_yield||0} low yield · ${sum.failed||0} failed`;
      el('trayName').textContent=`${lot.tray||'—'} · ${lot.protocol||'—'}`; el('lotBadge').textContent=(lot.status||'UNKNOWN').replace('_',' ');
    }
    function renderInspector(sample) {
      if(!sample) return;
      const reason=sample.failure_reason ? ` · ${esc(sample.failure_reason)}` : '';
      el('inspector').innerHTML=`<div><div class="inspect-main">${esc(sample.well)} · ${esc(sample.sample_id)}</div><div class="inspect-sub">${esc(sample.sample_type)} · DNA yield <b>${esc(sample.yield_ng_ul)} ng/µL</b>${reason}</div></div><div class="status-text ${sample.status.toLowerCase()}-text">● ${esc(sample.status.replace('_',' '))}</div>`;
    }
    function renderPlate() {
      const map=new Map((state.lot.samples||[]).map(s=>[s.well,s])); let html='';
      for(let r=0;r<6;r++) for(let c=1;c<=8;c++){ const well=`${String.fromCharCode(65+r)}${c}`, s=map.get(well); const cls=s?s.status.toLowerCase():'empty'; const title=s?`${s.sample_id} · ${s.yield_ng_ul} ng/µL · ${s.status}${s.failure_reason?' · '+s.failure_reason:''}`:`${well} · Empty`;
        html+=`<button class="well ${cls}" data-well="${well}" title="${esc(title)}" ${s?'':'disabled'}><span class="well-label">${r===0?c:''}</span><span class="well-row">${c===1?String.fromCharCode(65+r):''}</span><span class="well-code">${s?esc(s.sample_id.replace('SMP-','')):''}</span></button>`; }
      el('plateGrid').innerHTML=html; document.querySelectorAll('.well:not(.empty)').forEach(node=>node.onclick=()=>renderInspector(map.get(node.dataset.well)));
      const priority=(state.lot.samples||[]).find(s=>s.status==='FAILED')||(state.lot.samples||[]).find(s=>s.status==='LOW_YIELD')||(state.lot.samples||[])[0]; renderInspector(priority);
    }
    function traceCard(type,title,content,meta='',raw=null){ return `<div class="trace-card ${type}"><div class="trace-title"><span>${title}</span><span class="latency">${meta}</span></div><div class="trace-content">${content}</div>${raw?`<details><summary>Inspect payload</summary><pre>${esc(pretty(raw))}</pre></details>`:''}</div>`; }
    function renderTrace() {
      const traces=state.traces||[]; if(!traces.length){el('timeline').innerHTML='<div class="empty-state">No trace recorded yet.<br>Run a prompt to inspect the agent decision path.</div>';return;}
      el('timeline').innerHTML=traces.map(t=>{ let cards=traceCard('thought','◈ Thought',esc(t.thought||'Evaluate next step'));
        if(t.action_type==='TOOL_EXECUTION'){cards+=traceCard('action','⌁ Action',`<span class="tool-name">${esc(t.tool_name)}</span>`,`${Number(t.llm_latency_ms||0).toFixed(2)} ms`,t.arguments); const status=t.observation?.status||'UNKNOWN'; cards+=traceCard('observation',`◎ Observation · ${esc(status)}`,esc(t.observation?.message||'Structured MCP response'),`${Number(t.tool_latency_ms||0).toFixed(2)} ms`,t.observation);}
        else cards+=traceCard('final','⚑ Final Answer',esc(t.output||'').replace(/\n/g,'<br>'),`${Number(t.latency_ms||0).toFixed(2)} ms`);
        return `<section class="trace-group"><span class="trace-step">${t.step}</span>${cards}</section>`; }).join('');
    }
    function renderTests(results=[]) { const byId=new Map(results.map(r=>[r.id,r])); el('suiteResults').innerHTML=(state.tests||[]).map(t=>`<div class="test-pill ${byId.get(t.id)?.passed?'pass':''}" title="${esc(t.type)}">${t.id}${byId.get(t.id)?.passed?' ✓':''}</div>`).join(''); }
    function renderAll(){renderMetrics();renderPlate();renderTrace();renderTests();el('providerName').textContent=`${state.provider||'MCP'} ONLINE`;el('quickPrompts').innerHTML=(state.tests||[]).map(t=>`<button class="chip" data-id="${t.id}" title="${esc(t.question)}">${t.id}</button>`).join('');document.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{const t=state.tests.find(x=>x.id===b.dataset.id);el('query').value=t.question;el('query').focus();});}
    async function refresh(){try{state=await api('/api/state');renderAll();}catch(e){toast(e.message);}}
    el('sendBtn').onclick=async()=>{const query=el('query').value.trim();if(!query){toast('Nhập chỉ dẫn cho tác tử trước khi chạy.');return;}el('sendBtn').disabled=true;el('sendBtn').textContent='Agent is reasoning…';try{const data=await api('/api/agent',{method:'POST',body:JSON.stringify({query})});state.lot=data.lot;state.traces=data.traces;renderMetrics();renderPlate();renderTrace();toast('ReAct cycle completed.');}catch(e){toast(e.message);}finally{el('sendBtn').disabled=false;el('sendBtn').textContent='Run ReAct agent';}};
    el('suiteBtn').onclick=async()=>{el('suiteBtn').disabled=true;el('suiteBtn').textContent='Running acceptance suite…';let p=4;el('progress').style.width='4%';const timer=setInterval(()=>{p=Math.min(88,p+7);el('progress').style.width=p+'%';},240);try{const data=await api('/api/tests',{method:'POST',body:'{}'});clearInterval(timer);el('progress').style.width='100%';state.lot=data.lot;state.traces=data.report.traces;renderMetrics();renderPlate();renderTrace();renderTests(data.report.results);el('suiteScore').textContent=`${data.report.passed} / ${data.report.total}`;toast(`${data.report.passed}/${data.report.total} test cases passed.`);}catch(e){clearInterval(timer);toast(e.message);}finally{el('suiteBtn').disabled=false;el('suiteBtn').textContent='Run all five test cases';}};
    el('resetBtn').onclick=async()=>{const data=await api('/api/reset',{method:'POST',body:'{}'});state.lot=data.lot;state.traces=[];el('suiteScore').textContent='0 / 5';el('progress').style.width='0';renderMetrics();renderPlate();renderTrace();renderTests();toast('Mock LIMS state restored.');};
    el('refreshBtn').onclick=refresh; el('copyBtn').onclick=async()=>{await navigator.clipboard.writeText(pretty(state.traces));toast('Trace JSON copied.');};
    el('query').addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter')el('sendBtn').click();}); refresh();
  </script>
</body></html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    """Small JSON API and static document handler."""

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 1_000_000)
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self._send_json(
                {
                    "lot": _lot_data(),
                    "traces": _trace_data(),
                    "tests": load_test_cases(),
                    "provider": PROVIDER.__class__.__name__,
                }
            )
        else:
            self._send_json({"error": "Endpoint not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()
        try:
            with AGENT_LOCK:
                if path == "/api/agent":
                    query = str(payload.get("query", "")).strip()
                    if not query:
                        self._send_json({"error": "Trường query không được để trống."}, 400)
                        return
                    traces = run_react_agent(query, PROVIDER, MCP_SERVER, verbose=False)
                    save_waterfall_trace(traces)
                    self._send_json({"traces": traces, "lot": _lot_data()})
                elif path == "/api/tests":
                    report = run_test_suite(PROVIDER, MCP_SERVER, reset_state=True, verbose=False)
                    self._send_json({"report": report, "lot": _lot_data()})
                elif path == "/api/reset":
                    reset_mock_database()
                    save_waterfall_trace([])
                    self._send_json({"status": "SUCCESS", "lot": _lot_data()})
                else:
                    self._send_json({"error": "Endpoint not found"}, 404)
        except Exception as exc:
            self._send_json({"error": f"Dashboard operation failed: {exc}"}, 500)

    def log_message(self, format: str, *args) -> None:
        print(f"🌐 {self.address_string()} · {format % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print("=" * 66)
    print("🧬 HELIX CONTROL · LIMS EXTRACTION DASHBOARD")
    print("=" * 66)
    print(f"✅ Dashboard: http://{HOST}:{PORT}")
    print(f"🔌 Provider:  {PROVIDER.__class__.__name__}")
    print("⏹️  Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Dashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
