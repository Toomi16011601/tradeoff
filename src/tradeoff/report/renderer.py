"""Render JSON audit records without network services or active data markup."""
from __future__ import annotations

import html
import json
import math
import re
import shlex
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from .. import __version__
from ..privacy import reject_sensitive_data
from .workstation import recorded_data, render_workstation


STATES = {
    "FOUND": ("found", "Future dependency found", "Future data changed", "a past decision."),
    "NO_DEPENDENCY_OBSERVED": ("clear", "No dependency observed", "No dependency observed.", "Within the sampled scope."),
    "INCONCLUSIVE": ("uncertain", "Audit inconclusive", "Audit inconclusive.", "Evidence is incomplete."),
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
    return f'<a class="{css}" href="{_escape(_safe_path(path))}" target="_blank" rel="noopener">{_escape(label)}<span aria-hidden="true">↗</span></a>'


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
        return '<div class="empty-note"><span class="eyebrow">WITNESS</span><h3>No witness is available</h3><p>No paired decision change was established.</p></div>'
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
      <a class="text-link" href="#evidence">Paired evidence <span aria-hidden="true">↗</span></a>
    </div>'''


def _hero(report: dict, artifacts: dict) -> str:
    witness = report.get("witness") or {}
    dataset, coverage = report.get("dataset") or {}, report.get("coverage") or {}
    before, after = _decision_target(witness.get("before_decision")), _decision_target(witness.get("after_decision"))
    pair = f'{_escape(before)} <span aria-label="changed to">→</span> {_escape(after)}' if witness else 'No paired witness'
    state = 'Complete' if coverage.get('complete') else 'Partial'
    replay = report.get('repair_replay') or {}
    repair = replay.get('status') if replay.get('status') in {'PASS', 'FAILED'} else 'NOT VERIFIED'
    provenance = report.get('provenance') or {}
    synthetic = ' · synthetic' if 'synth' in str(dataset.get('symbol', '')).lower() or 'synthetic' in str(provenance.get('input', '')).lower() else ''
    return f'''<div class="report-ribbon"><h1>Audit workstation</h1><span class="mono">{_escape(dataset.get('symbol', 'DATASET'))} · {_escape(dataset.get('row_count', 0))} bars{synthetic} · offline</span></div><div class="audit-summary" role="group" aria-label="Audit coverage"><div class="summary-verdict">{_pill(report['status'])}</div><div class="summary-pair"><strong>{pair}</strong><span>{'Observed position units' if report.get('trace_kind') == 'observed_position' else 'Target units'}</span></div><div><strong>{len(witness.get('changed_rows', []))}</strong><span>Changed future records</span></div><div><strong>{_escape(coverage.get('cutoffs_probed', '—'))} / {_escape(coverage.get('eligible_cutoffs', '—'))}</strong><span>{state} declared search · cutoffs</span></div><a class="summary-repair" data-status="{_escape(repair)}" href="#saved-fixture"><strong>Repair {_escape(repair)}</strong><span>Same saved fixture only</span></a></div>'''


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
    description = "Paired projections on the original tape. Same execution assumptions." if intervention_ledger else "Original decisions projected on the original tape."
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
    return f'''<article class="panel chart-panel"><div class="panel-heading"><div><span class="eyebrow">CONDITIONAL ECONOMICS</span><h2>{heading}</h2></div><span class="tiny-tag">PROJECTED · MODEL UNITS</span></div><p class="panel-description">{description}</p><div class="economics-metrics"><div><span class="micro">ORIGINAL NET P&amp;L</span><strong class="green-text">{_number(original_ledger.get('net_pnl'), signed=True)}</strong></div>{paired_metric}</div><div class="chart-legend"><span><i class="legend-line original"></i>Original decisions</span>{paired_legend}</div>{_chart(report)}{controls}<details class="data-disclosure"><summary>Equity data <span aria-hidden="true">+</span></summary>{_table(['Bar', 'Timestamp', 'Original equity', 'Intervention equity'], table_rows, table_id='equity-table', caption='Projected equity on the original price tape; values are model units')}</details><p class="chart-footnote">Model output. Paired difference does not establish causal profit attribution.</p></article>'''


def _overview(report: dict, artifacts: dict) -> str:
    primary = _artifact_link(artifacts["test"], "Open regression test", primary=True) if artifacts.get("test") else _artifact_link(artifacts["json"], "Open audit JSON", primary=True) if artifacts.get("json") else ""
    return f'''<section id="overview" class="view" aria-label="Overview">{_hero(report, artifacts)}{render_workstation(report)}<div class="workstation-footnote"><p>{_escape(report.get('reason') or '')}</p><a href="#method">Scope &amp; limits</a></div><details id="saved-fixture" class="data-disclosure saved-fixture"><summary>Saved fixture &amp; repair <span aria-hidden="true">+</span></summary><div class="investigation-grid"><article class="witness-card">{_decision_panel(report, compact=True)}</article>{_repair_panel(report, artifacts)}</div>{primary}</details><details class="data-disclosure economics-disclosure"><summary>Conditional economic projection <span aria-hidden="true">+</span></summary>{_economics_panel(report)}</details></section>'''


def _command_location(reference: Any, artifact: str) -> tuple[str, str, str]:
    package = str(reference or "").split(":", 1)[0].split(".", 1)[0]
    if package in {"tradeoff", "backtest_witness"}:
        return "THE EXPORT DIRECTORY", artifact, ""
    guidance = ('<p class="small-note">Replace path/to/report with the directory containing this report '
                '(for example, .tradeoff/check-…). Keep your working directory at the strategy project '
                'root so imports and companion files remain available.</p>')
    return "YOUR STRATEGY PROJECT ROOT", f"path/to/report/{artifact}", guidance


def _repair_panel(report: dict, artifacts: dict) -> str:
    replay = report.get("repair_replay") or {}
    status = replay.get("status")
    label = status if status in {"PASS", "FAILED"} else "NOT VERIFIED"
    tone = {"PASS": "clear", "FAILED": "found"}.get(status, "uncertain")
    explanation = {
        "PASS": "Passed prefix invariance on the same saved fixture. This case only.",
        "FAILED": "Replay failed on the same saved fixture. Repair remains unverified.",
    }.get(status, "No completed replay on the same saved fixture. Repair remains unverified.")
    patch = (report.get("provenance") or {}).get("fixed_patch")
    patch_html = f'<div class="repair-patch"><span class="micro">DECLARED REPAIR</span><p>{_escape(patch if isinstance(patch, str) else _json(patch))}</p></div>' if patch else '<p class="small-note">No repair explanation was supplied.</p>'
    adapter = replay.get("adapter")
    adapter_html = f'<span class="micro">REPAIRED CALLBACK</span><p class="mono repair-adapter">{_escape(adapter)}</p>' if adapter else ""
    if adapter and artifacts.get("fixture"):
        directory, fixture_path, guidance = _command_location(adapter, artifacts["fixture"])
        command_text = f'tradeoff reproduce {shlex.quote(fixture_path)} --adapter {shlex.quote(str(adapter))}'
        command = f'<div class="repair-action"><span class="micro">REPLAY FROM {directory}</span>{guidance}<pre><code id="repair-command">{_escape(command_text)}</code></pre><button class="button js-only" type="button" data-copy="repair-command" data-copy-status="repair-copy-status">Copy command <span aria-hidden="true">⧉</span></button><p id="repair-copy-status" class="copy-status" role="status">The command is selectable for manual copying.</p></div>'
    else:
        command = '<a class="text-link" href="#reproducer">Replay instructions <span aria-hidden="true">↗</span></a>'
    reason = f'<p class="repair-reason">{_escape(replay["reason"])}</p>' if replay.get("reason") else ""
    return f'<article class="panel repair-panel" aria-label="Saved-fixture repair"><div class="panel-kicker"><span class="eyebrow">03 / VERIFY THE REPAIR</span><span class="status-pill {tone}">Repair {label}</span></div><h2>Saved-fixture repair</h2><p class="panel-description">{explanation}</p>{adapter_html}{command}<p class="small-note">Check warmup and strategy activity before generalizing.</p><details class="data-disclosure"><summary>Repair details <span aria-hidden="true">+</span></summary>{reason}{patch_html}<p>Original tape, cutoff, availability timestamps and configuration are retained. No source-line attribution or global leak-free claim.</p></details></article>'


def _availability_timeline(report: dict, *, detailed: bool = False) -> str:
    witness = report.get("witness")
    if not witness:
        return ""
    changes = witness.get("changed_rows") or []
    available = sorted({row["available_at"] for row in changes if row.get("available_at")},
                       key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")))
    first = available[0] if available else None
    items = f'<li><span class="micro">EARLIER DECISION</span><time class="mono">{_escape(witness.get("decision_timestamp"))}</time><span>Paired traces differ.</span></li><li class="timeline-boundary"><span class="micro">FIXED CUTOFF</span><time class="mono">{_escape(witness.get("cutoff"))}</time><span>History held fixed.</span></li><li class="timeline-unavailable"><span class="micro">CHANGED INPUT FIRST AVAILABLE</span><time class="mono">{_escape(first)}</time><span>{len(changes)} changed records unavailable at cutoff.</span></li>'
    table = ""
    if detailed:
        cutoff = datetime.fromisoformat(witness["cutoff"].replace("Z", "+00:00"))
        rows = []
        for row in changes:
            value = row.get("available_at")
            state = "Availability not supplied" if not value else "Unavailable at cutoff" if datetime.fromisoformat(value.replace("Z", "+00:00")) > cutoff else "Available at cutoff"
            rows.append([row.get("index"), row.get("timestamp"), value, state])
        table = _table(["Row index", "Event timestamp", "Available at", "Boundary"], rows,
                       table_id="availability-table", caption="Changed records against the fixed availability boundary")
    return f'<article class="panel availability-panel"><div class="panel-heading"><div><span class="eyebrow">AVAILABILITY TIMELINE</span><h2>Availability boundary</h2></div><a class="text-link" href="#evidence">Inspect records <span aria-hidden="true">↗</span></a></div><p class="panel-description">Unavailable = available after cutoff. Event time alone does not establish availability.</p><ol class="availability-timeline" aria-label="Decision and input availability timeline">{items}</ol>{table}</article>'


def _evidence(report: dict) -> str:
    witness = report.get("witness")
    heading = '<div class="section-heading"><span class="eyebrow">02 / EVIDENCE</span><h1>Paired decision evidence.</h1><p>Fixed cutoff. Changes only to unavailable records.</p></div>'
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
    reduction = "Reduction completed within budget." if witness.get("reduction_complete") else "Reduction incomplete; verified witness within budget."
    return f'''<section id="evidence" class="view" aria-label="Evidence">{heading}{_availability_timeline(report, detailed=True)}<div class="evidence-grid">{_decision_panel(report)}<div class="proof-note"><span class="eyebrow">WHAT THE PAIR ESTABLISHES</span><h2>Unavailable input. Earlier decision changed.</h2><p>Same history, seed and configuration. Targets differ at <span class="mono">{_escape(witness.get('decision_timestamp'))}</span>.</p><p>{_escape(reduction)} Global minimality is not established.</p></div></div><article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">PREFIX COMPARISON</span><h2>Decisions at or before the cutoff</h2></div><span class="tiny-tag">TARGET EQUIVALENCE</span></div>{_table(['Decision timestamp', 'Original target', 'Intervention target', 'Comparison'], decision_rows, table_id='decision-table', caption='Paired prefix decision targets')}{diagnostic}</article><article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">THE INTERVENTION</span><h2>Unavailable records, before and after</h2></div><span class="tiny-tag">{len(witness.get('changed_rows', []))} RECORDS</span></div><p class="panel-description">Changed records were unavailable at cutoff. Zero-based rows; full history retained.</p>{_table(['Row index', 'Event timestamp', 'Available at', 'Field', 'Original', 'Intervened'], mutation_rows, table_id='mutation-table', caption='Fields changed only in records unavailable at the fixed cutoff')}</article></section>'''


def _reproducer(report: dict, artifacts: dict) -> str:
    heading = '<div class="section-heading"><span class="eyebrow">03 / REPRODUCER</span><h1>Replay the saved case.</h1><p>The paired fixture checks prefix invariance.</p></div>'
    if not artifacts.get("test") or not report.get("witness"):
        return f'<section id="reproducer" class="view" aria-label="Reproducer">{heading}<div class="unavailable"><span class="eyebrow">NO PAIRED FIXTURE</span><h3>No regression test was exported</h3><p>A verified decision witness is required before Tradeoff can export this reproducer. {_escape(report.get("reason") or "")}</p>{_artifact_link(artifacts["json"], "Open audit JSON") if artifacts.get("json") else ""}</div></section>'
    directory, test_path, guidance = _command_location(report.get("strategy_ref"), artifacts["test"])
    links = "".join(_artifact_link(path, {"fixture": "Paired fixture", "test": "Pytest regression", "receipt": "Integrity receipt", "json": "Full audit JSON"}.get(name, name)) for name, path in artifacts.items())
    return f'''<section id="reproducer" class="view" aria-label="Reproducer">{heading}<div class="reproducer-grid"><article class="command-panel"><div class="panel-kicker"><span class="eyebrow">RUN FROM {directory}</span><span class="tiny-tag">PYTHON + PYTEST</span></div>{guidance}<pre><code id="test-command">python -m pytest {_escape(shlex.quote(test_path))}</code></pre><button class="button light js-only" type="button" data-copy="test-command">Copy command <span aria-hidden="true">⧉</span></button><p id="copy-status" class="copy-status" role="status">The command is selectable for manual copying.</p><div class="command-rule"></div><span class="micro">CALLBACK UNDER TEST</span><p class="mono callback-path">{_escape(report.get('strategy_ref') or 'Local callback')}</p><p>Use your strategy’s environment with Tradeoff, pytest and callback dependencies.</p></article><aside class="replay-steps"><div><span class="step-number">01</span><h3>Reproduce</h3><p>Run the saved full-tape pair. The dependency should fail prefix invariance.</p></div><div><span class="step-number">02</span><h3>Repair</h3><p>Remove unavailable-data access. Rebuild preprocessing and state on each run.</p></div><div><span class="step-number">03</span><h3>Replay</h3><p>Rerun the same fixture. Retain the test as a regression check.</p></div></aside></div><article class="panel artifact-panel"><div><span class="eyebrow">PORTABLE ARTIFACTS</span><h2>Saved artifacts.</h2><p>Open local files below. The receipt records hashes; it is not a signed attestation.</p></div><div class="artifact-links">{links}</div></article><div class="notice"><strong>Keep these files together.</strong><p>The fixture retains both full tapes. The generated test uses its sibling fixture and verifies content integrity before comparing decision prefixes.</p></div></section>'''


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
    ledger_html = f'<article class="panel evidence-panel"><div class="panel-heading"><div><span class="eyebrow">ACCOUNTING RECONCILIATION</span><h2>Realized, open, and net</h2></div></div><p class="panel-description">Realized + open P&amp;L = final equity − starting cash. Terminal positions use the final close; no invented sale.</p>{_table(["Projection", "Final equity", "Realized P&L", "Open P&L", "Fees", "Borrow costs", "Net P&L"], ledger_rows, caption="Model-unit accounting and one-share reference")}</article>' if ledger_rows else ""
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
        fill_details += f'<article class="panel evidence-panel"><span class="eyebrow">PUBLIC STRATEGY PROVENANCE</span><h2>Source and data provenance.</h2><p class="panel-description">Declared provenance. This case does not measure live performance.</p><details class="data-disclosure"><summary>Source, input &amp; repair <span aria-hidden="true">+</span></summary><pre>{_escape(_json(provenance, pretty=True))}</pre></details></article>'
    return f'''<section id="method" class="view" aria-label="Method"><div class="section-heading"><span class="eyebrow">04 / METHOD</span><h1>Scope &amp; assumptions.</h1><p>Declared search coverage and projection settings.</p></div><div class="method-grid"><article class="panel"><span class="eyebrow">SEARCH COVERAGE</span><h2>{scope}</h2><dl class="method-facts"><div><dt>Callback runs / budget</dt><dd class="mono">{_escape(coverage.get('runs', 0))} / {_escape(settings.get('max_calls', '—'))}</dd></div><div><dt>Cutoffs probed / eligible</dt><dd class="mono">{_escape(coverage.get('cutoffs_probed', '—'))} / {_escape(coverage.get('eligible_cutoffs', '—'))}</dd></div><div><dt>COMPLETED INTERVENTIONS</dt><dd class="mono">{_escape(coverage.get('probes', 0))}</dd></div><div><dt>Reduction runs</dt><dd class="mono">{_escape(coverage.get('reduction_runs', 0))}</dd></div><div><dt>Minimum history</dt><dd class="mono">{_escape(settings.get('min_history', '—'))} bars</dd></div><div><dt>Maximum sampled cutoffs</dt><dd class="mono">{_escape(settings.get('max_probes', '—'))}</dd></div><div><dt>Seed</dt><dd class="mono">{_escape(settings.get('seed', '—'))}</dd></div></dl><ul class="coverage-notes">{notes}</ul><p class="small-note">{_escape(report.get('reason') or '')}</p></article><article class="panel"><span class="eyebrow">ECONOMIC ASSUMPTIONS</span><h2>Projection settings.</h2>{assumptions_html}<p class="small-note">{_escape(economics.get('explanation') or 'No economic projection was supplied.')}</p><details class="data-disclosure"><summary>Execution conventions <span aria-hidden="true">+</span></summary><p>Reference bars are midpoint prices. Fills use half the spread plus per-side slippage; fees apply once per fill. Rejected targets retry. The declared cap limits short and leveraged long exposure. Closing a loss may leave debt. No maintenance-margin liquidation is simulated.</p></details></article></div>{ledger_html}{sensitivity_html}{fill_details}<article class="method-process"><div><span class="step-number">01</span><h3>Establish stability</h3><p>Repeat identical inputs. Failures or unstable targets block comparison.</p></div><div><span class="step-number">02</span><h3>Intervene on availability</h3><p>Hold timestamps and cutoff fixed. Mutate coherent OHLC/volume only after availability cutoff.</p></div><div><span class="step-number">03</span><h3>Compare the past</h3><p>Compare timestamps and signed targets at or before cutoff. Features and reasons are diagnostic.</p></div><div><span class="step-number">04</span><h3>Reduce and verify</h3><p>Reduce changed records, retain full history, then repeat the final pair within budget.</p></div></article><div class="notice limitations"><span class="eyebrow">LIMITS OF THE CLAIM</span><h3>Bounded evidence.</h3><p>FOUND: verified past-target change. NO_DEPENDENCY_OBSERVED: none in inspected interventions. INCONCLUSIVE: comparison blocked.</p><p>No global leak-free or profitability certificate.</p><details class="data-disclosure"><summary>Supported scope <span aria-hidden="true">+</span></summary><p>One instrument; signed and fractional units; bar-close decisions; deterministic callbacks; declared OHLC / volume mutations. Extra fields are outside mutation coverage. Observed-position adapters add a timing transformation to the economic projection.</p></details><details class="data-disclosure"><summary>Audit identity and callback configuration <span aria-hidden="true">+</span></summary><dl class="method-facts"><div><dt>Schema</dt><dd class="mono">{_escape(report.get('schema_version'))}</dd></div><div><dt>Created</dt><dd class="mono">{_escape(report.get('created_at'))}</dd></div><div><dt>Input SHA-256</dt><dd class="mono break-all">{_escape(report.get('dataset', {}).get('input_hash'))}</dd></div></dl><pre>{_escape(_json(report.get('config', {}), pretty=True))}</pre></details></div></section>'''


def _document(content: str, *, title: str, report: dict, nav: str = "", body_class: str = "", header_meta: str = "", footer_meta: str = "") -> str:
    resources = files("tradeoff.report")
    # JavaScript numbers cannot distinguish adjacent native integers above 2^53.
    # Keep numeric report.json unchanged and transport quantity labels as text.
    display_targets = {
        "original": [str(item.get("target", "—")) for item in (report.get("baseline") or {}).get("trace", [])],
        "intervention": [str(item.get("target", "—")) for item in (report.get("witness") or {}).get("mutated_trace", [])],
    }
    browser_data = {**report, "display_targets": display_targets, "workstation": recorded_data(report)}
    replacements = {
        "TITLE": _escape(title), "CSS": resources.joinpath("assets/report.css").read_text(encoding="utf-8"),
        "VERSION": _escape(__version__),
        "JS": resources.joinpath("assets/report.js").read_text(encoding="utf-8"),
        "DATA": _json(browser_data).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"),
        "NAV": nav, "CONTENT": content, "BODY_CLASS": _escape(body_class),
        "SHELL_CLASS": "terminal-shell" if "report" in body_class.split() else "",
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
    nav = '<nav class="view-nav" aria-label="Report views">' + "".join(f'<a href="#{name.lower()}" data-view="{name.lower()}"><span class="mono">0{i}</span>{name}</a>' for i, name in enumerate(["Overview", "Evidence", "Reproducer", "Method"], 1)) + '<span class="nav-caption">TEMPORAL AUDIT</span></nav>'
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
    content = f'''<div id="overview" class="gallery-hero"><span class="eyebrow">{collection_label}</span><h1>Temporal audit<br><em>casebook.</em></h1><p>Decision evidence. Saved fixtures. Verified repairs.</p><div class="gallery-intro"><span class="mono">{len(scenarios):02d} SCENARIOS</span><p>{intro}</p></div></div><div class="scenario-list">{cards}</div><div class="gallery-bottom"><div><span class="eyebrow">A DEVELOPER'S INSTRUMENT</span><h2>Find the dependency.<br>Verify the repair.</h2></div><p>Unavailable records are changed at a fixed cutoff. Earlier decisions are compared; verified findings include a replay fixture. Runs locally, offline.</p></div>'''
    markup = _document(content, title="Tradeoff · Public strategy casebook" if public else "Tradeoff · Synthetic demo collection", report={}, body_class="gallery", header_meta=f"{'PUBLIC CASES' if public else 'SYNTHETIC DEMO'} / {__version__}", footer_meta="NO-KEY LOCAL DEMOS")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    page = destination / "index.html"
    page.write_text(markup, encoding="utf-8")
    return page
