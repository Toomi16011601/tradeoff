"""Rendered account comparisons retain the modeled scope and fail closed."""
from copy import deepcopy

import pytest

from tradeoff.report.feedback_renderer import render_feedback_report


def report_with(comparison):
    return {
        "schema_version": "tradeoff.feedback-report.v1", "report_id": "synthetic-report",
        "as_of": "2026-02-01T00:00:00+00:00", "environments": ["simulated"],
        "quality": {}, "evaluation": {"episodes": [], "decisions": [], "findings": []},
        "evidence": {"as_of_seq": 1, "head_hash": "a" * 64}, "comparison": comparison,
    }


def comparison():
    baseline = dict(initial_cash="100", final_cash="49", final_shares="5", terminal_equity="89",
        net_pnl="-11", net_return_pct="-11", net_return_bps="-1100", max_drawdown_bps="1834.86",
        filled_notional="50", turnover="0.5", explicit_fees="1", fill_count=1, decision_count=2,
        hold_count=1)
    candidate = dict(initial_cash="100", final_cash="100", final_shares="0", terminal_equity="100",
        net_pnl="0", net_return_pct="0", net_return_bps="0", max_drawdown_bps="0",
        filled_notional="0", turnover="0", explicit_fees="0", fill_count=0, decision_count=2,
        hold_count=2)
    return {
        "schema_version": "tradeoff.simulated-account-comparison.v1",
        "status": "MODELED_ACCOUNT_COMPARISON", "capture_class": "RETROSPECTIVE_PLAN",
        "scope": "One USD cash-stock account per version; declared cost and execution assumptions.",
        "accounts": {"baseline": baseline, "candidate": candidate},
        "metrics": {"baseline_return_bps": "-1100", "candidate_return_bps": "0", "delta_return_bps": "1100"},
        "timeline": [{"at": "2026-01-05T14:30:00+00:00", "price": "10", "baseline_equity": "100", "candidate_equity": "100"},
            {"at": "2026-01-07T14:30:00+00:00", "price": "8", "baseline_equity": "89", "candidate_equity": "100"}],
        "matched_count": 2, "population_counts": {"v1": 2, "v2": 2}, "pairs": [],
        "market_path_hash": "b" * 64, "warnings": ["HISTORICAL_TIMESTAMPS_UNVERIFIED"],
        "exclusions": [],
    }


def compare_section(comp):
    page = render_feedback_report(report_with(comp))
    return page.split('id="compare"', 1)[1].split('</section>', 1)[0]


def test_modeled_accounts_show_total_returns_and_open_terminal_holdings():
    # Sending the new schema to the episode-pair branch must not hide open holdings.
    section = compare_section(comparison())
    for text in ("MODELED SIMULATION", "BASELINE ACCOUNT RETURN", "CANDIDATE ACCOUNT RETURN",
            "CANDIDATE − BASELINE", "-11", "11", "pp", "Final cash / USD", "Final holdings / shares",
            "Terminal equity / USD", "Explicit modeled fees / USD", "Maximum drawdown / bps",
            "Turnover / initial cash", "49", "89", "0.5", "1834.86", "RETROSPECTIVE_PLAN",
            "2 common calendar opportunities", "HISTORICAL_TIMESTAMPS_UNVERIFIED"):
        assert text in section
    assert "<strong>-11 <small>%</small></strong>" in section
    assert "<strong>0 <small>%</small></strong>" in section
    assert "<strong>11 <small>pp</small></strong>" in section
    assert "Open holdings are valued at the terminal mark" in section
    assert "matched pairs" not in section
    assert "observed" not in section.lower()
    assert "winner" not in section.lower()


@pytest.mark.parametrize("status", ["INSUFFICIENT_EVIDENCE", "NOT_COMPARABLE", "UNRECOGNIZED_RESULT", "MODELED_ACCOUNT_COMPARISON"])
def test_blocked_or_unknown_status_cannot_render_account_values(status):
    # Even a malformed blocked response carrying numbers must not publish them.
    comp = comparison()
    comp["status"] = status
    comp["metrics"] = dict.fromkeys(comp["metrics"])
    comp["exclusions"] = [{"source_alias": "baseline-source", "reason": "TERMINAL_MARK_MISSING"}]
    section = compare_section(comp)
    assert status in section
    assert "Account results unavailable" in section
    assert "TERMINAL_MARK_MISSING" in section
    assert "HISTORICAL_TIMESTAMPS_UNVERIFIED" in section
    for value in ("49", "89", "1834.86", "-11"):
        assert value not in section
    assert "BASELINE ACCOUNT RETURN" not in section


def test_all_comparison_diagnostics_are_escaped_as_text():
    # Scope, warnings, source aliases and counts must never create HTML attributes/tags.
    hostile = '</script><img src=x onerror=alert(1)> {{BODY}}'
    comp = comparison()
    comp["capture_class"] = comp["scope"] = hostile
    comp["warnings"] = [hostile]
    comp["exclusions"] = [{"reason": hostile, "source_alias": hostile,
        "decision_id": hostile, "opportunity_id": hostile}]
    comp["population_counts"] = {hostile: 2}
    section = compare_section(comp)
    assert '<img src=x' not in section
    assert '&lt;img src=x' in section
    assert '{{BODY}}' in section


def test_legacy_episode_comparison_keeps_mean_bps_and_pair_labels():
    comp = dict(status="DESCRIPTIVE_COMPARISON", capture_class="PROSPECTIVE_PLAN", matched_count=2,
        scope="Eligible both-traded subset", metrics=dict(baseline_mean_bps="1430",
        candidate_mean_bps="1350", mean_delta_bps="-80"), exclusions=[])
    section = compare_section(deepcopy(comp))
    assert "BASELINE MEAN" in section
    assert "1430" in section and "-80" in section
    assert "2 matched pairs" in section
    assert "MODELED SIMULATION" not in section


def quality_section(comp):
    report = report_with(comp)
    report["evaluation"]["episodes"] = [dict(episode_id="open-modeled-holding", direction="long",
        status="OPEN", gross_cashflow="-50", observed_net=None, modeled_net=None,
        cost_coverage="MODELED", reasons=["COST_SCOPE_MODELED"])]
    page = render_feedback_report(report)
    return page.split('id="quality"', 1)[1].split('</section>', 1)[0]


def test_valid_modeled_account_note_scopes_unknown_net_to_observed_episodes():
    # A valid modeled comparison must not look blocked by its separate observed-net gap.
    section = quality_section(comparison())
    assert "Observed episode net unavailable" in section
    assert "Modeled account costs are declared assumptions" in section
    assert "Cost coverage incomplete" not in section


@pytest.mark.parametrize("status", ["INSUFFICIENT_EVIDENCE", "NOT_COMPARABLE", "UNRECOGNIZED_RESULT"])
def test_blocked_comparison_retains_incomplete_cost_quality_note(status):
    comp = comparison()
    comp["status"] = status
    section = quality_section(comp)
    assert "Cost coverage incomplete" in section
    assert "Observed episode net unavailable" not in section


def test_legacy_episode_review_retains_incomplete_cost_quality_note():
    section = quality_section(None)
    assert "Cost coverage incomplete" in section
    assert "Observed episode net unavailable" not in section
