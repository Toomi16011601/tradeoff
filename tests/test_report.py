"""Renderer boundary tests: truthful states, portable assets, and hostile data."""
import importlib
import importlib.util
import json
from html.parser import HTMLParser

import pytest


class Document(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.nodes = []
        self.words = []
        self.scripts = []
        self.current_script = None
        self.in_style = False
        self.tables = {}
        self.current_table = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.nodes.append((tag, attrs))
        if tag == "script":
            self.current_script = [attrs, ""]
        if tag == "style":
            self.in_style = True
        if tag == "table":
            self.current_table = attrs.get("id")
            if self.current_table:
                self.tables[self.current_table] = []

    def handle_data(self, data):
        if self.current_script is None and not self.in_style:
            self.words.append(data)
        if self.current_script is not None:
            self.current_script[1] += data
        if self.current_table:
            self.tables[self.current_table].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current_script is not None:
            self.scripts.append(self.current_script)
            self.current_script = None
        if tag == "style":
            self.in_style = False
        if tag == "table":
            self.current_table = None

    @property
    def text(self):
        return " ".join(self.words)


def renderer():
    # Deleting the report implementation must fail this behavior gate explicitly.
    assert importlib.util.find_spec("backtest_witness.report") is not None, "offline report API is missing"
    return importlib.import_module("backtest_witness.report")


def report(status="FOUND"):
    timestamps = [f"2026-01-0{i}T16:00:00+00:00" for i in range(1, 5)]
    rows = [{"timestamp": t, "available_at": t, "symbol": "SYNTH", "open": 10,
             "high": 12, "low": 9, "close": 11, "volume": 100} for t in timestamps]
    trace = [{"timestamp": t, "target": n % 2} for n, t in enumerate(timestamps)]
    altered = [dict(row) for row in rows]
    altered[3].update(open=100, high=120, low=90, close=110, volume=1000)
    paired = [dict(item) for item in trace]
    paired[1]["target"] = 0
    witness = {"cutoff": timestamps[1], "decision_timestamp": timestamps[1],
               "decision_index": 1, "before_decision": trace[1], "after_decision": paired[1],
               "mutation_name": "scale_up", "changed_rows": [{"index": 3,
               "timestamp": timestamps[3], "available_at": timestamps[3],
               "before": rows[3], "after": altered[3]}], "original_rows": rows,
               "mutated_rows": altered, "mutated_trace": paired, "reduced": True,
               "reduction_complete": True}
    ledger = {"initial_cash": 1000, "final_equity": 1002, "net_pnl": 2,
              "total_fees": 1, "realized_pnl": 0, "open_pnl": 2,
              "max_drawdown_pct": 0.2, "equity_curve": [{"timestamp": t, "equity": e}
              for t, e in zip(timestamps, [1000, 1000, 1001, 1002])], "fills": []}
    intervention = {**ledger, "final_equity": 1000, "net_pnl": 0,
                    "equity_curve": [{"timestamp": t, "equity": 1000} for t in timestamps]}
    return {"schema_version": "edgelab.audit.v1", "report_id": "audit-0123456789",
            "created_at": "2026-10-13T05:00:00+00:00", "status": status,
            "headline": "An earlier decision depends on unavailable data",
            "reason": "Repeated paired runs changed the target at the fixed cutoff.",
            "strategy_ref": "backtest_witness.demos:leaky", "trace_kind": "target_units",
            "config": {}, "dataset": {"symbol": "SYNTH", "row_count": 4,
            "start": timestamps[0], "end": timestamps[-1], "input_hash": "a" * 64},
            "settings": {"seed": 7, "min_history": 3, "max_probes": 12, "max_calls": 96},
            "coverage": {"runs": 8, "probes": 1, "eligible_cutoffs": 2, "complete": True,
            "reduction_runs": 2, "notes": ["Extra JSON fields are outside mutation coverage."]},
            "baseline": {"trace": trace}, "witness": witness if status == "FOUND" else None,
            "economics": {"assumptions": {"initial_cash": 1000, "fee_fixed": 1,
            "fee_bps": 0, "spread_bps": 2, "slippage_bps": 2, "fill_lag_bars": 1},
            "original": ledger, "intervention": intervention if status == "FOUND" else None,
            "delta": -2 if status == "FOUND" else None, "sensitivity": [],
            "benchmark": ledger, "explanation": "Both traces use the original price tape."},
            "artifacts": {"json": "report.json", "fixture": "reproducer.json",
            "test": "test_future_invariance.py", "receipt": "receipt.json"}}


def test_found_report_exposes_exact_witness_without_javascript():
    doc = Document(renderer().render_report(report()))
    assert "2026-01-02T16:00:00+00:00" in doc.text
    assert "scale_up" in doc.text
    assert "100" in doc.text
    assert {attrs.get("id") for tag, attrs in doc.nodes if tag == "section"} >= {
        "overview", "evidence", "reproducer", "method"}
    assert any(tag == "table" and attrs.get("id") == "equity-table" for tag, attrs in doc.nodes)
    assert any(tag == "a" and attrs.get("href") == "test_future_invariance.py" for tag, attrs in doc.nodes)


@pytest.mark.parametrize("status", ["NO_DEPENDENCY_OBSERVED", "INCONCLUSIVE"])
def test_nonfinding_states_disclose_reason_without_inventing_witness(status):
    data = report(status)
    data["reason"] = "Callback returned different targets on repeated identical inputs."
    doc = Document(renderer().render_report(data))
    assert data["reason"] in doc.text
    assert "No witness is available" in doc.text
    assert not any(attrs.get("id") == "mutation-table" for _, attrs in doc.nodes)


def test_unpaired_economics_does_not_claim_two_projected_decision_paths():
    doc = Document(renderer().render_report(report("NO_DEPENDENCY_OBSERVED")))
    assert "One tape. Two decision paths." not in doc.text
    assert "Original decisions. Original tape." in doc.text
    assert "No paired ledger" in doc.text


def test_absent_economics_has_no_fabricated_zero_results():
    data = report()
    data["economics"] = None
    doc = Document(renderer().render_report(data))
    assert "Economic projection unavailable" in doc.text
    assert not any(attrs.get("id") == "equity-chart" for _, attrs in doc.nodes)
    assert not any(attrs.get("id") == "equity-table" for _, attrs in doc.nodes)


def test_failed_economic_projection_shows_the_supplied_blocker():
    data = report()
    data["economics"] = None
    data["economics_error"] = "The account cannot represent the fill cash change at this precision."
    doc = Document(renderer().render_report(data))
    assert data["economics_error"] in doc.text


def test_completed_interventions_are_not_reported_as_cutoffs():
    data = report()
    data["coverage"].update(probes=6, cutoffs_probed=3, eligible_cutoffs=12)
    doc = Document(renderer().render_report(data))
    assert "COMPLETED INTERVENTIONS" in doc.text
    assert "3 / 12" in doc.text
    assert "6 / 12" not in doc.text


def test_observed_position_adapter_labels_the_recorded_unit():
    data = report()
    data["trace_kind"] = "observed_position"
    doc = Document(renderer().render_report(data))
    assert "Observed position units" in doc.text
    assert "Target units · long / flat" not in doc.text


def test_unavailable_sensitivity_discloses_reason_and_settings():
    data = report()
    data["economics"]["sensitivity"] = [{"name": "Doubled costs", "status": "UNAVAILABLE",
        "reason": "Doubling the spread exceeded a coherent fill bound.",
        "settings": {"spread_bps": 12000}, "original": None, "intervention": None,
        "delta": None}]
    doc = Document(renderer().render_report(data))
    assert "Doubling the spread exceeded a coherent fill bound." in doc.text
    assert "12000" in doc.text
    assert "UNAVAILABLE" in doc.text


def test_evidence_prefix_uses_actual_instants_across_timezone_offsets():
    data = report()
    earlier = "2026-01-02T16:30:00+01:00"  # 15:30 UTC, before the 16:00 UTC cutoff.
    data["dataset"]["start"] = earlier
    data["baseline"]["trace"][0]["timestamp"] = earlier
    data["witness"]["mutated_trace"][0]["timestamp"] = earlier
    for key in ["original_rows", "mutated_rows"]:
        data["witness"][key][0].update(timestamp=earlier, available_at=earlier)
    for key in ["original", "intervention"]:
        data["economics"][key]["equity_curve"][0]["timestamp"] = earlier
    doc = Document(renderer().render_report(data))
    assert earlier in doc.tables["decision-table"]
    assert "2026-01-03T16:00:00+00:00" not in doc.tables["decision-table"]


def test_embedded_script_terminator_and_html_are_inert():
    data = report()
    hostile = '</script><script>alert("owned")</script><img src=x onerror=alert(1)>'
    data["headline"] = hostile
    data["witness"]["before_decision"]["reason"] = hostile
    markup = renderer().render_report(data)
    doc = Document(markup)
    payload = [value for attrs, value in doc.scripts if attrs.get("id") == "report-data"]
    assert len(payload) == 1
    assert json.loads(payload[0])["headline"] == hostile
    assert not any(tag == "img" for tag, _ in doc.nodes)
    assert not any("onerror" in attrs for _, attrs in doc.nodes)
    assert len(doc.scripts) == 2  # inert payload + offline behavior


@pytest.mark.parametrize("path", ["../secret.json", "/tmp/secret.json", "https://x/a.json",
    "javascript:alert(1)", "//example.com/a", "a/../../secret", "a\\b.json",
    'x\" onclick=\"alert(1)', "a%2f..%2fsecret.json"])
def test_rejects_unsafe_artifact_paths(path):
    data = report()
    data["artifacts"]["fixture"] = path
    with pytest.raises(ValueError, match="artifact"):
        renderer().render_report(data)


def test_write_report_creates_offline_html_and_unmodified_json(tmp_path):
    data = report()
    page = renderer().write_report(data, tmp_path)
    assert page == tmp_path / "index.html"
    assert json.loads((tmp_path / "report.json").read_text()) == data
    doc = Document(page.read_text())
    assert not any(tag in {"script", "link"} and (attrs.get("src") or attrs.get("href"))
                   for tag, attrs in doc.nodes)


def test_gallery_links_each_real_scenario_and_escapes_names(tmp_path):
    page = renderer().write_gallery(tmp_path, [
        {"name": "Leaky <sample>", "status": "FOUND", "path": "leaky/index.html",
         "description": "Full-sample normalization"},
        {"name": "Causal control", "status": "NO_DEPENDENCY_OBSERVED",
         "path": "causal/index.html", "description": "Trailing window"}])
    doc = Document(page.read_text())
    assert "Leaky <sample>" in doc.text
    assert not any(tag == "sample" for tag, _ in doc.nodes)
    assert {attrs.get("href") for tag, attrs in doc.nodes if tag == "a"} >= {
        "leaky/index.html", "causal/index.html"}


def test_gallery_rejects_external_scenario_destinations(tmp_path):
    with pytest.raises(ValueError, match="artifact"):
        renderer().write_gallery(tmp_path, [{"name": "Bad", "status": "FOUND",
            "description": "", "path": "https://example.com"}])


def test_signed_position_witness_and_short_costs_are_legible():
    data = report()
    data["witness"]["before_decision"]["target"] = -31.125
    data["witness"]["after_decision"]["target"] = -29.25
    for ledger in (data["economics"]["original"], data["economics"]["intervention"]):
        ledger["total_borrow_cost"] = 12.5
        ledger["risk_events"] = [{"timestamp": "2026-01-04T16:00:00+00:00", "reason": "nonpositive equity"}]
    doc = Document(renderer().render_report(data))
    assert "-31.125" in doc.text and "-29.25" in doc.text
    assert "long / short / flat" in doc.text
    assert "Borrow costs" in doc.text
    assert "12.50" in doc.text
    assert "nonpositive equity" in doc.text
    assert "long / flat units" not in doc.text


def test_public_case_gallery_distinguishes_strategy_source_from_synthetic_data(tmp_path):
    page = renderer().write_gallery(tmp_path, [{"name": "Pinned strategy", "status": "FOUND",
        "path": "original/index.html", "description": "Original public source on synthetic input"}],
        collection="public")
    doc = Document(page.read_text())
    assert "PUBLIC STRATEGY" in doc.text
    assert "synthetic" in doc.text.lower()
    assert "THE SYNTHETIC DEMO COLLECTION" not in doc.text


def test_html_transports_large_target_display_without_numeric_rounding(tmp_path):
    data = report()
    data["baseline"]["trace"][1]["target"] = 9007199254740992
    data["witness"]["mutated_trace"][1]["target"] = 9007199254740993
    page = renderer().write_report(data, tmp_path)
    doc = Document(page.read_text())
    payload = json.loads(next(value for attrs, value in doc.scripts if attrs.get("id") == "report-data"))
    assert payload["display_targets"]["original"][1] == "9007199254740992"
    assert payload["display_targets"]["intervention"][1] == "9007199254740993"
    # Machine-readable report quantities keep their numeric schema.
    saved = json.loads((tmp_path / "report.json").read_text())
    assert saved == data
