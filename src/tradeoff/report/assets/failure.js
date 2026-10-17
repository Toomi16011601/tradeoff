(() => {
  'use strict';
  const report = JSON.parse(document.getElementById('failure-data').textContent);
  const select = document.getElementById('scenario-select');
  if (!select) return;
  const byId = id => document.getElementById(id);
  const put = (id, value) => { byId(id).textContent = String(value ?? 'Unavailable'); };
  const num = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'Unavailable';
  const pct = value => value == null ? 'Unavailable' : num(value) + '%';
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = String(text); if (className) el.className = className; return el; };
  const labels = report.display_positions || {};
  const baseline = report.baseline || {};
  const before = baseline.result?.equity || [];
  const beforeLabels = labels.baseline || [];
  const plotLeft = 112, plotRight = 760, plotWidth = plotRight - plotLeft;
  let selected, after, afterLabels, selectedLedger, paired, tape, cursor = 0, firstChange = -1;
  const stress = scenario => scenario == null ? 'No stress parameters supplied' : `+${scenario.commission_bps ?? 0} bps commission · +${scenario.spread_bps ?? 0} bps spread · ${scenario.delay_bars ?? 0} extra ${(scenario.delay_bars ?? 0) === 1 ? 'bar' : 'bars'}`;
  const factList = entries => { const dl = node('dl', undefined, 'facts'); entries.forEach(([label, value]) => { const div = node('div'); div.append(node('dt', label), node('dd', value)); dl.append(div); }); return dl; };
  function metrics() {
    const m = selected.metrics || {};
    const card = node('div', undefined, 'metric-card');
    card.append(node('span', selected.name, 'eyebrow'), node('span', selected.status || 'UNAVAILABLE', 'entry-state'), node('strong', pct(m.return_pct)), node('span', 'Native return', 'subtle'));
    card.append(factList([['Final equity', num(m.final_equity)], ['Net profit', num(m.net_profit)], ['Max drawdown', pct(m.max_drawdown_pct)], ['Closed trades', m.closed_trades ?? 'Unavailable']]));
    if (selected.violations?.length) { const list = node('ul'); selected.violations.forEach(v => list.append(node('li', v))); card.append(list); }
    else card.append(node('p', 'No requirement violations recorded'));
    card.append(node('p', selected.reason || '', 'subtle'));
    byId('selected-metrics').replaceChildren(card);
  }
  function ledger() {
    const container = byId('selected-ledger'); container.replaceChildren();
    if (!selected.result) { container.append(node('p', `Native engine equity unavailable. ${selected.reason || selected.status || 'No execution result supplied'}`)); return; }
    const result = selected.result;
    container.append(node('h3', 'Native execution record'), factList([['Engine', `${result.engine ?? 'Unavailable'} ${result.engine_version ?? ''}`], ['Initial cash', num(result.initial_cash)]]));
    [['effective_settings', 'Effective native settings'], ['timing', 'Exact execution timing'], ['warnings', 'Execution warnings'], ['trades', 'Closed native trades'], ['open_trades', 'Open terminal holdings'], ['pending_orders', 'Pending terminal orders']].forEach(([key, label]) => {
      const details = node('details'); details.append(node('summary', label), node('pre', selectedLedger[key] ?? 'Not supplied')); container.append(details);
    });
  }
  function svgNode(tag, attrs, text) { const el = document.createElementNS('http://www.w3.org/2000/svg', tag); Object.entries(attrs || {}).forEach(([k,v]) => el.setAttribute(k, v)); if (text !== undefined) el.textContent = text; return el; }
  function chart() {
    const container = byId('chart-container'); container.replaceChildren();
    const values = [...before, ...after].map(p => p.equity).filter(Number.isFinite);
    if (!values.length) { container.append(node('p', 'Native engine equity unavailable', 'empty')); return; }
    let lo = values.reduce((a,b) => Math.min(a,b), Infinity), hi = values.reduce((a,b) => Math.max(a,b), -Infinity);
    const pad = Math.max((hi-lo)*.15, Math.max(Math.abs(lo),Math.abs(hi),1)*.0005); lo -= pad; hi += pad;
    const svg = svgNode('svg', {id:'equity-chart', viewBox:'0 0 800 260', role:'img', 'aria-labelledby':'chart-title chart-description'});
    svg.append(svgNode('title', {id:'chart-title'}, 'Native engine equity comparison'), svgNode('desc', {id:'chart-description'}, 'Baseline and selected scenario equity. Full paired values are in the accessible table below.'));
    for (let i=0;i<4;i++) { svg.append(svgNode('line', {x1:plotLeft,x2:plotRight,y1:20+i*70,y2:20+i*70,class:'grid'}), svgNode('text', {x:plotLeft-8,y:24+i*70,'text-anchor':'end'}, num(hi-(hi-lo)*i/3))); }
    const indexByTime = new Map(tape.map((p,i) => [p.timestamp,i]));
    [[before,'base-line'],[after,'stress-line']].forEach(([curve,className]) => { if (curve.length) svg.append(svgNode('polyline', {class:className,points:curve.map(p => `${plotLeft+(indexByTime.get(p.timestamp)??0)*plotWidth/Math.max(tape.length-1,1)},${20+(hi-p.equity)*210/(hi-lo)}`).join(' ')})); });
    svg.append(svgNode('line', {id:'chart-cursor',x1:plotLeft,x2:plotLeft,y1:20,y2:230,class:'cursor-line'})); container.append(svg);
  }
  function table() {
    const body = byId('equity-table').querySelector('tbody'); body.replaceChildren();
    const fragment = document.createDocumentFragment();
    tape.forEach((point, i) => { const b = before.length ? point : null; const pair = paired.get(point.timestamp); const a = pair?.point; const tr = node('tr');
      [i+1,point.timestamp,num(b?.equity),b ? beforeLabels[i] ?? 'Unavailable' : 'Unavailable',num(a?.equity),a ? afterLabels[pair.index] ?? 'Unavailable' : 'Unavailable'].forEach(value => tr.append(node('td',value))); fragment.append(tr); });
    body.append(fragment);
  }
  function inspect(value) {
    cursor = Math.min(Math.max(Number(value)||0,0), Math.max(tape.length-1,0));
    const point = tape[cursor]; const b = before.length ? point : null; const pair = point ? paired.get(point.timestamp) : null; const a = pair?.point;
    put('bar-counter', `${tape.length ? cursor+1 : 0} / ${tape.length}`); put('bar-timestamp', point?.timestamp || 'No observed bars');
    put('bar-base-equity',num(b?.equity)); put('bar-stress-equity',num(a?.equity));
    put('bar-base-position', b ? beforeLabels[cursor] ?? 'Unavailable' : 'Unavailable'); put('bar-stress-position', a ? afterLabels[pair.index] ?? 'Unavailable' : 'Unavailable');
    const input = byId('bar-cursor'); input.value = cursor; input.setAttribute('aria-valuetext', point ? `Bar ${cursor+1}: ${point.timestamp}` : 'No observed bars');
    byId('bar-prev').disabled = !tape.length || cursor === 0; byId('bar-next').disabled = !tape.length || cursor >= tape.length-1;
    const line = byId('chart-cursor'); if (line) { const x = plotLeft+cursor*plotWidth/Math.max(tape.length-1,1); line.setAttribute('x1',x); line.setAttribute('x2',x); }
  }
  function choose() {
    const key = select.value;
    selected = key === 'failure' ? {...report.failure,name:'Reduced failure',status:'FAIL'} : report.scenarios?.[Number(key)] || {name:'No scenario',status:'NOT_RUN',reason:'No scenario was declared.'};
    after = selected.result?.equity || []; afterLabels = key === 'failure' ? labels.failure || [] : labels.scenarios?.[Number(key)] || [];
    selectedLedger = key === 'failure' ? report.display_ledgers?.failure || {} : report.display_ledgers?.scenarios?.[Number(key)] || {};
    tape = before.length ? before : after; paired = new Map(after.map((point,index) => [point.timestamp,{point,index}]));
    firstChange = before.length && after.length ? before.findIndex((b,i) => { const pair = paired.get(b.timestamp); return pair && (beforeLabels[i] !== afterLabels[pair.index] || b.equity !== pair.point.equity); }) : -1;
    const positionIndex = before.length && after.length ? before.findIndex((b,i) => { const pair = paired.get(b.timestamp); return pair && beforeLabels[i] !== afterLabels[pair.index]; }) : -1;
    const equityIndex = before.length && after.length ? before.findIndex(b => { const pair = paired.get(b.timestamp); return pair && b.equity !== pair.point.equity; }) : -1;
    byId('first-change').disabled = firstChange < 0;
    put('divergence-note', before.length && after.length ? `Earliest changed position: ${positionIndex < 0 ? 'none observed' : before[positionIndex].timestamp}. Earliest changed equity: ${equityIndex < 0 ? 'none observed' : before[equityIndex].timestamp}.` : 'Paired divergence unavailable: both native results are required.');
    put('selected-stress', stress(selected.scenario)); put('comparison-note', selected.reason || (!after.length ? `Native engine equity unavailable · ${selected.status}` : !before.length ? `Baseline native engine equity unavailable · ${baseline.reason || baseline.status}` : ''));
    const input = byId('bar-cursor'); input.max = Math.max(tape.length-1,0); input.disabled = !tape.length;
    metrics(); ledger(); chart(); table(); inspect(0);
  }
  select.addEventListener('change',choose);
  byId('bar-cursor').addEventListener('input', event => inspect(event.target.value));
  byId('bar-prev').addEventListener('click', () => inspect(cursor-1));
  byId('bar-next').addEventListener('click', () => inspect(cursor+1));
  byId('first-change').addEventListener('click', () => { inspect(firstChange); byId('bar-cursor').focus(); });
  choose();
})();
