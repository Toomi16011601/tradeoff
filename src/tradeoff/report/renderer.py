"""Render JSON audit records without network services or active data markup."""
from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from .. import __version__
from ..privacy import reject_sensitive_data


STATES = {
    "FOUND": ("found", "Future dependency found", "The future changed", "a past decision."),
    "NO_DEPENDENCY_OBSERVED": ("clear", "No dependency observed", "No dependency observed.", "Within this audit."),
    "INCONCLUSIVE": ("uncertain", "Audit inconclusive", "The audit is inconclusive.", "Resolve the blocker."),
}


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _json(value: Any, *, pretty: bool = False) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2 if pretty else None)


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value):
        raise ValueError("artifact paths must be safe relative filenames")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("artifact paths must not contain traversal or empty components")
    return value


def _number(value: Any, *, signed: bool = False) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "—"
    return f"{value:+,.2f}" if signed else f"{value:,.2f}"


def _date(value: Any) -> str:
    return str(value or "—")[:10]


def _status(status: str) -> tuple[str, str, str, str]:
    if status not in STATES:
        raise ValueError("report status must be FOUND, NO_DEPENDENCY_OBSERVED, or INCONCLUSIVE")
    return STATES[status]


def _pill(status: str) -> str:
    tone, label, _, _ = _status(status)
    return f'<span class="status-pill {tone}"><span class="status-dot" aria-hidden="true"></span>{label}</span>'


def _artifact_link(path: str, label: str, *, primary: bool = False) -> str:
    css = "button primary" if primary else "download-link"
    return f'<a class="{css}" href="{_escape(_safe_path(path))}" download>{_escape(label)}<span aria-hidden="true">↗</span></a>'


def _table(headers: list[str], rows: list[list[Any]], *, table_id: str = "", caption: str = "") -> str:
    attr = f' id="{_escape(table_id)}"' if table_id else ""
    title = f"<caption>{_escape(caption)}</caption>" if caption else ""
    head = "".join(f'<th scope="col">{_escape(value)}</th>' for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll" tabindex="0" role="region" aria-label="{_escape(caption or "Data table")}"><table{attr}>{title}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _decision_target(value: Any) -> Any:
    return value.get("target", "—") if isinstance(value, dict) else value


def _decision_panel(report: dict, *, compact: bool = False) -> str:
    witness = report.get("witness")
    if not witness:
        return '<div class="empty-note"><span class="eyebrow">WITNESS</span><h3>No witness is available</h3><p>A paired decision change has not been established for this report.</p></div>'
    before = _decision_target(witness.get("before_decision"))
    after = _decision_target(witness.get("after_decision"))
    reduced = "Reduced witness" if witness.get("reduced") else "Observed witness"
    count = len(witness.get("changed_rows", []))
    unit_label = "Observed position units" if report.get("trace_kind") == "observed_position" else "Target units"
    return f'''<div class="decision-panel{' compact' if compact else ''}">
      <div class="panel-kicker"><span class="eyebrow">THE DECISION WITNESS</span><span class="tiny-tag">{_escape(reduced)}</span></div>
      <div class="target-pair"><div><span class="micro">ORIGINAL TARGET</span><strong>{_escape(before)}</strong></div><span class="pair-arrow" aria-label="changed to">→</span><div><span class="micro">AFTER INTERVENTION</span><strong class="red-text">{_escape(after)}</strong></div></div>
      <p class="target-caption">{unit_label} · long / short / flat</p>
      <dl class="evidence-facts"><div><dt>Decision at</dt><dd class="mono">{_escape(witness.get('decision_timestamp'))}</dd></div><div><dt>Fixed cutoff</dt><dd class="mono">{_escape(witness.get('cutoff'))}</dd></div><div><dt>Unavailable records changed</dt><dd>{count}</dd></div><div><dt>Intervention</dt><dd class="mono">{_escape(witness.get('mutation_name'))}</dd></div></dl>
      <a class="text-link" href="#evidence">Inspect the paired evidence <span aria-hidden="true">↗</span></a>
    </div>'''


def _hero(report: dict, artifacts: dict) -> str:
    status = report["status"]
    _, _, title, subtitle = _status(status)
    dataset = report.get("dataset", {})
    coverage = report.get("coverage", {})
    settings = report.get("settings", {})
    link = _artifact_link(artifacts["test"], "Export regression test", primary=True) if artifacts.get("test") else _artifact_link(artifacts["json"], "Download audit JSON", primary=True) if artifacts.get("json") else ""
    return f'''<div class="report-ribbon"><span class="eyebrow">AUDIT REPORT <span class="ribbon-slash">/</span> {_escape(dataset.get('symbol', 'DATASET'))}</span><span class="mono">{_escape(report.get('report_id', ''))}</span></div>
    <div class="hero"><div class="hero-copy">{_pill(status)}<h1>{_escape(title)}<br><em>{_escape(subtitle)}</em></h1><p class="hero-description">{_escape(report.get('headline') or report.get('reason') or '')}</p></div><aside class="docket"><span class="eyebrow">AUDIT SCOPE</span><dl><div><dt>Price tape</dt><dd>{_escape(dataset.get('symbol'))} <span class="subtle">/ {_escape(dataset.get('row_count', 0))} bars</span></dd></div><div><dt>Period</dt><dd class="mono">{_escape(_date(dataset.get('start')))} → {_escape(_date(dataset.get('end')))}</dd></div><div><dt>Strategy</dt><dd class="mono">{_escape(report.get('strategy_ref') or 'Local callback')}</dd></div><div><dt>Recorded trace</dt><dd>{_escape(str(report.get('trace_kind', 'target_units')).replace('_', ' '))}</dd></div></dl></aside></div>
    <div class="audit-strip"><div><span class="micro">CALLBACK RUNS</span><strong class="mono">{_escape(coverage.get('runs', 0))}<small> / {_escape(settings.get('max_calls', '—'))}</small></strong></div><div><span class="micro">COMPLETED INTERVENTIONS</span><strong class="mono">{_escape(coverage.get('probes', 0))}</strong></div><div><span class="micro">FIXED SEED</span><strong class="mono">{_escape(settings.get('seed', '—'))}</strong></div><p class="strip-note">{_escape(report.get('reason') or '')}</p>{link}</div>'''


def _curve(report: dict) -> tuple[list[dict], list[dict], int]:
    economics = report.get("economics") or {}
    original = (economics.get("original") or {}).get("equity_curve", [])
    intervention = (economics.get("intervention") or {}).get("equity_curve", [])
    cursor = min(max(int((report.get("witness") or {}).get("decision_index", 0)), 0), max(len(original) - 1, 0))
    return original, intervention, cursor


def _chart(report: dict) -> str:
    original, intervention, cursor = _curve(report)
    if not original:
        reason = report.get("economics_error") or "No equity ledger was supplied. This audit only reports decision evidence."
        return f'<div class="unavailable"><span class="eyebrow">ECONOMIC PROJECTION</span><h3>Economic projection unavailable</h3><p>{_escape(reason)}</p></div>'
    values = [float(point["equity"]) for point in original + intervention]
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * .2, max(abs(lo), abs(hi), 1) * .0005)
    lo, hi = lo - pad, hi + pad
    width, height, left, right, top, bottom = 800, 260, 62, 17, 16, 35
    plot_width, plot_height = width - left - right, height - top - bottom

    def xy(i: int, equity: float) -> tuple[float, float]:
        return (left + plot_width * i / max(len(original) - 1, 1), top + plot_height * (hi - equity) / (hi - lo))

    def points(curve: list[dict]) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in [xy(i, float(p['equity'])) for i, p in enumerate(curve)])

    grid = ""
    for step in range(4):
        value = hi - (hi - lo) * step / 3
        y = top + plot_height * step / 3
        grid += f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" class="chart-grid"/><text x="{left-12}" y="{y+4:.2f}" text-anchor="end" class="chart-label">{_number(value)}</text>'
    original_points = points(original)
    area = f'{left},{top+plot_height} {original_points} {xy(len(original)-1, original[-1]["equity"])[0]:.2f},{top+plot_height}'
    x, y = xy(cursor, original[cursor]["equity"])
    intervention_line = f'<polyline points="{points(intervention)}" class="intervention-line"/>' if intervention else ""
    cursor_pair = f'<circle id="cursor-intervention" cx="{x:.2f}" cy="{xy(cursor, intervention[cursor]["equity"])[1]:.2f}" r="4.5" class="intervention-dot"/>' if len(intervention) > cursor else ""
    labels = ""
    for i, anchor in [(0, "start"), (len(original) - 1, "end")]:
        lx, _ = xy(i, original[i]["equity"])
        labels += f'<text x="{lx:.2f}" y="{height-8}" text-anchor="{anchor}" class="chart-label">{_escape(_date(original[i].get("timestamp")))}</text>'
    witness = report.get("witness")
    cutoff = ""
    if witness:
        index = next((i for i, p in enumerate(original) if p.get("timestamp") == witness.get("cutoff")), None)
        if index is not None:
            cx, _ = xy(index, 0)
            cutoff = f'<line x1="{cx:.2f}" y1="{top}" x2="{cx:.2f}" y2="{top+plot_height}" class="cutoff-line"/><text x="{cx+7:.2f}" y="{top+12}" class="cutoff-label">FIXED CUTOFF</text>'
    comparison_description = "Original decisions and intervention decisions evaluated on the same original prices." if intervention else "Original decisions evaluated on the original prices. No paired ledger was supplied."
    return f'''<svg id="equity-chart" class="equity-chart" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc" data-lo="{lo}" data-hi="{hi}" data-left="{left}" data-top="{top}" data-width="{plot_width}" data-height="{plot_height}"><title id="chart-title">Projected equity on the original price tape</title><desc id="chart-desc">{comparison_description} An accessible data table follows the chart.</desc>{grid}<polygon points="{area}" class="equity-area"/>{cutoff}<polyline points="{original_points}" class="original-line"/>{intervention_line}<line id="cursor-line" x1="{x:.2f}" x2="{x:.2f}" y1="{top}" y2="{top+plot_height}" class="cursor-line"/><circle id="cursor-original" cx="{x:.2f}" cy="{y:.2f}" r="4.5" class="original-dot"/>{cursor_pair}{labels}</svg>'''


def _economics_panel(report: dict) -> str:
    economics = report.get("economics")
    if not economics or not economics.get("original"):
        return _chart(report)
    original_ledger = economics["original"]
    intervention_ledger = economics.get("intervention")
    heading = "One tape. Two decision paths." if intervention_ledger else "Original decisions. Original tape."
    description = "Both decision traces are projected on the original price tape, with the same execution assumptions." if intervention_ledger else "The original decision trace is projected on the original price tape, with the declared execution assumptions."
    original, intervention, cursor = _curve(report)
    paired_legend = '<span><i class="legend-line intervention"></i>Intervention decisions</span>' if intervention_ledger else ""
    paired_metric = f'<div><span class="micro">INTERVENTION NET P&amp;L</span><strong>{_number(intervention_ledger.get("net_pnl"), signed=True)}</strong></div><div><span class="micro">PAIRED DIFFERENCE</span><strong class="red-text">{_number(economics.get("delta"), signed=True)}</strong></div>' if intervention_ledger else '<div><span class="micro">PAIRED DIFFERENCE</span><strong class="no-value">No paired ledger</strong></div>'
    curves = {p.get("timestamp"): p.get("equity") for p in intervention}
    table_rows = [[i + 1, p.get("timestamp"), _number(p.get("equity")), _number(curves.get(p.get("timestamp")))] for i, p in enumerate(original)]
    controls = ""
    if original:
        original_targets = (report.get("baseline") or {}).get("trace", [])
        intervention_targets = (report.get("witness") or {}).get("mutated_trace", [])
        current_target = original_targets[cursor].get("target", "—") if len(original_targets) > cursor else "—"
        paired_target = intervention_targets[cursor].get("target", "—") if len(intervention_targets) > cursor else "—"
        paired_value = _number(intervention[cursor].get("equity")) if len(intervention) > cursor else "—"
        controls = f'''<div class="inspection"><div class="inspection-heading"><span class="eyebrow">INSPECT A BAR</span><span id="cursor-counter" class="mono">{cursor+1:02d} / {len(original):02d}</span></div><div class="cursor-controls js-only"><button type="button" id="cursor-prev" class="icon-button" aria-label="Inspect previous bar">←</button><input type="range" id="inspection-cursor" min="0" max="{len(original)-1}" value="{cursor}" aria-label="Inspection bar" aria-valuetext="Bar {cursor+1}: {_escape(original[cursor].get('timestamp'))}"><button type="button" id="cursor-next" class="icon-button" aria-label="Inspect next bar">→</button></div><div class="cursor-detail" aria-live="polite" aria-atomic="true"><time id="cursor-timestamp" class="mono">{_escape(original[cursor].get('timestamp'))}</time><div><span class="green-dot" aria-hidden="true"></span><span>Original <strong id="cursor-original-value" class="mono">{_number(original[cursor].get('equity'))}</strong><small>target <span id="cursor-original-target">{_escape(current_target)}</span></small></span><span class="red-dot" aria-hidden="true"></span><span>Intervention <strong id="cursor-intervention-value" class="mono">{paired_value}</strong><small>target <span id="cursor-intervention-target">{_escape(paired_target)}</span></small></span></div></div></div>'''
    return f'''<article class="panel chart-panel"><div class="panel-heading"><div><span class="eyebrow">CONDITIONAL ECONOMICS</span><h2>{heading}</h2></div><span class="tiny-tag">MODEL UNITS</span></div><p class="panel-description">{description}</p><div class="economics-metrics"><div><span class="micro">ORIGINAL NET P&amp;L</span><strong class="green-text">{_number(original_ledger.get('net_pnl'), signed=True)}</strong></div>{paired_metric}</div><div class="chart-legend"><span><i class="legend-line original"></i>Original decisions</span>{paired_legend}</div>{_chart(report)}{controls}<details class="data-disclosure"><summary>View accessible equity data <span aria-hidden="true">+</span></summary>{_table(['Bar', 'Timestamp', 'Original equity', 'Intervention equity'], table_rows, table_id='equity-table', caption='Projected equity on the original price tape; values are model units')}</details><p class="chart-footnote">Conditional model output. The paired difference is not a causal attribution of strategy profit.</p></article>'''


def _overview(report: dict, artifacts: dict) -> str:
    witness = report.get("witness")
    steps = '''<div class="next-step"><span class="eyebrow">THE NEXT STEP</span><h3>Turn the witness into a guardrail.</h3><p>Run the exported invariant test, make the callback causal, then rerun the same fixture.</p><a class="text-link" href="#reproducer">Open the reproducer <span aria-hidden="true">↗</span></a></div>''' if witness else '''<div class="next-step"><span class="eyebrow">INTERPRET WITH CARE</span><h3>A bounded audit.</h3><p>No global claim of leak-free behavior follows from this report. Inspect coverage, rerun constraints, and unsupported fields.</p><a class="text-link" href="#method">Read the method <span aria-hidden="true">↗</span></a></div>'''
    return f'<section id="overview" class="view" aria-label="Overview">{_hero(report, artifacts)}<div class="overview-grid">{_economics_panel(report)}<aside class="witness-rail">{_decision_panel(report, compact=True)}{steps}</aside></div></section>'


def _evidence(report: dict) -> str:
    witness = report.get("witness")
    heading = '<div class="section-heading"><span class="eyebrow">02 / EVIDENCE</span><h1>A change you can inspect.</h1><p>The cutoff stays fixed. Only records unavailable at that moment are intervened on.</p></div>'
    if not witness:
        return f'<section id="evidence" class="view" aria-label="Evidence">{heading}{_decision_panel(report)}<div class="notice"><strong>{_escape(report.get("reason"))}</strong><p>Inspect Method for the callback stability, budget, and mutation scope behind this status.</p></div></section>'
    original = (report.get("baseline") or {}).get("trace", [])
    mutated = witness.get("mutated_trace", [])
    paired = {p.get("timestamp"): p for p in mutated}
    decision_rows = []
    cutoff_instant = datetime.fromisoformat(witness["cutoff"].replace("Z", "+00:00"))
    for point in original:
        if datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00")) <= cutoff_instant:
            after = paired.get(point.get("timestamp"), {})
            decision_rows.append([point.get("timestamp"), point.get("target"), after.get("target", "—"), "CHANGED" if after.get("target") != point.get("target") else "Same"])
    mutation_rows = []
    for row in witness.get("changed_rows", []):
        before, after = row.get("before", {}), row.get("after", {})
        for field in ["open", "high", "low", "close", "volume"]:
            if before.get(field) != after.get(field):
                mutation_rows.append([row.get("index"), row.get("timestamp"), row.get("available_at"), field, before.get(field), after.get(field)])
    diagnostic = f'''<details class="data-disclosure"><summary>Paired decision diagnostics <span aria-hidden="true">+</span></summary><div class="diagnostic-pair"><div><span class="eyebrow">ORIGINAL DECISION</span><pre>{_escape(_json(witness.get('before_decision'), pretty=True))}</pre></div><div><span class="eyebrow">INTERVENTION DECISION</span><pre>{_escape(_json(witness.get('after_decision'), pretty=True))}</pre></div></div></details>'''
    reduction = "Reduction completed under the declared budget." if witness.get("reduction_complete") else "Reduction was not completed; this is the verified witness available within the budget."
    return f'''<section id="evidence" class="view" aria-label="Evidence">{heading}<div class="evidence-grid">{_decision_panel(report)}<div class="proof-note"><span class="eyebrow">WHAT THE PAIR ESTABLISHES</span><h2>An unavailable record changed a decision at or before the cutoff.</h2><p>The original callback and intervened callback use the same history length, seed and configuration. Their paired targets differ at <span class="mono">{_escape(witness.get('decision_timestamp'))}</span>.</p><p>{_escape(reduction)} A reduced fixture is not guaranteed globally smallest.</p></div></div><article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">PREFIX COMPARISON</span><h2>Decisions at or before the cutoff</h2></div><span class="tiny-tag">TARGET EQUIVALENCE</span></div>{_table(['Decision timestamp', 'Original target', 'Intervention target', 'Comparison'], decision_rows, table_id='decision-table', caption='Paired prefix decision targets')}{diagnostic}</article><article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">THE INTERVENTION</span><h2>Unavailable records, before and after</h2></div><span class="tiny-tag">{len(witness.get('changed_rows', []))} RECORDS</span></div><p class="panel-description">Availability, rather than the event timestamp alone, determines whether a record can be changed. Row indices are zero-based; full history and the cutoff are retained.</p>{_table(['Row index', 'Event timestamp', 'Available at', 'Field', 'Original', 'Intervened'], mutation_rows, table_id='mutation-table', caption='Fields changed only in records unavailable at the fixed cutoff')}</article></section>'''


def _reproducer(report: dict, artifacts: dict) -> str:
    heading = '<div class="section-heading"><span class="eyebrow">03 / REPRODUCER</span><h1>Keep the evidence.<br><em>Catch the regression.</em></h1><p>A portable paired fixture turns an observed dependency into an executable invariant.</p></div>'
    if not artifacts.get("test") or not report.get("witness"):
        return f'<section id="reproducer" class="view" aria-label="Reproducer">{heading}<div class="unavailable"><span class="eyebrow">NO PAIRED FIXTURE</span><h3>No regression test was exported</h3><p>A verified decision witness is required before Tradeoff can export this reproducer. {_escape(report.get("reason") or "")}</p>{_artifact_link(artifacts["json"], "Download audit JSON") if artifacts.get("json") else ""}</div></section>'
    links = "".join(_artifact_link(path, {"fixture": "Paired fixture", "test": "Pytest regression", "receipt": "Integrity receipt", "json": "Full audit JSON"}.get(name, name)) for name, path in artifacts.items())
    return f'''<section id="reproducer" class="view" aria-label="Reproducer">{heading}<div class="reproducer-grid"><article class="command-panel"><div class="panel-kicker"><span class="eyebrow">RUN FROM THE EXPORT DIRECTORY</span><span class="tiny-tag">PYTHON + PYTEST</span></div><pre><code id="test-command">python -m pytest {_escape(artifacts['test'])}</code></pre><button class="button light js-only" type="button" data-copy="test-command">Copy command <span aria-hidden="true">⧉</span></button><p id="copy-status" class="copy-status" role="status">The command is selectable for manual copying.</p><div class="command-rule"></div><span class="micro">CALLBACK UNDER TEST</span><p class="mono callback-path">{_escape(report.get('strategy_ref') or 'Local callback')}</p><p>The generated test imports this callback. Install the project and pytest in your Python environment before running it.</p></article><aside class="replay-steps"><div><span class="step-number">01</span><h3>Reproduce the finding</h3><p>The test reruns each complete tape with the fixed seed, configuration and cutoff. The current dependency should fail prefix invariance.</p></div><div><span class="step-number">02</span><h3>Make the callback causal</h3><p>Remove access to unavailable information. Rebuild preprocessing and strategy state on every run.</p></div><div><span class="step-number">03</span><h3>Replay the same fixture</h3><p>A stable, causal callback should pass. Keep the test in your suite to catch future regressions.</p></div></aside></div><article class="panel artifact-panel"><div><span class="eyebrow">PORTABLE ARTIFACTS</span><h2>The audit, in four files.</h2><p>Sibling downloads work without a network connection. The receipt records hashes; it is not a signed attestation.</p></div><div class="artifact-links">{links}</div></article><div class="notice"><strong>Keep these files together.</strong><p>The fixture retains both full tapes. The generated test uses its sibling fixture and verifies content integrity before comparing decision prefixes.</p></div></section>'''


def _method(report: dict) -> str:
    coverage, settings = report.get("coverage", {}), report.get("settings", {})
    economics = report.get("economics") or {}
    assumptions = economics.get("assumptions") or {}
    labels = {"initial_cash": "Starting cash", "fee_fixed": "Fixed fee per fill", "fee_bps": "Notional fee (bps)", "spread_bps": "Full spread (bps)", "slippage_bps": "Per-side slippage (bps)", "fill_lag_bars": "Execution delay (bars)", "max_leverage": "Gross exposure / equity cap", "short_borrow_bps_annual": "Annual short borrow (bps)"}
    assumptions_html = _table(["Assumption", "Declared value"], [[labels.get(k, k.replace('_', ' ')), _json(v) if isinstance(v, (list, dict)) else v] for k, v in assumptions.items()], caption="Declared economic projection assumptions") if assumptions else '<p class="empty-description">No economic assumptions were supplied.</p>'
    notes = "".join(f"<li>{_escape(note)}</li>" for note in coverage.get("notes", []))
    scope = "Complete declared search" if coverage.get("complete") else "Partial declared search"
    ledger_rows = []
    for name, ledger in [("Original", economics.get("original")), ("Intervention", economics.get("intervention")), ("One-share buy / hold reference", economics.get("benchmark"))]:
        if ledger:
            ledger_rows.append([name, _number(ledger.get('final_equity')), _number(ledger.get('realized_pnl'), signed=True), _number(ledger.get('open_pnl'), signed=True), _number(ledger.get('total_fees')), _number(ledger.get('total_borrow_cost', 0)), _number(ledger.get('net_pnl'), signed=True)])
    ledger_html = f'<article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">ACCOUNTING RECONCILIATION</span><h2>Realized, open, and net</h2></div></div><p class="panel-description">Realized plus open P&amp;L equals final equity minus starting cash. The last position is marked at the final close; no terminal sale is invented.</p>{_table(["Projection", "Final equity", "Realized P&L", "Open P&L", "Fees", "Borrow costs", "Net P&L"], ledger_rows, caption="Model-unit accounting and one-share reference")}</article>' if ledger_rows else ""
    sensitivities = economics.get("sensitivity") or []
    sensitivity_rows = [[s.get('name'), _json(s.get('settings', {})),
        _number((s.get('original') or {}).get('net_pnl'), signed=True),
        _number((s.get('intervention') or {}).get('net_pnl'), signed=True),
        _number(s.get('delta'), signed=True),
        (s.get('status') or 'PROJECTED') + (': ' + s['reason'] if s.get('reason') else '')]
        for s in sensitivities]
    sensitivity_html = f'<article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">ASSUMPTION SENSITIVITY</span><h2>The same decisions, different costs</h2></div></div>{_table(["Scenario", "Declared settings", "Original net P&L", "Intervention net P&L", "Difference", "Status / reason"], sensitivity_rows, table_id="sensitivity-table", caption="Declared execution cost and timing sensitivity; unavailable projections have no invented values")}</article>' if sensitivities else ""
    fill_details = ""
    for name, ledger in [("Original", economics.get("original")), ("Intervention", economics.get("intervention"))]:
        if ledger:
            fills = ledger.get("fills", [])
            fill_details += f'<details class="data-disclosure"><summary>{name} fill ledger · {len(fills)} fills <span aria-hidden="true">+</span></summary>{_table(["Fill timestamp", "Signal timestamp", "Side", "Quantity", "Reference price", "Fill price", "Fee"], [[f.get("timestamp"), f.get("signal_timestamp"), f.get("side"), f.get("quantity"), _number(f.get("reference_price")), _number(f.get("fill_price")), _number(f.get("fee"))] for f in fills], caption=f"{name} projection actual fills")}<p class="small-note">Rejected orders: {_escape(_json(ledger.get("rejected_orders", [])))}</p></details>'
            events = ledger.get("risk_events", [])
            if events:
                fill_details += f'<details class="data-disclosure"><summary>{name} exposure and insolvency observations <span aria-hidden="true">+</span></summary><p class="small-note">These events do not trigger forced liquidation in the projection.</p><pre>{_escape(_json(events, pretty=True))}</pre></details>'
            charges = ledger.get("borrow_charges", [])
            if charges:
                fill_details += f'<details class="data-disclosure"><summary>{name} short borrow ledger <span aria-hidden="true">+</span></summary>{_table(["Timestamp", "Interval seconds", "Prior short units", "Annual bps", "Charge"], [[c.get("timestamp"), c.get("elapsed_seconds"), c.get("quantity"), c.get("annual_bps"), _number(c.get("amount"))] for c in charges], caption=f"{name} short borrow accruals")}</details>'
    provenance = report.get("provenance")
    if provenance:
        fill_details += f'<article class="panel evidence-panel"><span class="eyebrow">PUBLIC STRATEGY PROVENANCE</span><h2>Pinned code, synthetic input.</h2><p class="panel-description">The source version, extraction boundaries and repair are recorded below. This case does not measure live performance.</p><pre>{_escape(_json(provenance, pretty=True))}</pre></article>'
    return f'''<section id="method" class="view" aria-label="Method"><div class="section-heading"><span class="eyebrow">04 / METHOD</span><h1>Know what the audit establishes.</h1><p>Availability-aware interventions, repeated callbacks and a declared execution model.</p></div><div class="method-grid"><article class="panel"><span class="eyebrow">SEARCH COVERAGE</span><h2>{scope}</h2><dl class="method-facts"><div><dt>Callback runs / budget</dt><dd class="mono">{_escape(coverage.get('runs', 0))} / {_escape(settings.get('max_calls', '—'))}</dd></div><div><dt>Cutoffs probed / eligible</dt><dd class="mono">{_escape(coverage.get('cutoffs_probed', '—'))} / {_escape(coverage.get('eligible_cutoffs', '—'))}</dd></div><div><dt>Completed interventions</dt><dd class="mono">{_escape(coverage.get('probes', 0))}</dd></div><div><dt>Reduction runs</dt><dd class="mono">{_escape(coverage.get('reduction_runs', 0))}</dd></div><div><dt>Minimum history</dt><dd class="mono">{_escape(settings.get('min_history', '—'))} bars</dd></div><div><dt>Maximum sampled cutoffs</dt><dd class="mono">{_escape(settings.get('max_probes', '—'))}</dd></div><div><dt>Seed</dt><dd class="mono">{_escape(settings.get('seed', '—'))}</dd></div></dl><ul class="coverage-notes">{notes}</ul><p class="small-note">{_escape(report.get('reason') or '')}</p></article><article class="panel"><span class="eyebrow">ECONOMIC ASSUMPTIONS</span><h2>Execution is a model.</h2>{assumptions_html}<p class="small-note">{_escape(economics.get('explanation') or 'No economic projection was supplied.')}</p><p class="small-note">Reference bars are midpoint prices. Fills use half the full spread plus per-side slippage, with fees once per actual fill. Persistent rejected targets retry. Short exposure and leveraged long exposure are constrained by the declared cap; closing a losing position can leave debt. No maintenance-margin liquidation is simulated.</p></article></div>{ledger_html}{sensitivity_html}{fill_details}<article class="method-process"><div><span class="step-number">01</span><h3>Establish stability</h3><p>Repeat identical input runs and compare targets. Callback failures or instability block a comparable audit.</p></div><div><span class="step-number">02</span><h3>Intervene on availability</h3><p>Keep timestamps and cutoff fixed. Scale coherent OHLC and volume only where availability is later than cutoff.</p></div><div><span class="step-number">03</span><h3>Compare the past</h3><p>Compare timestamps and signed target quantities at or before cutoff. Features and reasons are diagnostics.</p></div><div><span class="step-number">04</span><h3>Reduce and verify</h3><p>Greedily reduce changed records while preserving full history. Repeat the final pair within the call budget.</p></div></article><div class="notice limitations"><span class="eyebrow">LIMITS OF THE CLAIM</span><h3>Evidence of a dependency is precise. Coverage is bounded.</h3><p>FOUND means an observed target changed under a verified intervention on unavailable data. NO_DEPENDENCY_OBSERVED means only that the inspected interventions did not change past targets. INCONCLUSIVE means a blocker prevented a comparable result.</p><p>This release covers one instrument, signed and fractional units, bar-close decisions, deterministic callbacks, and declared OHLC / volume mutations. Extra fields are outside mutation coverage. A passing audit is not a leak-free or profitability certificate. Observed-position adapters apply an additional timing transformation in the economic projection.</p><details class="data-disclosure"><summary>Audit identity and callback configuration <span aria-hidden="true">+</span></summary><dl class="method-facts"><div><dt>Schema</dt><dd class="mono">{_escape(report.get('schema_version'))}</dd></div><div><dt>Created</dt><dd class="mono">{_escape(report.get('created_at'))}</dd></div><div><dt>Input SHA-256</dt><dd class="mono break-all">{_escape(report.get('dataset', {}).get('input_hash'))}</dd></div></dl><pre>{_escape(_json(report.get('config', {}), pretty=True))}</pre></details></div></section>'''


def _document(content: str, *, title: str, report: dict, nav: str = "", body_class: str = "", header_meta: str = "", footer_meta: str = "") -> str:
    resources = files("tradeoff.report")
    # JavaScript numbers cannot distinguish adjacent native integers above 2^53.
    # Keep numeric report.json unchanged and transport quantity labels as text.
    display_targets = {
        "original": [str(item.get("target", "—")) for item in (report.get("baseline") or {}).get("trace", [])],
        "intervention": [str(item.get("target", "—")) for item in (report.get("witness") or {}).get("mutated_trace", [])],
    }
    browser_data = {**report, "display_targets": display_targets}
    replacements = {
        "TITLE": _escape(title), "CSS": resources.joinpath("assets/report.css").read_text(encoding="utf-8"),
        "VERSION": _escape(__version__),
        "JS": resources.joinpath("assets/report.js").read_text(encoding="utf-8"),
        "DATA": _json(browser_data).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"),
        "NAV": nav, "CONTENT": content, "BODY_CLASS": _escape(body_class),
        "HEADER_META": _escape(header_meta), "FOOTER_META": _escape(footer_meta),
    }
    template = resources.joinpath("template.html").read_text(encoding="utf-8")
    # Substitute only tokens in the template, never inside untrusted content.
    return re.sub(r"@@([A-Z_]+)@@", lambda match: replacements[match.group(1)], template)


def render_report(report: dict) -> str:
    """Return standalone offline HTML. Unsafe sibling artifact paths raise ValueError."""
    reject_sensitive_data(report)
    _status(report.get("status"))
    artifacts = {key: _safe_path(path) for key, path in (report.get("artifacts") or {}).items() if path is not None}
    nav = '<nav class="view-nav" aria-label="Report views">' + "".join(f'<a href="#{name.lower()}" data-view="{name.lower()}"><span class="mono">0{i}</span>{name}</a>' for i, name in enumerate(["Overview", "Evidence", "Reproducer", "Method"], 1)) + '<span class="nav-caption">DECISION INTEGRITY / AUDIT DOSSIER</span></nav>'
    content = _overview(report, artifacts) + _evidence(report) + _reproducer(report, artifacts) + _method(report)
    return _document(content, title=f"Tradeoff · {_status(report['status'])[1]}", report=report,
        nav=nav, body_class=f"report status-{_status(report['status'])[0]}",
        header_meta=f"AUDIT / {_date(report.get('created_at'))}", footer_meta="SELF-CONTAINED REPORT")


def write_report(report: dict, output_dir: str | Path) -> Path:
    """Write index.html and report.json; fixture export remains the caller's responsibility."""
    markup = render_report(report)
    encoded_report = _json(report, pretty=True) + "\n"
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(encoded_report, encoding="utf-8")
    page = destination / "index.html"
    page.write_text(markup, encoding="utf-8")
    return page


def write_gallery(output_dir: str | Path, scenarios: list[dict], *, collection: str = "synthetic") -> Path:
    """Write an offline directory of real demo scenarios with validated local links."""
    reject_sensitive_data(scenarios)
    if collection not in {"synthetic", "public"}:
        raise ValueError("collection must be synthetic or public")
    public = collection == "public"
    collection_label = "THE PUBLIC STRATEGY CASEBOOK" if public else "THE SYNTHETIC DEMO COLLECTION"
    intro = ("Pinned public strategy code on synthetic data. Compare the original findings with causal repairs using the same saved fixtures." if public else "Real local runs on synthetic data. Each report exposes its witness, coverage and execution assumptions.")
    cards = ""
    for i, scenario in enumerate(scenarios, 1):
        tone, _, _, _ = _status(scenario["status"])
        path = _safe_path(scenario["path"])
        cards += f'''<a class="scenario-card {tone}" href="{_escape(path)}"><div class="scenario-number mono">0{i}</div><div class="scenario-copy">{_pill(scenario['status'])}<h2>{_escape(scenario['name'])}</h2><p>{_escape(scenario.get('description', ''))}</p></div><span class="scenario-open">Inspect report <span aria-hidden="true">↗</span></span></a>'''
    content = f'''<div id="overview" class="gallery-hero"><span class="eyebrow">{collection_label}</span><h1>What did your strategy<br><em>know, and when?</em></h1><p>Audit a decision. Inspect the evidence. Keep a regression test.</p><div class="gallery-intro"><span class="mono">{len(scenarios):02d} SCENARIOS</span><p>{intro}</p></div></div><div class="scenario-list">{cards}</div><div class="gallery-bottom"><div><span class="eyebrow">A DEVELOPER'S INSTRUMENT</span><h2>Debug the dependency.<br>Then prove the fix.</h2></div><p>Tradeoff intervenes only on records unavailable at a fixed cutoff, compares earlier decisions, and exports a portable paired fixture when a dependency is found. No keys, network connection, or market-data download required.</p></div>'''
    markup = _document(content, title="Tradeoff · Public strategy casebook" if public else "Tradeoff · Synthetic demo collection", report={}, body_class="gallery", header_meta=f"{'PUBLIC CASES' if public else 'SYNTHETIC DEMO'} / {__version__}", footer_meta="NO-KEY LOCAL DEMOS")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    page = destination / "index.html"
    page.write_text(markup, encoding="utf-8")
    return page
