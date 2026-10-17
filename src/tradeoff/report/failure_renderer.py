"""Self-contained execution failure reports, independent of invariant reports."""
from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from .. import __version__
from ..privacy import reject_sensitive_data
from .renderer import _escape, _json, _number, _safe_path, _table

STATES = {
    "FAILURE_FOUND": ("failed", "Stress failure found", "A requirement broke under stress."),
    "BASELINE_FAILED": ("failed", "Baseline failed", "The baseline already fails."),
    "NO_FAILURE_OBSERVED": ("clear", "No failure observed", "The tested scenarios met your policy."),
    "INCONCLUSIVE": ("uncertain", "Inconclusive", "The comparison is incomplete."),
}


def _state(status):
    if status not in STATES:
        raise ValueError("unknown failure report status")
    return STATES[status]


def _pct(value):
    return _number(value) + "%" if value is not None else "Unavailable"


def _quantity(value):
    """Canonical display equality without passing native integers through float."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value) if value is not None else 'Unavailable'


def _stress(scenario):
    if scenario is None:
        return 'No stress parameters supplied'
    delay = scenario.get('delay_bars', 0)
    return (f"+{scenario.get('commission_bps', 0)} bps commission · "
            f"+{scenario.get('spread_bps', 0)} bps spread · "
            f"{delay} extra {'bar' if delay == 1 else 'bars'}")


def _list(items, empty="None recorded"):
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in items) + "</ul>" if items else f"<p>{_escape(empty)}</p>"


def _facts(values):
    return '<dl class="facts">' + "".join(f"<div><dt>{_escape(label)}</dt><dd>{_escape(value)}</dd></div>" for label, value in values) + "</dl>"


def _pre(value):
    return f"<pre>{_escape(_json(value, pretty=True))}</pre>"


def _metrics(entry, label):
    metrics = entry.get("metrics") or {}
    return f'''<div class="metric-card"><span class="eyebrow">{_escape(label)}</span><span class="entry-state">{_escape(entry.get('status', 'UNAVAILABLE'))}</span>
    <strong>{_pct(metrics.get('return_pct'))}</strong><span class="subtle">Native return</span>
    {_facts([('Final equity', _number(metrics.get('final_equity'))), ('Net profit', _number(metrics.get('net_profit'), signed=True)), ('Max drawdown', _pct(metrics.get('max_drawdown_pct'))), ('Closed trades', metrics.get('closed_trades', 'Unavailable'))])}
    {_list(entry.get('violations') or [], 'No requirement violations recorded')}
    <p class="subtle">{_escape(entry.get('reason') or '')}</p></div>'''


def _policy(report):
    requirements = report.get("requirements") or {}
    labels = [('min_return_pct', 'Minimum return', '%'), ('max_drawdown_pct', 'Maximum drawdown', '%'),
              ('max_return_drop_pct', 'Maximum return drop vs baseline', ' percentage points'), ('min_closed_trades', 'Minimum closed trades', '')]
    values = [(label, str(requirements[key]) + unit if requirements.get(key) is not None else 'Disabled') for key, label, unit in labels]
    return f'<article class="panel policy"><span class="eyebrow">YOUR REQUIREMENTS</span><h2>A declared policy.</h2>{_facts(values)}<p class="subtle">A failure is a policy breach under simulated assumptions. A passing result covers only the completed declared scenarios.</p></article>'


def _input_checks(report):
    checks = report.get('input_checks')
    if not checks:
        return ''
    warnings = list(checks.get('warnings') or [])
    warnings.extend(item.get('message', 'Input limitation recorded')
                    for item in checks.get('data_warnings') or [])
    return ('<section id="input-checks" class="panel"><span class="eyebrow">INPUT CHECKS</span>'
            '<h2>Input limitations and declarations.</h2>'
            + _list(warnings, 'No input limitations reported by these bounded checks.')
            + '<p>Direct attribute checks do not verify helper functions, dynamic features or companion-data semantics. '
              'A completed simulation does not establish faithful strategy integration.</p>'
            + '<details><summary>Declared fields and static inspection scope</summary>'
            + _pre(checks) + '</details></section>')


def _matrix(report):
    entries = [("Baseline", {"commission_bps": 0, "spread_bps": 0, "delay_bars": 0}, report.get('baseline') or {})]
    entries += [(item.get('name', 'Scenario'), item.get('scenario'), item) for item in report.get('scenarios') or []]
    rows = []
    for name, scenario, entry in entries:
        metrics = entry.get('metrics') or {}
        note = '; '.join(entry.get('violations') or []) or entry.get('reason') or 'No violations recorded'
        rows.append([name, _stress(scenario), entry.get('status', 'UNAVAILABLE'), _pct(metrics.get('return_pct')),
                     _pct(metrics.get('max_drawdown_pct')), metrics.get('closed_trades', 'Unavailable'), note])
    return '<section id="scenarios" class="panel"><span class="eyebrow">DECLARED SCENARIOS</span><h2>The full test matrix.</h2><p>Costs are additional to native settings. 1 basis point (bps) = 0.01%. Delay means extra bars beyond normal next-open execution.</p>' + _table(['Scenario', 'Additional stress', 'Status', 'Native return', 'Max drawdown', 'Closed trades', 'Violations / reason'], rows, table_id='scenario-table', caption='All declared native execution scenarios, including unavailable and not-run cases') + '</section>'


def _selected(report):
    failure = report.get('failure')
    if failure:
        return 'failure', {**failure, 'name': 'Reduced failure', 'status': 'FAIL'}
    entries = report.get('scenarios') or []
    index = next((i for i, entry in enumerate(entries) if entry.get('result')), 0)
    return str(index), entries[index] if entries else {'name': 'No scenario', 'status': 'NOT_RUN', 'result': None, 'reason': 'No scenario was declared.'}


def _curves(report, selected):
    return ((report.get('baseline') or {}).get('result') or {}).get('equity') or [], (selected.get('result') or {}).get('equity') or []


def _chart(before, after):
    values = [point['equity'] for point in before + after]
    if not values:
        return '<p class="empty">Native engine equity unavailable</p>'
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * .15, max(abs(lo), abs(hi), 1) * .0005)
    lo, hi = lo - pad, hi + pad
    count = max(len(before), len(after))
    left, right = 112, 760
    plot_width = right - left

    def points(curve):
        return ' '.join(f'{left + i * plot_width / max(count - 1, 1):.2f},{20 + (hi-p["equity"])*210/(hi-lo):.2f}' for i, p in enumerate(curve))

    grid = ''.join(f'<line x1="{left}" x2="{right}" y1="{20+i*70}" y2="{20+i*70}" class="grid"/><text x="{left-8}" y="{24+i*70}" text-anchor="end">{_number(hi-(hi-lo)*i/3)}</text>' for i in range(4))
    lines = ''.join(f'<polyline class="{kind}" points="{points(curve)}"/>' for kind, curve in [('base-line', before), ('stress-line', after)] if curve)
    return f'<svg id="equity-chart" viewBox="0 0 800 260" role="img" aria-labelledby="chart-title chart-description"><title id="chart-title">Native engine equity comparison</title><desc id="chart-description">Baseline and selected scenario equity. Full paired values are in the accessible table below.</desc>{grid}{lines}<line id="chart-cursor" x1="{left}" x2="{left}" y1="20" y2="230" class="cursor-line"/></svg>'


def _equity_rows(before, after):
    paired = {point['timestamp']: point for point in after}
    rows = []
    tape = before or after
    for index, point in enumerate(tape):
        b = point if before else None
        a = paired.get(point['timestamp'])
        rows.append([index + 1, point['timestamp'], _number(b['equity']) if b else 'Unavailable',
                     _quantity(b['position']) if b else 'Unavailable', _number(a['equity']) if a else 'Unavailable',
                     _quantity(a['position']) if a else 'Unavailable'])
    return rows


def _ledger(entry):
    result = entry.get('result')
    if not result:
        return f'<p>Native engine equity unavailable. {_escape(entry.get("reason") or entry.get("status") or "No execution result supplied")}</p>'
    return '<h3>Native execution record</h3>' + _facts([('Engine', f"{result.get('engine', 'Unavailable')} {result.get('engine_version', '')}"), ('Initial cash', _number(result.get('initial_cash')))]) + ''.join(
        f'<details><summary>{label}</summary>{_pre(result.get(key, [] if key in {"trades", "open_trades", "pending_orders", "warnings"} else {}))}</details>'
        for key, label in [('effective_settings', 'Effective native settings'), ('timing', 'Exact execution timing'), ('warnings', 'Execution warnings'), ('trades', 'Closed native trades'), ('open_trades', 'Open terminal holdings'), ('pending_orders', 'Pending terminal orders')])


def _comparison(report):
    key, selected = _selected(report)
    before, after = _curves(report, selected)
    options = '<option value="failure">Reduced failure · FAIL</option>' if report.get('failure') else ''
    options += ''.join(f'<option value="{i}"{" selected" if str(i)==key else ""}>{_escape(entry.get("name", "Scenario"))} · {_escape(entry.get("status", "UNAVAILABLE"))}</option>' for i, entry in enumerate(report.get('scenarios') or []))
    if not options:
        options = '<option value="0">No scenario · NOT_RUN</option>'
    count = len(before or after)
    b, a = (before[0] if before else {}), (after[0] if after else {})
    disabled = ' disabled' if not count else ''
    return f'''<section id="comparison" class="panel"><div class="section-top"><div><span class="eyebrow">PAIRED EXECUTION</span><h2>Native engine equity.</h2></div><div class="select-wrap"><label for="scenario-select">Compare with baseline</label><select id="scenario-select">{options}</select></div></div>
    <p>Each scenario reruns the strategy and broker. Cash, sizing, fills and positions come from the engine. Open holdings and pending tail orders remain visible.</p>
    <div class="metric-pair"><div>{_metrics(report.get('baseline') or {}, 'Baseline')}</div><div id="selected-metrics">{_metrics(selected, selected.get('name', 'Selected scenario'))}</div></div>
    <p id="selected-stress" class="stress-description">{_escape(_stress(selected.get('scenario')))}</p>
    <div class="legend"><span><i class="base-key"></i>Baseline</span><span><i class="stress-key"></i>Selected scenario</span></div>
    <div id="chart-container">{_chart(before, after)}</div><p id="comparison-note" class="subtle">{_escape(selected.get('reason') or '')}</p>
    <div class="inspection"><div class="section-top"><label for="bar-cursor" class="eyebrow">INSPECT A BAR</label><span id="bar-counter">{'1' if count else '0'} / {count}</span></div>
    <div class="cursor-controls"><button type="button" id="bar-prev" aria-label="Inspect previous bar" disabled>←</button><input type="range" id="bar-cursor" min="0" max="{max(count-1, 0)}" value="0" aria-label="Inspection bar"{disabled}><button type="button" id="bar-next" aria-label="Inspect next bar"{' disabled' if count<2 else ''}>→</button></div>
    <div id="bar-detail" aria-live="polite" aria-atomic="true"><p id="bar-timestamp" class="mono">{_escape(b.get('timestamp') or a.get('timestamp') or 'No observed bars')}</p><div class="bar-pair"><p>Baseline equity <strong id="bar-base-equity">{_number(b.get('equity'))}</strong><br>Position <strong id="bar-base-position">{_escape(_quantity(b.get('position')))}</strong></p><p>Scenario equity <strong id="bar-stress-equity">{_number(a.get('equity'))}</strong><br>Position <strong id="bar-stress-position">{_escape(_quantity(a.get('position')))}</strong></p></div></div>
    <button type="button" id="first-change" class="text-button">Inspect earliest divergence</button><p id="divergence-note" class="subtle"></p></div>
    <details><summary>Accessible paired equity and positions</summary>{_table(['Bar', 'Timestamp', 'Baseline equity', 'Baseline position', 'Scenario equity', 'Scenario position'], _equity_rows(before, after), table_id='equity-table', caption='Native engine equity and observed positions on the full input tape')}</details>
    <div class="ledger-pair"><details><summary>Baseline native ledger</summary>{_ledger(report.get('baseline') or {})}</details><details><summary>Selected scenario native ledger</summary><div id="selected-ledger">{_ledger(selected)}</div></details></div>
    <p class="subtle">Changed observations locate divergence; they do not allocate lost profit causally to individual trades.</p></section>'''


def _failure(report):
    failure = report.get('failure')
    if not failure:
        return '<section id="failure" class="panel"><span class="eyebrow">FAILURE EVIDENCE</span><h2>No verified stress failure.</h2><p>No reduced failure or replay fixture is established by this report. Inspect the baseline outcome and scenario coverage above.</p></section>'
    differences = failure.get('differences') or []
    position = next((point['timestamp'] for point in differences if point.get('before_position') != point.get('after_position')), 'No changed position observed')
    equity = next((point['timestamp'] for point in differences if point.get('before_equity') != point.get('after_equity')), 'No changed equity observed')
    reduction = failure.get('reduction') or {}
    return f'''<section id="failure" class="panel"><span class="eyebrow">VERIFIED FAILURE</span><h2>A reduced, tested stress.</h2><p>{_escape(_stress(failure.get('scenario')))}</p>{_list(failure.get('violations') or [])}
    {_facts([('Earliest changed position', position), ('Earliest changed equity', equity), ('Reduction runs', reduction.get('runs', 'Unavailable')), ('Declared reduction complete', 'Yes' if reduction.get('complete') else 'No')])}
    <p>{_escape(reduction.get('scope') or reduction.get('reason') or 'No reduction scope supplied.')}</p><p class="subtle">Full history is retained. Search over declared levels is bounded and may be nonmonotonic; this is not a global break-even threshold.</p>
    <details><summary>All changed paired observations · {len(differences)}</summary>{_table(['Timestamp', 'Baseline position', 'Failure position', 'Baseline equity', 'Failure equity'], [[p.get('timestamp'), _quantity(p.get('before_position')), _quantity(p.get('after_position')), _number(p.get('before_equity')), _number(p.get('after_equity'))] for p in differences], caption='Verified reduced failure paired native observations')}</details></section>'''


def _replay(report, artifacts):
    labels = {'json': 'Full report JSON', 'fixture': 'Failure fixture', 'test': 'Pytest regression', 'receipt': 'Integrity receipt'}
    has_failure = bool(report.get('failure'))
    links = ''.join(f'<a class="download" href="{_escape(path)}" download>{_escape(labels.get(key, key))} ↗</a>' for key, path in artifacts.items() if key == 'json' or has_failure)
    command = f"python -m pytest {artifacts['test']}" if has_failure and artifacts.get('test') else None
    replay = f'''<div class="command"><span class="eyebrow">RUN WITH YOUR STRATEGY IMPORTABLE</span><pre><code>{_escape(command)}</code></pre><p>Install your strategy project, its exact engine version and pytest. The command above uses the exported test's filename. For checkout examples, run from the repository root and prefix that filename with the output folder. The generated test imports <code>{_escape(report.get('strategy_ref') or 'the saved runner')}</code> and loads the sibling fixture.</p></div><ol class="replay-steps"><li><strong>Reproduce the policy breach.</strong> The saved strategy should fail this test under the verified stress.</li><li><strong>Repair and replay.</strong> Adjust the strategy, then rerun both baseline and stress against the same full tape and requirements. Use explicit runner or config overrides for repairs.</li><li><strong>Keep the evidence.</strong> Retain fixture hashes and the original receipt. Version mismatch refuses comparison; a passing replay is a scoped policy result.</li></ol>''' if command else '<p>No regression test was exported. A verified stress failure and an importable runner are required for a replay fixture.</p>'
    return f'<section id="replay" class="panel"><span class="eyebrow">REPLAY & REPAIR</span><h2>Make the failure reproducible.</h2>{replay}<div class="downloads">{links}</div><p class="subtle">Keep sibling files together. Content hashes detect changes; receipts are not signed source-authenticity attestations.</p></section>'


def _method(report):
    coverage = report.get('coverage') or {}
    settings = report.get('settings') or {}
    return f'''<section id="method" class="panel"><span class="eyebrow">SCOPE & PROVENANCE</span><h2>Know what was run.</h2>{_facts([('Engine invocations / budget', f"{coverage.get('runs', 0)} / {settings.get('max_calls', 'Unavailable')}"), ('Completed / declared scenarios', f"{coverage.get('completed', 0)} / {coverage.get('total', 0)}"), ('Declared suite complete', 'Yes' if coverage.get('complete') else 'No'), ('Seed', settings.get('seed', 'Unavailable')), ('Schema', report.get('schema_version')), ('Input SHA-256', (report.get('dataset') or {}).get('input_hash'))])}{_list(coverage.get('notes') or [], 'No coverage notes recorded')}
    <p>Protective contingent stop-loss and take-profit orders keep native timing. Extra delay applies to discretionary market entries and manual market closes. Unsupported delayed order types and trade-on-close execution remain unavailable.</p>
    <details><summary>Runner and native engine settings</summary>{_pre(report.get('runner_spec') or {})}</details><details><summary>Exact callback configuration</summary>{_pre(report.get('config') or {})}</details><details><summary>Search settings and coverage</summary>{_pre({'settings': settings, 'coverage': coverage})}</details>
    <details><summary>Source and input provenance</summary>{_pre(report.get('provenance')) if report.get('provenance') else '<p>No provenance supplied.</p>'}</details><p class="subtle">Simulated execution on the declared tape. This report does not certify profitability or resilience outside the tested scenarios.</p></section>'''


def _document(content, *, title, report=None):
    resources = files('tradeoff.report')
    data = dict(report or {})
    if report:
        position_labels = lambda result: [_quantity(point.get('position')) for point in (result or {}).get('equity') or []]
        data['display_positions'] = {
            'baseline': position_labels((report.get('baseline') or {}).get('result')),
            'scenarios': [position_labels(entry.get('result')) for entry in report.get('scenarios') or []],
            'failure': position_labels((report.get('failure') or {}).get('result')),
            'differences': [{key: _quantity(value) if key in {'before_position', 'after_position'} else value for key, value in point.items()} for point in (report.get('failure') or {}).get('differences') or []],
        }
        def ledger_labels(result):
            return {key: _json(value, pretty=True) for key, value in (result or {}).items()
                    if key in {'effective_settings', 'timing', 'warnings', 'trades', 'open_trades', 'pending_orders'}}

        # JS cannot stringify native integers above 2^53 faithfully. Preserve
        # the exact ledger text as well as the observed position labels.
        data['display_ledgers'] = {
            'baseline': ledger_labels((report.get('baseline') or {}).get('result')),
            'scenarios': [ledger_labels(entry.get('result')) for entry in report.get('scenarios') or []],
            'failure': ledger_labels((report.get('failure') or {}).get('result')),
        }
    encoded = _json(data).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    replacements = {'TITLE': _escape(title), 'VERSION': _escape(__version__), 'CONTENT': content, 'DATA': encoded,
                    'CSS': resources.joinpath('assets/failure.css').read_text(encoding='utf-8'),
                    'JS': resources.joinpath('assets/failure.js').read_text(encoding='utf-8') if report else ''}
    template = resources.joinpath('failure_template.html').read_text(encoding='utf-8')
    return re.sub(r'@@([A-Z_]+)@@', lambda match: replacements[match.group(1)], template)


def render_failure_report(report: dict) -> str:
    """Render finite JSON evidence with inline assets and safe sibling downloads."""
    reject_sensitive_data(report)
    tone, label, title = _state(report.get('status'))
    _json(report)  # Validate every field before formatting or emitting files.
    artifacts = {key: _safe_path(path) for key, path in (report.get('artifacts') or {}).items() if path is not None}
    data = report.get('dataset') or {}
    hero = f'''<section class="hero"><div class="report-ribbon"><span class="eyebrow">STRATEGY FAILURE LAB / {_escape(data.get('symbol', 'DATASET'))}</span><span class="mono">{_escape(report.get('report_id'))}</span></div><span class="status {tone}">{_escape(label)}</span><h1>{_escape(title)}</h1><p class="hero-description">{_escape(report.get('headline') or '')}</p><p>{_escape(report.get('reason') or '')}</p><div class="hero-facts">{_facts([('Strategy', report.get('strategy_ref') or 'Local execution callback'), ('Full tape', f"{data.get('row_count', 0)} bars"), ('Period', f"{data.get('start', 'Unavailable')} → {data.get('end', 'Unavailable')}"), ('Created', report.get('created_at'))])}</div></section>'''
    nav = '<nav aria-label="Report sections">' + ''.join(f'<a href="#{key}">{label}</a>' for key, label in [('scenarios', 'Scenarios'), ('comparison', 'Equity'), ('failure', 'Failure'), ('replay', 'Replay'), ('method', 'Scope')]) + '</nav>'
    return _document(hero + nav + _policy(report) + _input_checks(report) + _matrix(report) + _comparison(report) + _failure(report) + _replay(report, artifacts) + _method(report), title=f'Tradeoff · {label}', report=report)


def write_failure_report(report: dict, output_dir: str | Path) -> Path:
    """Write unchanged report JSON and a standalone HTML report."""
    markup = render_failure_report(report)
    encoded = _json(report, pretty=True) + '\n'
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'report.json').write_text(encoded, encoding='utf-8')
    page = destination / 'index.html'
    page.write_text(markup, encoding='utf-8')
    return page


def write_failure_gallery(output_dir: str | Path, entries: list[dict]) -> Path:
    """Write an offline index linking local execution failure reports."""
    reject_sensitive_data(entries)
    cards = ''
    for index, entry in enumerate(entries, 1):
        tone, label, _ = _state(entry['status'])
        path = _safe_path(entry['path'])
        cards += f'<a class="case-card" href="{_escape(path)}"><span class="eyebrow">CASE {index:02d}</span><span class="status {tone}">{_escape(label)}</span><h2>{_escape(entry.get("name"))}</h2><p>{_escape(entry.get("description") or "")}</p><span class="case-open">Inspect execution report ↗</span></a>'
    content = '<section class="hero"><span class="eyebrow">PUBLIC STRATEGY CASEBOOK</span><h1>What breaks<br><em>under stress?</em></h1><p class="hero-description">Pinned public strategy code. Synthetic full tapes. Native execution reruns.</p><p>Inspect the baseline, declared cost and delay scenarios, policy failures and replay evidence. Every outcome remains visible.</p></section><div class="case-grid">' + cards + '</div><section class="panel"><h2>Evidence you can replay.</h2><p>These cases illustrate simulated execution and scoped user requirements. Synthetic inputs do not measure historical or live market performance. A baseline failure is visible as its own outcome.</p></section>'
    markup = _document(content, title='Tradeoff · Execution casebook')
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    page = destination / 'index.html'
    page.write_text(markup, encoding='utf-8')
    return page
