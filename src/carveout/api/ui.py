"""Self-contained interactive Web UI served by FastAPI."""

WEB_UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carve-out Copilot — Decision Intelligence Platform</title>
<style>
  :root { --bg:#f4f6f9; --card:#fff; --tx:#172334; --mu:#64748b; --bd:#dbe1e8; --ac:#2563eb; --ok:#059669; --warn:#d97706; --bad:#dc2626; }
  body { margin:0; font:14px/1.5 system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--tx); }
  header { background:#0f172a; color:#fff; padding:14px 24px; display:flex; justify-content:space-between; align-items:center; }
  header h1 { margin:0; font-size:18px; }
  .wrap { max-width:1200px; margin:20px auto; padding:0 16px; }
  .tabs { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
  .tabs button { padding:8px 16px; border-radius:8px; border:1px solid var(--bd); background:var(--card); cursor:pointer; font-weight:600; }
  .tabs button.active { background:var(--ac); color:#fff; border-color:var(--ac); }
  .card { background:var(--card); border:1px solid var(--bd); border-radius:10px; padding:16px; margin-bottom:16px; }
  .hide { display:none; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px; }
  .kpi { background:var(--bg); padding:12px; border-radius:8px; border:1px solid var(--bd); }
  .kpi b { display:block; font-size:20px; }
  .kpi span { color:var(--mu); font-size:12px; }
  input, select, textarea { padding:8px; border:1px solid var(--bd); border-radius:6px; font:inherit; }
  button.primary { background:var(--ac); color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:600; }
  button.danger { background:var(--bad); color:#fff; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:600; }
  pre { background:#0f172a; color:#e2e8f0; padding:12px; border-radius:8px; overflow-x:auto; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>Carve-out Copilot</h1>
  <div>
    <select id="portfolio-select"><option value="portfolio_v1">Nordia Retail (v1)</option></select>
    <button class="primary" onclick="loadPortfolio()">Refresh</button>
  </div>
</header>
<div class="wrap">
  <div class="tabs">
    <button class="active" onclick="showTab('overview', this)">Portfolio Overview</button>
    <button onclick="showTab('workflow', this)">Workflow Monitoring</button>
    <button onclick="showTab('decision', this)">Decision Intelligence</button>
    <button onclick="showTab('review', this)">Human Review</button>
    <button onclick="showTab('reports', this)">Reports</button>
  </div>

  <div id="tab-overview" class="card">
    <h2>Portfolio Overview</h2>
    <div id="overview-kpis" class="grid"></div>
    <pre id="overview-json">Loading portfolio...</pre>
  </div>

  <div id="tab-workflow" class="card hide">
    <h2>Launch & Monitor LangGraph Workflow</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
      <input id="wf-query" style="flex:1;min-width:260px" value="Investigate APP-06 delay and optimize" />
      <input id="wf-thread" placeholder="Optional thread_id" />
      <label><input type="checkbox" id="wf-human" checked /> Human Review</label>
      <button class="primary" onclick="launchWorkflow()">Launch Workflow</button>
      <button onclick="checkStatus()">Check Status</button>
    </div>
    <pre id="wf-output">No workflow launched yet.</pre>
  </div>

  <div id="tab-decision" class="card hide">
    <h2>Decision Intelligence & What-If Scenarios</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
      <input id="exp-asset" value="APP-06" style="width:120px" />
      <button class="primary" onclick="explainAsset()">Explain Asset</button>
      <button class="primary" onclick="comparePlans()">Compare Baseline vs Optimized</button>
      <button class="primary" onclick="runDelayScenario()">Run APP-06 12w Delay</button>
    </div>
    <pre id="decision-output">Select an action above.</pre>
  </div>

  <div id="tab-review" class="card hide">
    <h2>Human-in-the-Loop Approval</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
      <input id="rev-thread" placeholder="Thread ID" />
      <input id="rev-user" value="web_reviewer" placeholder="Reviewer" />
      <input id="rev-comment" placeholder="Comment" style="flex:1" />
      <button class="primary" onclick="resumeWorkflow('APPROVE')">APPROVE</button>
      <button class="danger" onclick="resumeWorkflow('REJECT')">REJECT</button>
    </div>
    <pre id="review-output">Enter a paused thread_id to submit a decision.</pre>
  </div>

  <div id="tab-reports" class="card hide">
    <h2>Decision Reports</h2>
    <button class="primary" onclick="fetchReport('markdown')">Generate Markdown Report</button>
    <button class="primary" onclick="fetchReport('json')">Generate JSON Report</button>
    <pre id="report-output">Click a button to generate a report.</pre>
  </div>
</div>

<script>
function showTab(name, btn) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ['overview','workflow','decision','review','reports'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hide', t !== name);
  });
}
function pid() { return document.getElementById('portfolio-select').value; }

async function loadPortfolio() {
  const res = await fetch('/api/portfolios/' + pid());
  const data = await res.json();
  document.getElementById('overview-kpis').innerHTML = `
    <div class="kpi"><b>${data.asset_count}</b><span>Assets</span></div>
    <div class="kpi"><b>${data.wave_count}</b><span>Waves</span></div>
    <div class="kpi"><b>${data.conflict_count}</b><span>Conflicts</span></div>
    <div class="kpi"><b>$${(data.estimated_tsa_cost_total/1e6).toFixed(2)}M</b><span>Est. TSA Cost</span></div>
  `;
  document.getElementById('overview-json').textContent = JSON.stringify(data, null, 2);
}

async function launchWorkflow() {
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
  document.getElementById('wf-output').textContent = JSON.stringify(data, null, 2);
}

async function checkStatus() {
  const tid = document.getElementById('wf-thread').value;
  if (!tid) return alert('Enter a thread_id');
  const res = await fetch('/api/workflows/' + tid + '/status');
  document.getElementById('wf-output').textContent = JSON.stringify(await res.json(), null, 2);
}

async function explainAsset() {
  const aid = document.getElementById('exp-asset').value;
  const res = await fetch(`/api/assets/${aid}/explanation?portfolio_id=${pid()}`);
  document.getElementById('decision-output').textContent = JSON.stringify(await res.json(), null, 2);
}

async function comparePlans() {
  const res = await fetch(`/api/comparisons?portfolio_id=${pid()}&scenario=minimize_cost`);
  document.getElementById('decision-output').textContent = JSON.stringify(await res.json(), null, 2);
}

async function runDelayScenario() {
  const body = { portfolio_id: pid(), scenario_id: 'app_06_delay', scenario_name: 'APP-06 12w Delay', delay_weeks: {'APP-06': 12, 'APP-07': 12} };
  const res = await fetch('/api/scenarios', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  document.getElementById('decision-output').textContent = JSON.stringify(await res.json(), null, 2);
}

async function resumeWorkflow(action) {
  const tid = document.getElementById('rev-thread').value;
  if (!tid) return alert('Enter a thread_id');
  const body = { action, reviewer: document.getElementById('rev-user').value, comment: document.getElementById('rev-comment').value };
  const res = await fetch(`/api/workflows/${tid}/resume`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  document.getElementById('review-output').textContent = JSON.stringify(await res.json(), null, 2);
}

async function fetchReport(fmt) {
  const res = await fetch(`/api/reports/${pid()}?format=${fmt}`);
  const txt = fmt === 'markdown' ? await res.text() : JSON.stringify(await res.json(), null, 2);
  document.getElementById('report-output').textContent = txt;
}

loadPortfolio();
</script>
</body>
</html>
"""
