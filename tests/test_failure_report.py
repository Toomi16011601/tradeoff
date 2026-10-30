"""Offline failure reports retain native evidence and explicit unavailable states."""
import copy
import json
import re
from html.parser import HTMLParser

import pytest


class Page(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags = []
        self.words = []
        self.hidden = 0
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag in {'script', 'style'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.words.append(data)

    @property
    def text(self):
        return " ".join(self.words)


def sample_report():
    equity = [
        {"timestamp": "2026-01-01", "position": 0, "equity": 1000},
        {"timestamp": "2026-01-02", "position": 9007199254740993, "equity": 1100},
    ]
    baseline_result = {"engine": "backtesting", "engine_version": "0.6.6", "initial_cash": 1000,
        "effective_settings": {"commission": 0, "cash": 1000}, "scenario": {"commission_bps": 0, "spread_bps": 0, "delay_bars": 0},
        "timing": {"execution": "next open", "protective_orders": "native timing"}, "warnings": [],
        "equity": equity, "trades": [], "open_trades": [], "pending_orders": []}
    stressed_result = copy.deepcopy(baseline_result)
    stressed_result["equity"][1].update(position=9007199254740992, equity=990)
    stress = {"commission_bps": 25, "spread_bps": 10, "delay_bars": 1}
    stressed_result["scenario"] = stress
    base_metrics = {"return_pct": 10, "net_profit": 100, "final_equity": 1100, "max_drawdown_pct": 0, "closed_trades": 0}
    stress_metrics = {"return_pct": -1, "net_profit": -10, "final_equity": 990, "max_drawdown_pct": 1, "closed_trades": 0}
    return {"schema_version": "backtest-witness.failure-lab.v1", "report_id": "test-report", "created_at": "2026-01-01",
        "status": "FAILURE_FOUND", "headline": "A requirement failed under stress.", "reason": "Verified in repeated runs.",
        "strategy_ref": "example:Strategy", "runner_spec": {"engine": "backtesting", "engine_settings": {"cash": 1000}},
        "dataset": {"symbol": "SYNTH", "row_count": 2, "start": "2026-01-01", "end": "2026-01-02", "input_hash": "abc"},
        "requirements": {"min_return_pct": 0, "max_drawdown_pct": None, "max_return_drop_pct": None, "min_closed_trades": 0},
        "settings": {"seed": 7, "max_calls": 96}, "coverage": {"runs": 8, "completed": 1, "total": 1, "complete": True, "notes": []},
        "baseline": {"status": "PASS", "result": baseline_result, "metrics": base_metrics, "violations": [], "reason": None},
        "scenarios": [{"name": "Combined", "scenario": stress, "status": "FAIL", "result": stressed_result,
            "metrics": stress_metrics, "violations": ["Return -1% is below minimum 0%."], "reason": None}],
        "failure": {"scenario": stress, "result": stressed_result, "metrics": stress_metrics,
            "violations": ["Return -1% is below minimum 0%."],
            "differences": [{"timestamp": "2026-01-02", "before_position": 9007199254740993,
                "after_position": 9007199254740992, "before_equity": 1100, "after_equity": 990}],
            "reduction": {"complete": True, "runs": 2, "scope": "Lower declared levels tested; full history retained."}},
        "artifacts": {"json": "report.json", "fixture": "failure-fixture.json", "test": "test_failure_resilience.py", "receipt": "failure-receipt.json"},
        "provenance": {"input": "Synthetic prices", "source": "Pinned MIT source"}, "config": {"size": 1}}


def render(report):
    # Delayed import makes the initial red run expose the missing implementation.
    from tradeoff.report.failure_renderer import render_failure_report
    return render_failure_report(report)


def browser_data(markup):
    return json.loads(re.search(r'<script id="failure-data" type="application/json">(.*?)</script>', markup, re.S).group(1))


def test_initial_view_contains_native_pair_and_policy_without_javascript():
    page = Page(render(sample_report()))
    assert "Native engine equity" in page.text
    assert "Combined" in page.text
    assert "10.00%" in page.text and "-1.00%" in page.text
    assert "Minimum return" in page.text and "Disabled" in page.text
    assert "9007199254740993" in page.text
    assert "Earliest changed position" in page.text
    assert "Lower declared levels tested; full history retained." in page.text
    assert any(tag == "input" and attrs.get("type") == "range" and attrs.get("aria-label") for tag, attrs in page.tags)
    assert any(tag == "select" and attrs.get("id") == "scenario-select" for tag, attrs in page.tags)
    assert any(tag == "table" and attrs.get("id") == "equity-table" for tag, attrs in page.tags)


def test_keyboard_skip_link_targets_focusable_main_content():
    page = Page(render(sample_report()))
    links = [attrs for tag, attrs in page.tags if tag == "a"]
    assert links[0].get("class") == "skip-link"
    assert links[0].get("href") == "#main"
    assert any(tag == "main" and attrs.get("id") == "main" and attrs.get("tabindex") == "-1"
               for tag, attrs in page.tags)


def test_embedded_json_escapes_script_and_preserves_exact_position_labels():
    report = sample_report()
    hostile = '</script><img src=x onerror="alert(1)">@@CSS@@&\u2028'
    report["headline"] = hostile
    report["provenance"]["source"] = hostile
    markup = render(report)
    assert hostile not in markup
    assert '<img src=x' not in markup
    assert '&lt;/script&gt;' in markup
    data = browser_data(markup)
    assert data["headline"] == hostile
    assert data["display_positions"]["baseline"] == ["0", "9007199254740993"]
    assert data["display_positions"]["scenarios"][0] == ["0", "9007199254740992"]
    assert data["display_positions"]["differences"][0]["before_position"] == "9007199254740993"


@pytest.mark.parametrize("status", ["BASELINE_FAILED", "NO_FAILURE_OBSERVED", "INCONCLUSIVE"])
def test_null_results_and_missing_failure_are_explicit(status):
    report = sample_report()
    report.update(status=status, failure=None)
    report["baseline"].update(status="UNAVAILABLE", result=None, metrics=None, reason="Missing complete equity")
    report["scenarios"] = [
        {"name": "Unsupported", "scenario": {"delay_bars": 1}, "status": "UNAVAILABLE", "result": None, "metrics": None, "violations": [], "reason": "Stop orders unsupported"},
        {"name": "Skipped", "scenario": {"commission_bps": 5}, "status": "NOT_RUN", "result": None, "metrics": None, "violations": [], "reason": "Budget exhausted"},
    ]
    page = Page(render(report))
    assert "UNAVAILABLE" in page.text and "NOT_RUN" in page.text
    assert "Stop orders unsupported" in page.text and "Budget exhausted" in page.text
    assert "No verified stress failure" in page.text
    assert "Native engine equity unavailable" in page.text
    assert "Missing complete equity" in page.text
    assert not any(tag == "a" and attrs.get("href") == "failure-fixture.json" for tag, attrs in page.tags)


def test_offline_artifacts_and_write_preserve_the_report(tmp_path):
    from tradeoff.report.failure_renderer import write_failure_report
    report = sample_report()
    original = copy.deepcopy(report)
    path = write_failure_report(report, tmp_path)
    assert path == tmp_path / "index.html"
    assert json.loads((tmp_path / "report.json").read_text()) == original
    assert report == original
    page = Page(path.read_text())
    assert {attrs["href"] for tag, attrs in page.tags if tag == "a" and "download" in attrs} >= {
        "report.json", "failure-fixture.json", "test_failure_resilience.py", "failure-receipt.json"}
    assert not any(tag in {"script", "link", "iframe", "img"} and ("src" in attrs or "href" in attrs) for tag, attrs in page.tags)
    assert "fetch(" not in path.read_text() and "@import" not in path.read_text()
    assert "python -m pytest test_failure_resilience.py" in page.text
    assert "Protective" in page.text and "extra bars" in page.text


@pytest.mark.parametrize("bad_path", ["../secret", "https://example.com", "/tmp/a", "evil\" onclick=\"x", "a//b"])
def test_unsafe_download_paths_are_refused(bad_path):
    report = sample_report()
    report["artifacts"]["fixture"] = bad_path
    with pytest.raises(ValueError, match="artifact"):
        render(report)


def test_nonfinite_payload_and_unknown_status_are_refused_before_writing(tmp_path):
    from tradeoff.report.failure_renderer import write_failure_report
    report = sample_report()
    report["config"]["bad"] = float("nan")
    with pytest.raises(ValueError):
        write_failure_report(report, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
    report = sample_report()
    report["status"] = "CERTIFIED"
    with pytest.raises(ValueError, match="status"):
        render(report)


def test_failure_gallery_links_reports_with_execution_statuses(tmp_path):
    from tradeoff.report.failure_renderer import write_failure_gallery
    path = write_failure_gallery(tmp_path, [{"name": '<script>Strategy</script>', "status": "BASELINE_FAILED",
        "path": "case/index.html", "description": "Synthetic execution case"}])
    markup = path.read_text()
    page = Page(markup)
    assert any(tag == "a" and attrs.get("href") == "case/index.html" for tag, attrs in page.tags)
    assert "Baseline failed" in page.text and "Synthetic execution case" in page.text
    assert '<script>Strategy</script>' not in markup
    assert not any(tag in {"script", "link"} and ("src" in attrs or "href" in attrs) for tag, attrs in page.tags)
    with pytest.raises(ValueError, match="artifact"):
        write_failure_gallery(tmp_path, [{"name": "X", "status": "FAILURE_FOUND", "path": "../secret"}])


def test_selected_native_ledger_transport_preserves_large_trade_sizes():
    report = sample_report()
    report["failure"]["result"] = copy.deepcopy(report["failure"]["result"])
    report["scenarios"][0]["result"]["trades"] = [{"size": 9007199254740993, "net_pnl": -10}]
    report["failure"]["result"]["trades"] = [{"size": -9007199254740993, "net_pnl": -10}]
    data = browser_data(render(report))
    assert json.loads(data["display_ledgers"]["scenarios"][0]["trades"])[0]["size"] == 9007199254740993
    assert json.loads(data["display_ledgers"]["failure"]["trades"])[0]["size"] == -9007199254740993


def test_empty_suite_does_not_invent_selected_stress_parameters():
    report = sample_report()
    report.update(status="NO_FAILURE_OBSERVED", failure=None, scenarios=[])
    markup = render(report)
    selected = re.search(r'<p id="selected-stress"[^>]*>(.*?)</p>', markup).group(1)
    assert selected == "No stress parameters supplied"
    page = Page(markup)
    assert "No scenario was declared." in page.text


@pytest.mark.parametrize('before,after,label', [(1, 1.0, '1'), (0, -0.0, '0'), (100000000000000000000, 1e20, '100000000000000000000')])
def test_equal_numeric_positions_use_exact_canonical_labels_without_false_divergence(before, after, label):
    report = sample_report()
    for point in report['baseline']['result']['equity']:
        point['position'] = before
    for point in report['scenarios'][0]['result']['equity']:
        point['position'] = after
    report['failure']['differences'][0].update(before_position=before, after_position=after)
    markup = render(report)
    assert 'No changed position observed' in Page(markup).text
    data = browser_data(markup)
    assert data['display_positions']['baseline'] == [label, label]
    assert data['display_positions']['scenarios'][0] == [label, label]
    assert data['display_positions']['failure'] == [label, label]
    assert data['display_positions']['differences'][0]['before_position'] == label
    assert data['display_positions']['differences'][0]['after_position'] == label
    assert re.search(r'<strong id="bar-base-position">(.*?)</strong>', markup).group(1) == label
    assert re.search(r'<strong id="bar-stress-position">(.*?)</strong>', markup).group(1) == label


def test_native_six_digit_axis_labels_have_left_padding_and_aligned_cursor():
    import xml.etree.ElementTree as ET
    report = sample_report()
    for entry in (report['baseline'], report['scenarios'][0]):
        for point in entry['result']['equity']:
            point['equity'] *= 100
    markup = render(report)
    svg = ET.fromstring(re.search(r'<svg id="equity-chart".*?</svg>', markup, re.S).group(0))
    labels = svg.findall('text')
    assert any(float(item.text.replace(',', '')) >= 100000 for item in labels)
    # The supplied 10px monospace label font uses about 6px per character.
    assert all(float(item.attrib['x']) - len(item.text) * 6 >= 8 for item in labels)
    first_grid = svg.find("line[@class='grid']")
    cursor = svg.find("line[@id='chart-cursor']")
    assert cursor.attrib['x1'] == first_grid.attrib['x1']
    assert cursor.attrib['x2'] == first_grid.attrib['x1']
    for curve in svg.findall('polyline'):
        assert float(curve.attrib['points'].split(',')[0]) == float(first_grid.attrib['x1'])
