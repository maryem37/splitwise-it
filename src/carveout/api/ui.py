"""Self-contained interactive Web UI served by FastAPI — Unified Demo Platform."""

WEB_UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carve-out Copilot — Unified Decision Intelligence Platform</title>
<style>
  :root {
    --bg:#f1f5f9; --card:#ffffff; --tx:#0f172a; --mu:#64748b; --bd:#e2e8f0;
    --ac:#2563eb; --ac-dk:#1d4ed8; --ok:#059669; --ok-bg:#ecfdf5;
    --warn:#d97706; --warn-bg:#fffbeb; --bad:#dc2626; --bad-bg:#fef2f2;
  }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--tx); }
  header {
    background:#0f172a; color:#fff; padding:12px 24px;
    display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;
  }
  header h1 { margin:0; font-size:18px; display:flex; align-items:center; gap:8px; }
  .subtitle { color:#94a3b8; font-size:12px; font-weight:400; }
  .flow-banner {
    background:#1e293b; color:#e2e8f0; padding:10px 24px; font-size:12px;
    display:flex; gap:16px; align-items:center; flex-wrap:wrap; border-bottom:1px solid #334155;
  }
  .flow-step { display:flex; align-items:center; gap:6px; }
  .flow-badge { background:#334155; color:#93c5fd; padding:2px 8px; border-radius:4px; font-weight:700; font-size:11px; }
  .wrap { max-width:1360px; margin:16px auto; padding:0 16px; }
  .tabs { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
  .tabs button {
    padding:9px 16px; border-radius:8px; border:1px solid var(--bd);
    background:var(--card); cursor:pointer; font-weight:600; color:var(--tx); transition:0.15s;
  }
  .tabs button:hover { border-color:var(--ac); color:var(--ac); }
  .tabs button.active { background:var(--ac); color:#fff; border-color:var(--ac); }
  .card { background:var(--card); border:1px solid var(--bd); border-radius:10px; padding:18px; margin-bottom:16px; box-shadow:0 1px 2px rgba(0,0,0,0.03); }
  .hide { display:none; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin-bottom:16px; }
  .kpi { background:#f8fafc; padding:14px; border-radius:8px; border:1px solid var(--bd); }
  .kpi b { display:block; font-size:22px; color:var(--tx); }
  .kpi span { color:var(--mu); font-size:12px; }
  input, select, textarea { padding:8px 10px; border:1px solid var(--bd); border-radius:6px; font:inherit; background:#fff; }
  button.primary { background:var(--ac); color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:600; }
  button.primary:hover { background:var(--ac-dk); }
  button.success { background:var(--ok); color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:600; }
  button.danger { background:var(--bad); color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:600; }
  button.secondary { background:#e2e8f0; color:var(--tx); border:none; padding:8px 14px; border-radius:6px; cursor:pointer; font-weight:600; }
  .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; }
  .b-ok { background:var(--ok-bg); color:var(--ok); }
  .b-warn { background:var(--warn-bg); color:var(--warn); }
  .b-bad { background:var(--bad-bg); color:var(--bad); }
  .b-info { background:#eff6ff; color:var(--ac); }
  table { width:100%; border-collapse:collapse; margin-top:10px; font-size:13px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--bd); }
  th { background:#f8fafc; color:var(--mu); font-weight:700; font-size:12px; text-transform:uppercase; }
  .alert { padding:10px 14px; border-radius:8px; margin-bottom:8px; border-left:4px solid var(--bad); background:var(--bad-bg); font-size:13px; }
  .alert-warn { border-left-color:var(--warn); background:var(--warn-bg); }
  .alert-ok { border-left-color:var(--ok); background:var(--ok-bg); }
  .pill { display:inline-block; background:#e2e8f0; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; margin:2px; }
  pre { background:#0f172a; color:#e2e8f0; padding:12px; border-radius:8px; overflow-x:auto; font-size:12px; white-space:pre-wrap; }
  .prose { background:#f8fafc; border:1px solid var(--bd); border-radius:8px; padding:16px; white-space:pre-wrap; font-family:inherit; line-height:1.6; }
  iframe.dash-frame { width:100%; height:780px; border:1px solid var(--bd); border-radius:8px; background:#fff; }
  .chart-box { background:#f8fafc; border:1px solid var(--bd); border-radius:8px; padding:16px; margin:12px 0; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Carve-out Copilot <span class="subtitle">Unified IT Separation &amp; Decision Intelligence Platform</span></h1>
  </div>
  <div style="display:flex;gap:8px;align-items:center;">
    <select id="portfolio-select" onchange="onPortfolioChange()">
      <option value="portfolio_v1">Nordia Retail (v1)</option>
      <option value="portfolio_v2">Nordia Retail (v2)</option>
      <option value="portfolio_v3">Helios Utilities (v3)</option>
    </select>
    <button class="primary" onclick="loadPortfolio()">Refresh</button>
  </div>
</header>

<div class="flow-banner">
  <div class="flow-step"><span class="flow-badge">INPUT</span> <code>data/portfolio_v1.yaml</code> (30 assets, dependencies, TSA &amp; licences)</div>
  <span>&rarr;</span>
  <div class="flow-step"><span class="flow-badge">ENGINE</span> NetworkX Graph + OR-Tools CP-SAT + LangGraph AI Agents</div>
  <span>&rarr;</span>
  <div class="flow-step"><span class="flow-badge">OUTPUT</span> Waves, Dependency Graph, Gantt, Cost Optimization (-$290k) &amp; Audit Report</div>
</div>

<div class="wrap">
  <div class="tabs">
    <button class="active" onclick="showTab('visual', this)">1. Visual Dashboard (Graph &amp; Gantt)</button>
    <button onclick="showTab('overview', this)">2. Input &amp; Output Data</button>
    <button onclick="showTab('workflow', this)">3. AI Agents (Workflow)</button>
    <button onclick="showTab('decision', this)">4. Optimization &amp; Charts</button>
    <button onclick="showTab('review', this)">5. Human Review</button>
    <button onclick="showTab('reports', this)">6. Audit Report</button>
  </div>

  <!-- TAB 1: VISUAL DASHBOARD -->
  <div id="tab-visual" class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
      <div>
        <h2 style="margin:0;">Interactive Visual Dashboard</h2>
        <span style="color:var(--mu);font-size:12px;">Click any asset node in the graph to inspect dependencies, Gantt schedule, risks, and TSA cost breakdown.</span>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="primary" onclick="setFrame('/dashboard?portfolio_id=' + pid())">Wave Graph &amp; Gantt</button>
        <button class="secondary" onclick="setFrame('/graph')">Force-Directed Network</button>
      </div>
    </div>
    <iframe id="dash-iframe" class="dash-frame" src="/dashboard?portfolio_id=portfolio_v1"></iframe>
  </div>

  <!-- TAB 2: INPUT & OUTPUT DATA -->
  <div id="tab-overview" class="card hide">
    <h2 style="margin-top:0;">Portfolio Summary (Input &rarr; Computed Plan)</h2>
    <div id="overview-kpis" class="grid"></div>
    <div id="overview-alerts"></div>
    <div style="display:grid;grid-template-columns:1fr;gap:16px;">
      <div>
        <h3>Migration Waves (Output)</h3>
        <div id="waves-table"></div>
      </div>
      <div>
        <h3>Portfolio Assets (Input)</h3>
        <div id="assets-table"></div>
      </div>
    </div>
    <details style="margin-top:16px;">
      <summary style="cursor:pointer;color:var(--mu);font-weight:600;">Show Raw JSON (Technical)</summary>
      <pre id="overview-json">Loading...</pre>
    </details>
  </div>

  <!-- TAB 3: AI AGENTS WORKFLOW -->
  <div id="tab-workflow" class="card hide">
    <h2 style="margin-top:0;">LangGraph Multi-Agent Investigation</h2>
    <p style="color:var(--mu);margin-top:0;">Run Dependency, Strategy, Risk, Optimization, Evaluation &amp; Critic agents with SQLite persistence.</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px;">
      <input id="wf-query" style="flex:1;min-width:260px" value="Investigate APP-06 delay and optimize" />
      <input id="wf-thread" placeholder="Auto-generated thread_id" style="width:200px" />
      <label style="display:flex;align-items:center;gap:4px;"><input type="checkbox" id="wf-human" checked /> Human Review</label>
      <button class="primary" onclick="launchWorkflow(true)">Launch New Run</button>
      <button class="secondary" onclick="checkStatus()">Check Status</button>
    </div>
    <div id="wf-badges" style="margin-bottom:12px;"></div>
    <div id="wf-narrative" class="prose hide"></div>
    <details style="margin-top:10px;" open>
      <summary style="cursor:pointer;color:var(--mu);font-weight:600;">Workflow Telemetry &amp; State</summary>
      <pre id="wf-output">No workflow launched yet. Click "Launch New Run" above.</pre>
    </details>
  </div>

  <!-- TAB 4: DECISION INTELLIGENCE & CHARTS -->
  <div id="tab-decision" class="card hide">
    <h2 style="margin-top:0;">CP-SAT Optimization &amp; What-If Scenarios</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <input id="exp-asset" value="APP-06" style="width:110px" />
      <button class="primary" onclick="explainAsset()">Explain Asset</button>
      <button class="primary" onclick="comparePlans()">Compare Baseline vs Optimized</button>
      <button class="primary" onclick="runDelayScenario()">Simulate APP-06 +12w Delay</button>
    </div>
    <div id="decision-visual">
      <div class="alert alert-ok">Click <b>Compare Baseline vs Optimized</b> or <b>Simulate APP-06 +12w Delay</b> to see cost charts and wave shifts.</div>
    </div>
    <details style="margin-top:12px;">
      <summary style="cursor:pointer;color:var(--mu);font-weight:600;">Show Raw JSON (Technical)</summary>
      <pre id="decision-output">Select an action above.</pre>
    </details>
  </div>

  <!-- TAB 5: HUMAN REVIEW -->
  <div id="tab-review" class="card hide">
    <h2 style="margin-top:0;">Human-in-the-Loop Approval</h2>
    <p style="color:var(--mu);margin-top:0;">Approve or reject a paused workflow saved in SQLite.</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
      <input id="rev-thread" placeholder="Paused Thread ID" style="width:200px" />
      <input id="rev-user" value="web_reviewer" placeholder="Reviewer" style="width:160px" />
      <input id="rev-comment" placeholder="Approval comment (e.g. Approved for Q3)" style="flex:1;min-width:200px" />
      <button class="success" onclick="resumeWorkflow('APPROVE')">APPROVE</button>
      <button class="danger" onclick="resumeWorkflow('REJECT')">REJECT</button>
    </div>
    <div id="review-status"></div>
    <div id="review-report" class="prose hide"></div>
    <details style="margin-top:10px;">
      <summary style="cursor:pointer;color:var(--mu);font-weight:600;">Show Raw JSON (Technical)</summary>
      <pre id="review-output">Launch a workflow with Human Review checked, then approve or reject it here.</pre>
    </details>
  </div>

  <!-- TAB 6: AUDIT REPORT -->
  <div id="tab-reports" class="card hide">
    <h2 style="margin-top:0;">Executive Decision &amp; Audit Report</h2>
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
      <button class="primary" onclick="fetchReport('markdown')">Generate Readable Report (Markdown)</button>
      <button class="secondary" onclick="fetchReport('json')">Inspect Full Audit JSON</button>
    </div>
    <div id="report-formatted" class="prose">Click a button above to generate the report.</div>
    <pre id="report-output" class="hide"></pre>
  </div>
</div>

<script>
function showTab(name, btn) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ['visual','overview','workflow','decision','review','reports'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hide', t !== name);
  });
}
function pid() { return document.getElementById('portfolio-select').value; }
function setFrame(url) { document.getElementById('dash-iframe').src = url; }
function onPortfolioChange() {
  loadPortfolio();
  setFrame('/dashboard?portfolio_id=' + pid());
}

async function loadPortfolio() {
  const res = await fetch('/api/portfolios/' + pid());
  const data = await res.json();
  document.getElementById('overview-kpis').innerHTML = `
    <div class="kpi"><b>${data.asset_count}</b><span>Assets (Input)</span></div>
    <div class="kpi"><b>${data.wave_count}</b><span>Migration Waves</span></div>
    <div class="kpi"><b>${data.conflict_count}</b><span>Active Conflicts</span></div>
    <div class="kpi"><b>${data.cycle_count}</b><span>Dependency Cycles</span></div>
    <div class="kpi"><b>$${(data.estimated_tsa_cost_total/1e6).toFixed(2)}M</b><span>Est. TSA Cost</span></div>
    <div class="kpi"><b>${data.latest_planned_completion}</b><span>Latest Completion</span></div>
  `;

  let alertsHtml = '';
  (data.cycles || []).forEach(c => {
    alertsHtml += `<div class="alert alert-warn"><b>Circular Dependency:</b> ${c.join(' &harr; ')} (must migrate together in the same wave)</div>`;
  });
  (data.conflicts || []).forEach(c => {
    alertsHtml += `<div class="alert"><b>Conflict (${c.type}):</b> ${c.asset_id} &mdash; ${c.message || ('Expires ' + c.expiry + ', planned ' + c.planned_completion)}</div>`;
  });
  document.getElementById('overview-alerts').innerHTML = alertsHtml;

  let wHtml = '<table><tr><th>Wave</th><th>Start</th><th>Completion</th><th>Assets</th></tr>';
  (data.waves || []).forEach(w => {
    const pills = w.assets.map(a => `<span class="pill">${a}</span>`).join('');
    wHtml += `<tr><td><b>Wave ${w.wave}</b></td><td>${w.planned_start}</td><td>${w.planned_completion}</td><td>${pills}</td></tr>`;
  });
  wHtml += '</table>';
  document.getElementById('waves-table').innerHTML = wHtml;

  let aHtml = '<table><tr><th>ID</th><th>Name</th><th>Type</th><th>Owner</th><th>Criticality</th></tr>';
  (data.assets || []).forEach(a => {
    aHtml += `<tr><td><b>${a.id}</b></td><td>${a.name}</td><td>${a.type}</td><td>${a.owner}</td><td>${a.criticality}/5</td></tr>`;
  });
  aHtml += '</table>';
  document.getElementById('assets-table').innerHTML = aHtml;
  document.getElementById('overview-json').textContent = JSON.stringify(data, null, 2);
}

async function launchWorkflow(fresh) {
  if (fresh) { document.getElementById('wf-thread').value = ''; }
  document.getElementById('wf-output').textContent = 'Running LangGraph agents and CP-SAT optimizer... please wait (~15s)...';
  document.getElementById('wf-narrative').classList.add('hide');
  const body = {
    portfolio_id: pid(),
    user_request: document.getElementById('wf-query').value,
    thread_id: document.getElementById('wf-thread').value || null,
    human_review: document.getElementById('wf-human').checked,
  };
  const res = await fetch('/api/workflows', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await res.json();
  if (data.thread_id) {
    document.getElementById('wf-thread').value = data.thread_id;
    document.getElementById('rev-thread').value = data.thread_id;
  }
  renderWorkflowBadges(data);
  document.getElementById('wf-output').textContent = JSON.stringify(data, null, 2);
}

async function checkStatus() {
  const tid = document.getElementById('wf-thread').value;
  if (!tid) return alert('Enter a thread_id or click Launch New Run');
  const res = await fetch('/api/workflows/' + tid + '/status');
  const data = await res.json();
  renderWorkflowBadges(data);
  document.getElementById('wf-output').textContent = JSON.stringify(data, null, 2);
}

function renderWorkflowBadges(d) {
  if (d.detail) {
    document.getElementById('wf-badges').innerHTML = `<div class="alert">${d.detail}</div>`;
    return;
  }
  const stClass = d.workflow_status === 'interrupted' ? 'b-warn' : (d.workflow_status === 'approved' || d.workflow_status === 'completed' ? 'b-ok' : 'b-info');
  document.getElementById('wf-badges').innerHTML = `
    <span class="badge ${stClass}">Status: ${d.workflow_status}</span>
    <span class="badge b-info">Approval: ${d.approval_status}</span>
    <span class="badge b-info">Eval: ${d.evaluation_status || 'N/A'}</span>
    <span class="badge b-warn">Critic: ${d.critic_decision || 'N/A'}</span>
    ${d.interrupted ? '<div class="alert alert-warn" style="margin-top:8px;"><b>Paused for Human Review:</b> Go to tab <b>5. Human Review</b> to Approve or Reject thread <code>' + d.thread_id + '</code>.</div>' : ''}
  `;
  if (d.final_response) {
    document.getElementById('wf-narrative').textContent = d.final_response;
    document.getElementById('wf-narrative').classList.remove('hide');
  }
}

async function explainAsset() {
  const aid = document.getElementById('exp-asset').value;
  const res = await fetch(`/api/assets/${aid}/explanation?portfolio_id=${pid()}`);
  const d = await res.json();
  document.getElementById('decision-output').textContent = JSON.stringify(d, null, 2);
  if (d.detail) {
    document.getElementById('decision-visual').innerHTML = `<div class="alert">${d.detail}</div>`;
    return;
  }
  document.getElementById('decision-visual').innerHTML = `
    <div class="grid">
      <div class="kpi"><b>${d.asset_id}</b><span>${d.asset_name}</span></div>
      <div class="kpi"><b>Wave ${d.assigned_wave}</b><span>${d.planned_start} &rarr; ${d.planned_completion}</span></div>
      <div class="kpi"><b>${d.strategy}</b><span>Exit Strategy</span></div>
      <div class="kpi"><b>${(d.scc_members || []).length > 1 ? d.scc_members.join(' &harr; ') : 'None'}</b><span>Circular Coupling</span></div>
    </div>
    <div class="alert alert-ok"><b>Why Wave ${d.assigned_wave}?</b> ${d.placement_rationale}</div>
    <table>
      <tr><th>Move Earlier</th><td>${d.move_consequences?.move_earlier || ''}</td></tr>
      <tr><th>Move Later</th><td>${d.move_consequences?.move_later || ''}</td></tr>
      <tr><th>Blocking Dependencies</th><td>${(d.blocking_dependencies || []).join(', ') || 'None'}</td></tr>
    </table>
  `;
}

function renderCostChart(items) {
  const maxCost = Math.max(...items.map(i => i.cost), 1);
  let bars = items.map((it, idx) => {
    const w = Math.round((it.cost / maxCost) * 420);
    return `
      <g transform="translate(0, ${idx * 44})">
        <text x="0" y="18" font-size="12" font-weight="600" fill="#0f172a">${it.label}</text>
        <rect x="210" y="4" width="${w}" height="22" rx="4" fill="${it.color}"></rect>
        <text x="${218 + w}" y="19" font-size="12" font-weight="700" fill="#0f172a">$${(it.cost/1e6).toFixed(2)}M (${it.waves} waves)</text>
      </g>
    `;
  }).join('');
  return `<div class="chart-box"><b>TSA Cost &amp; Wave Comparison</b><svg width="100%" height="${items.length * 44 + 10}" style="margin-top:8px;">${bars}</svg></div>`;
}

async function comparePlans() {
  const res = await fetch(`/api/comparisons?portfolio_id=${pid()}&scenario=minimize_cost`);
  const d = await res.json();
  document.getElementById('decision-output').textContent = JSON.stringify(d, null, 2);
  const b = d.baseline, o = d.optimized;
  const chart = renderCostChart([
    { label: 'Deterministic Baseline', cost: b.tsa_cost, waves: b.total_waves, color: '#64748b' },
    { label: 'CP-SAT Optimized', cost: o.tsa_cost, waves: o.total_waves, color: '#059669' },
  ]);
  let rows = (d.moved_assets || []).map(m =>
    `<tr><td><b>${m.asset_id}</b> ${m.asset_name}</td><td>Wave ${m.baseline_wave}</td><td>Wave ${m.optimized_wave}</td><td><span class="badge ${m.wave_delta < 0 ? 'b-ok' : 'b-warn'}">${m.wave_delta > 0 ? '+' + m.wave_delta : m.wave_delta}</span></td></tr>`
  ).join('');
  document.getElementById('decision-visual').innerHTML = `
    <div class="grid">
      <div class="kpi"><b>$${(b.tsa_cost/1e6).toFixed(2)}M</b><span>Baseline TSA Cost (${b.total_waves} waves)</span></div>
      <div class="kpi"><b>$${(o.tsa_cost/1e6).toFixed(2)}M</b><span>Optimized TSA Cost (${o.total_waves} waves)</span></div>
      <div class="kpi"><b style="color:var(--ok)">$${(d.tsa_cost_delta/1000).toFixed(0)}k</b><span>Net Savings</span></div>
      <div class="kpi"><b>${o.conflicts_count}</b><span>Optimized Conflicts (was ${b.conflicts_count})</span></div>
    </div>
    ${chart}
    <p>${d.tradeoff_analysis}</p>
    <table><tr><th>Moved Asset</th><th>Baseline</th><th>Optimized</th><th>Delta</th></tr>${rows}</table>
  `;
}

async function runDelayScenario() {
  const body = { portfolio_id: pid(), scenario_id: 'app_06_delay', scenario_name: 'APP-06 12w Delay', delay_weeks: {'APP-06': 12, 'APP-07': 12} };
  const res = await fetch('/api/scenarios', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const d = await res.json();
  document.getElementById('decision-output').textContent = JSON.stringify(d, null, 2);
  const chart = renderCostChart([
    { label: 'Optimized Baseline', cost: d.baseline_tsa_cost, waves: d.total_waves, color: '#2563eb' },
    { label: 'APP-06 +12w Delay', cost: d.scenario_tsa_cost, waves: d.total_waves, color: '#dc2626' },
  ]);
  document.getElementById('decision-visual').innerHTML = `
    <div class="grid">
      <div class="kpi"><b>$${(d.baseline_tsa_cost/1e6).toFixed(2)}M</b><span>Baseline (${d.baseline_completion})</span></div>
      <div class="kpi"><b>$${(d.scenario_tsa_cost/1e6).toFixed(2)}M</b><span>12w Delay (${d.scenario_completion})</span></div>
      <div class="kpi"><b style="color:var(--bad)">+$${(d.tsa_cost_delta/1000).toFixed(0)}k</b><span>Cost Impact</span></div>
      <div class="kpi"><b>${d.affected_assets.join(', ')}</b><span>Coupled Assets</span></div>
    </div>
    ${chart}
    <div class="alert alert-warn">${d.impact_summary}</div>
  `;
}

async function resumeWorkflow(action) {
  const tid = document.getElementById('rev-thread').value;
  if (!tid) return alert('Enter a paused thread_id');
  const body = { action, reviewer: document.getElementById('rev-user').value, comment: document.getElementById('rev-comment').value };
  const res = await fetch(`/api/workflows/${tid}/resume`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const d = await res.json();
  document.getElementById('review-output').textContent = JSON.stringify(d, null, 2);
  if (d.detail) {
    document.getElementById('review-status').innerHTML = `<div class="alert">${d.detail}</div>`;
    return;
  }
  document.getElementById('review-status').innerHTML = `<div class="alert alert-ok"><b>Decision Submitted:</b> Thread <code>${d.thread_id}</code> is now <b>${d.workflow_status}</b> (${d.approval_status}).</div>`;
  if (d.final_response) {
    document.getElementById('review-report').textContent = d.final_response;
    document.getElementById('review-report').classList.remove('hide');
  }
}

async function fetchReport(fmt) {
  const res = await fetch(`/api/reports/${pid()}?format=${fmt}`);
  if (fmt === 'markdown') {
    const txt = await res.text();
    document.getElementById('report-formatted').textContent = txt;
    document.getElementById('report-formatted').classList.remove('hide');
    document.getElementById('report-output').classList.add('hide');
  } else {
    const txt = JSON.stringify(await res.json(), null, 2);
    document.getElementById('report-output').textContent = txt;
    document.getElementById('report-output').classList.remove('hide');
    document.getElementById('report-formatted').classList.add('hide');
  }
}

loadPortfolio();
</script>
</body>
</html>
"""
