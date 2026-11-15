"""Offline decision-review interface. Financial results arrive as exact text."""
from decimal import Decimal, localcontext
import html
from importlib.resources import files
from pathlib import Path
import re

from ..feedback.contracts import FeedbackError
from ..feedback.serialization import validate_output


def _escape(value):
    return html.escape("Unknown" if value is None else str(value), quote=True)


def _table(caption, headers, rows):
    head = "".join(f'<th scope="col">{_escape(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_escape(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f'<div class="fb-table" tabindex="0" role="region" aria-label="{_escape(caption)}"><table><caption>{_escape(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _section(key, number, title, subtitle, content):
    return f'<section class="fb-section" id="{key}" aria-labelledby="{key}-title"><div class="fb-section-head"><div><span class="fb-kicker">{number} / DECISION REVIEW</span><h2 id="{key}-title">{title}</h2></div><p>{subtitle}</p></div>{content}</section>'


def _chart(episodes):
    known = [e for e in episodes if e["observed_net"] is not None][:8]
    if not known:
        return '<div class="fb-empty">No complete observed net outcomes to plot. Missing costs remain unknown.</div>'
    with localcontext() as ctx:
        ctx.prec = 128
        extent = max(abs(Decimal(e["observed_net"])) for e in known) or Decimal("1")
        height = 40 + len(known) * 42
        lines = [f'<svg class="fb-chart" viewBox="0 0 560 {height}" role="img" aria-label="Observed net cash flow in USD, eligible episodes only"><title>Observed net cash flow, USD</title><line x1="270" x2="270" y1="10" y2="{height-15}"/>']
        for i, e in enumerate(known):
            y = 22 + i * 42
            value = Decimal(e["observed_net"])
            width = abs(value) / extent * 135
            x = Decimal("270") - width if value < 0 else Decimal("270")
            lines.append(f'<text x="0" y="{y+12}">{_escape(e["symbol"])} · {_escape(e["agent_version"])}</text><rect class="{"negative" if value < 0 else "positive"}" x="{x:.2f}" y="{y}" width="{width:.2f}" height="19" rx="2"/><text class="amount" x="430" y="{y+13}">{_escape(e["observed_net"])}</text>')
        return "".join(lines) + "</svg>"


def render_feedback_report(report):
    validate_output(report)
    if report.get("schema_version") != "tradeoff.feedback-report.v1":
        raise FeedbackError("UNSUPPORTED_SCHEMA", "Unsupported feedback report schema")
    ev, quality = report["evaluation"], report["quality"]
    episodes, decisions = ev["episodes"], ev["decisions"]
    known = sum(e["observed_net"] is not None for e in episodes)
    closed = sum(e["status"] == "ATTRIBUTABLE_CLOSED" for e in episodes)
    prospective = sum(d["capture"]["classification"] == "PROSPECTIVE" for d in decisions)
    environments = report["environments"]
    label = "PAPER / SIMULATED" if "paper" in environments else "SIMULATED" if "simulated" in environments else "IMPORTED / RETROSPECTIVE" if environments else "NO EVIDENCE YET"
    if decisions and all(d["reference"]["source"] == "synthetic_demo" for d in decisions):
        label += " / SYNTHETIC DEMO"
    hero = f'''<div class="fb-summary"><h1>Decision review</h1><span class="fb-badge">{_escape(label)}</span><span class="fb-as-of">AS OF {_escape(report['as_of'])}</span></div>'''
    stats = '<div class="fb-stats">' + "".join(f'<div class="fb-stat"><span class="fb-label">{title}</span><strong class="{tone}">{value}</strong><small>{caption}</small></div>' for title, value, caption, tone in [
        ("RECORDED DECISIONS", len(decisions), "holds and skips included", ""),
        ("ATTRIBUTABLE CLOSED", f"{closed} / {len(episodes)}", "resolved ownership", ""),
        ("OBSERVED NET KNOWN", f"{known} / {len(episodes)}", "applicable cost coverage required", "" if known == len(episodes) and episodes else "fb-amber"),
        ("PROSPECTIVE CAPTURE", f"{prospective} / {len(decisions)}", "declared local clock policy", "")]) + "</div>"
    checks = [("Inventory baseline", quality.get("inventory_resolved", False)),
              ("Order bindings", quality.get("bindings_complete", False)),
              ("Episode attribution", quality.get("attribution_complete", False)),
              ("Broker fetch for interval", quality.get("fetch_complete", False))]
    check_html = "".join(f'<div class="fb-check"><span>{name}</span><b class="{"complete" if value else ""}">{"Resolved" if value else "Incomplete / unverified"}</b></div>' for name, value in checks)
    findings = ev["findings"]
    finding_html = "".join(f'<div class="fb-finding"><code>{_escape(f["code"])}</code><p>{_escape(f["action"])}</p></div>' for f in findings[:16]) or '<p class="fb-green">No supported evidence issue detected.</p>'
    quality_html = f'<div class="fb-columns"><div class="fb-panel"><h3>Evidence coverage</h3>{check_html}</div><div class="fb-panel"><h3>Next checks <span class="subtle">/ {len(findings)} findings</span></h3><div class="fb-findings" tabindex="0" role="region" aria-label="Evidence findings">{finding_html}</div></div></div>'
    if known < len(episodes):
        comparison = report.get("comparison")
        if (comparison and comparison.get("schema_version") == "tradeoff.simulated-account-comparison.v1"
                and comparison.get("status") == "MODELED_ACCOUNT_COMPARISON"):
            quality_html += '<p class="fb-note"><strong>Observed episode net unavailable.</strong> Unknown observed net results stay unknown. Modeled account costs are declared assumptions.</p>'
        else:
            quality_html += '<p class="fb-note"><strong>Cost coverage incomplete.</strong> Unknown net results stay unknown. Fee schedules and assumptions are modeled evidence.</p>'
    if not decisions:
        quality_html += '<p class="fb-note">Connect your recorder. Capture intent before submission, then bind the actual order ID. Demo evidence is synthetic.</p>'
    decision_html = _table("Recorded decisions · exact quantities",
        ["Decision / version", "Intent", "Quantity", "Capture", "Horizon outcome", "Price change"],
        [[d["decision_id"] + " / " + d["agent_version"], d["symbol"] + " · " + d["action"], d["intended_quantity"],
          d["capture"]["classification"], d["outcome_status"], d["horizon_price_change"]] for d in decisions]) if decisions else '<div class="fb-empty">No decisions recorded. Run the feedback demo or connect your agent hook.</div>'
    decision_html += '<p class="fb-note">Price change is a market observation. Sell may close a long. Hold and skip receive no invented realized profit.</p>'
    workstation = f'''<div class="feedback-workstation audit-workstation" role="group" aria-label="Decision workstation"><div class="workstation-topline"><h2>Observed net cash flow</h2><span class="fb-label">USD · KNOWN NET ONLY</span></div><div class="workstation-layout"><div class="feedback-chart-stage">{_chart(episodes)}<p class="fb-chart-note">Up to 8 eligible episodes. Unknown costs remain unknown.</p></div><aside class="feedback-inspector bar-inspector" role="group" aria-label="Evidence summary"><h3>Evidence summary</h3><dl class="inspector-facts"><div><dt>Known observed net</dt><dd>{known} / {len(episodes)}</dd></div><div><dt>Unknown observed net</dt><dd class="{'fb-amber' if known < len(episodes) else ''}">{len(episodes) - known} / {len(episodes)}</dd></div><div><dt>Attributable closed</dt><dd>{closed} / {len(episodes)}</dd></div><div><dt>Prospective capture</dt><dd>{prospective} / {len(decisions)}</dd></div></dl><p class="fb-note">Paper fills are simulated. Descriptive differences do not establish better live trading.</p><details><summary>Receipt limits</summary><p class="fb-code">Local receipts do not authenticate source records or prove an agent never saw future data.</p></details><a class="text-link" href="#quality">Review evidence coverage <span aria-hidden="true">→</span></a></aside></div></div>'''
    outcome_html = _table("Execution episodes · observed and modeled net shown separately",
        ["Episode", "Direction", "Status", "Gross / USD", "Observed net / USD", "Modeled net / USD", "Cost coverage"],
        [[e["episode_id"], e["direction"], e["status"], e["gross_cashflow"], e["observed_net"], e["modeled_net"], e["cost_coverage"]] for e in episodes]) if episodes else '<div class="fb-empty">No execution episodes. A flat position does not establish historical opening inventory.</div>'
    outcome_html += ''.join(f'<span class="fb-code" data-net-state="{"unknown" if e["observed_net"] is None else "known"}">{_escape(e["episode_id"])} / {_escape(", ".join(e["reasons"]) or "Complete supported evidence")}</span>' for e in episodes)
    comp = report.get("comparison")
    if comp and comp.get("schema_version") == "tradeoff.simulated-account-comparison.v1":
        compare_html = '<span class="fb-badge">MODELED SIMULATION</span>'
        compare_html += f'<p class="fb-note"><strong>{_escape(comp["status"])} · {_escape(comp["matched_count"])} common calendar opportunities · {_escape(comp["capture_class"])}</strong><br>{_escape(comp["scope"])}</p>'
        metrics, accounts = comp.get("metrics", {}), comp.get("accounts", {})
        account_rows = [
            ("Initial cash / USD", "initial_cash"), ("Final cash / USD", "final_cash"),
            ("Final holdings / shares", "final_shares"), ("Terminal equity / USD", "terminal_equity"),
            ("Modeled net P&L / USD", "net_pnl"), ("Explicit modeled fees / USD", "explicit_fees"),
            ("Maximum drawdown / bps", "max_drawdown_bps"), ("Filled notional / USD", "filled_notional"),
            ("Turnover / initial cash", "turnover"), ("Filled executions", "fill_count"),
            ("Recorded decisions", "decision_count"), ("Hold decisions", "hold_count")]
        complete = comp["status"] == "MODELED_ACCOUNT_COMPARISON" and all(
            isinstance(accounts.get(side), dict) and all(accounts[side].get(key) is not None
                for key in [key for _, key in account_rows] + ["net_return_pct"])
            for side in ("baseline", "candidate")) and all(metrics.get(key) is not None
                for key in ("baseline_return_bps", "candidate_return_bps", "delta_return_bps"))
        if complete:
            with localcontext() as ctx:
                ctx.prec = 128
                delta_pp = format(Decimal(metrics["delta_return_bps"]) / Decimal("100"), "f")
            if "." in delta_pp:
                delta_pp = delta_pp.rstrip("0").rstrip(".")
            compare_html += '<div class="fb-comparison">' + ''.join(
                f'<div><span class="fb-label">{title}</span><strong>{_escape(value)} <small>{unit}</small></strong></div>'
                for title, value, unit in [
                    ("BASELINE ACCOUNT RETURN", accounts["baseline"]["net_return_pct"], "%"),
                    ("CANDIDATE ACCOUNT RETURN", accounts["candidate"]["net_return_pct"], "%"),
                    ("CANDIDATE − BASELINE", delta_pp, "pp")]) + '</div>'
            compare_html += _table("Modeled cash-stock accounts — same market calendar and starting cash",
                ["Account measure", "Baseline", "Candidate"],
                [[title, accounts["baseline"][key], accounts["candidate"][key]] for title, key in account_rows])
            compare_html += '<details class="data-disclosure"><summary>Account conventions <span aria-hidden="true">+</span></summary><p class="fb-note">Open holdings are valued at the terminal mark. Return includes cash, holdings and explicit modeled fill charges. Turnover = filled notional / initial cash. Drawdown uses the declared valuation calendar. Cost, execution and historical-ordering assumptions apply.</p></details>'
        else:
            compare_html += '<div class="fb-empty"><strong>Account results unavailable.</strong><br>Resolve exclusions and evidence gaps before interpreting returns.</div>'
        compare_html += _table("Recorded comparison population — holds and skips included", ["Agent version", "Decisions"],
            [[version, count] for version, count in comp.get("population_counts", {}).items()])
        compare_html += _table("Modeled simulation warnings", ["Warning"], [[warning] for warning in comp.get("warnings", [])])
        compare_html += _table("Comparison exclusions — unresolved evidence remains visible",
            ["Source", "Opportunity", "Decision", "Reason"],
            [[e.get("source_alias", "—"), e.get("opportunity_id", "—"), e.get("decision_id", "—"), e["reason"]]
                for e in comp["exclusions"]])
    elif comp:
        metrics = comp["metrics"]
        compare_html = '<div class="fb-comparison">' + ''.join(f'<div><span class="fb-label">{title}</span><strong>{_escape(value)} <small>bps</small></strong></div>' for title, value in [
            ("BASELINE MEAN", metrics["baseline_mean_bps"]), ("CANDIDATE MEAN", metrics["candidate_mean_bps"]), ("CANDIDATE − BASELINE", metrics["mean_delta_bps"])]) + '</div>'
        compare_html += f'<p class="fb-note"><strong>{_escape(comp["status"])} · {comp["matched_count"]} matched pairs · {_escape(comp["capture_class"])}</strong><br>{_escape(comp["scope"])}</p>'
        compare_html += _table("Comparison exclusions — all recorded opportunities remain visible", ["Opportunity", "Decision", "Reason"],
            [[e.get("opportunity_id", "—"), e.get("decision_id", "—"), e["reason"]] for e in comp["exclusions"]])
    else:
        compare_html = '<div class="fb-empty"><strong>No comparison plan selected.</strong><br>Register a plan before evaluation. Record both versions on matching opportunities. Eligible outcomes support a scoped comparison; no automatic winner.</div>'
    evidence_html = f'<div class="fb-panel"><h3>Evaluation checkpoint</h3><span class="fb-code">Sequence: {report["evidence"]["as_of_seq"]}<br>Head: {_escape(report["evidence"]["head_hash"])}<br>Report: {_escape(report["report_id"])}</span></div>'
    evidence_html += '<div class="fb-actions"><a href="feedback-report.json" download>Report JSON ↗</a><a href="feedback-evidence.json" download>Normalized evidence ↗</a><a href="feedback-receipt.json" download>Integrity receipt ↗</a><button type="button" data-print hidden>Print report</button></div><details class="data-disclosure"><summary>Export scope <span aria-hidden="true">+</span></summary><p class="fb-note">Review records before sharing. Broker IDs use local pseudonyms. Receipts bind bytes and checkpoints; they do not authenticate source. Your external agent controls provider submissions.</p></details>'
    body = hero + stats + workstation + _section("quality", "01", "Data quality", "Coverage, gaps and next checks.", quality_html)
    body += _section("decisions", "02", "Decisions", "Intent, capture and outcome state.", decision_html)
    body += _section("outcomes", "03", "Outcomes", "Exact quantities. Unknown costs remain unknown.", outcome_html)
    body += _section("compare", "04", "Compare", "Matched evidence for a declared change.", compare_html)
    body += _section("evidence", "05", "Evidence", "Records and evaluation checkpoint.", evidence_html)
    root = files("tradeoff.report")
    values = {"BODY": body, "CSS": root.joinpath("assets/report.css").read_text() + root.joinpath("assets/feedback.css").read_text(),
              "JS": root.joinpath("assets/feedback.js").read_text()}
    template = root.joinpath("feedback_template.html").read_text()
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m[1]], template)


def write_feedback_report(report, output_dir):
    page = render_feedback_report(report)
    folder = Path(output_dir)
    if not folder.is_dir() or folder.is_symlink() or (folder / "index.html").exists():
        raise FeedbackError("UNSAFE_OUTPUT", "Choose a report directory without an existing interface")
    path = folder / "index.html"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(page)
    return path
