"""The first viewport pairs actual results with the limits of that evidence."""
import json
import re

from test_report_coverage_visibility import VisibleGroup
import pytest


def test_execution_workstation_leads_with_native_comparison():
    from test_failure_report import sample_report
    from tradeoff.report.failure_renderer import render_failure_report

    data = sample_report()
    data["coverage"].update(completed=1, total=3, complete=False)
    page = render_failure_report(data)
    overview = VisibleGroup(page, "Execution workstation").text
    assert "1,100.00" in overview and "990.00" in overview
    assert page.index('id="comparison"') < page.index('id="scenarios"')
    coverage = VisibleGroup(page, "Execution coverage").text
    assert re.search(r"1\s*/\s*3", coverage) and "Partial" in coverage


@pytest.mark.parametrize("status", ["INCONCLUSIVE", "BASELINE_FAILED"])
def test_execution_blocker_is_visible_before_any_closed_details(status):
    from test_failure_report import sample_report
    from tradeoff.report.failure_renderer import render_failure_report

    data = sample_report()
    data.update(status=status, reason="SYNTHETIC_ENGINE_INPUT_UNAVAILABLE")
    page = render_failure_report(data)
    assert "SYNTHETIC_ENGINE_INPUT_UNAVAILABLE" in VisibleGroup(page, "Execution blocker").text


def test_feedback_workstation_plots_observed_net_once_with_evidence(tmp_path):
    from test_feedback_export import export_fixture

    export_fixture(tmp_path)
    page = (tmp_path / "feedback-output/index.html").read_text()
    overview = VisibleGroup(page, "Decision workstation").text
    assert "0.95" in overview
    assert page.count('class="fb-chart"') == 1
    assert "Observed net cash flow" in overview
    assert VisibleGroup(page, "Evidence summary").text


def test_feedback_workstation_keeps_missing_borrow_cost_unknown(tmp_path):
    from feedback_helpers import episode_records
    from test_feedback_export import export_fixture

    export_fixture(tmp_path, records=episode_records(short=True))
    page = (tmp_path / "feedback-output/index.html").read_text()
    report = json.loads((tmp_path / "feedback-output/feedback-report.json").read_text())
    assert report["evaluation"]["episodes"][0]["observed_net"] is None
    overview = VisibleGroup(page, "Decision workstation").text
    assert "No complete observed net outcomes" in overview
    inspector = VisibleGroup(page, "Evidence summary").text
    assert "unknown" in inspector.lower()
    assert 'data-net-state="unknown"' in page
