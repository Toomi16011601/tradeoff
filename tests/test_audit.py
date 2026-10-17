import copy
import pytest
from test_validation import tape


def clean(rows, config, seed):
    return [{"timestamp": row["timestamp"], "target": int(row["close"] > row["open"])} for row in rows]


def future_last(rows, config, seed):
    return [{"timestamp": row["timestamp"], "target": int(rows[-1]["close"] > 20)} for row in rows]


def test_future_data_dependency_is_reduced_and_preserves_full_history():
    from tradeoff.audit import audit
    rows = tape()
    result = audit(future_last, rows, {"nested": [1]}, min_history=1)
    assert result["status"] == "FOUND"
    witness = result["witness"]
    assert witness["before_decision"]["target"] == 0
    assert witness["after_decision"]["target"] == 1
    assert len(witness["original_rows"]) == len(rows)
    assert len(witness["mutated_rows"]) == len(rows)
    assert [record["index"] for record in witness["changed_rows"]] == [3]
    assert witness["cutoff"] == rows[0]["timestamp"]
    assert witness["reduced"] and witness["reduction_complete"]
    assert result["config"] == {"nested": [1]}


def test_causal_control_has_only_scoped_no_dependency_verdict():
    from tradeoff.audit import audit
    result = audit(clean, tape(), min_history=1)
    assert result["status"] == "NO_DEPENDENCY_OBSERVED"
    assert result["witness"] is None
    assert result["coverage"]["complete"]
    assert result["coverage"]["eligible_cutoffs"] == 3
    assert result["coverage"]["cutoffs_probed"] == 3
    assert result["coverage"]["probes"] == 6
    assert result["coverage"]["runs"] == 14


def test_cutoff_limit_and_intervention_counts_use_distinct_units():
    from tradeoff.audit import audit
    result = audit(clean, tape(), min_history=1, max_probes=1)
    assert result["coverage"]["cutoffs_probed"] == 1
    assert result["coverage"]["eligible_cutoffs"] == 3
    assert result["coverage"]["probes"] == 2
    assert result["status"] == "NO_DEPENDENCY_OBSERVED"


def test_mutation_can_change_delayed_prior_timestamp_row():
    from tradeoff.audit import audit
    rows = tape()
    rows[0]["available_at"] = rows[-1]["timestamp"]
    def delayed_leak(rows, config, seed):
        return [{"timestamp": row["timestamp"], "target": int(rows[0]["close"] > 20)} for row in rows]
    result = audit(delayed_leak, rows, min_history=1)
    assert result["status"] == "FOUND"
    assert [record["index"] for record in result["witness"]["changed_rows"]] == [0]
    assert result["witness"]["changed_rows"][0]["available_at"] > result["witness"]["cutoff"]


def test_only_targets_determine_stability_and_equivalence():
    from tradeoff.audit import audit
    count = 0
    def diagnostics(rows, config, seed):
        nonlocal count
        count += 1
        return [{"timestamp": row["timestamp"], "target": 0, "features": {"run": count}, "reason": str(count)} for row in rows]
    assert audit(diagnostics, tape(), min_history=1)["status"] == "NO_DEPENDENCY_OBSERVED"


def test_callback_cannot_mutate_original_tape_config_or_later_runs():
    from tradeoff.audit import audit
    rows, config = tape(), {"nested": [1]}
    before = copy.deepcopy((rows, config))
    def mutating(rows, config, seed):
        rows[0]["extra"]["nested"].append(9)
        config["nested"].append(9)
        assert config["nested"] == [1, 9]
        return clean(rows, config, seed)
    assert audit(mutating, rows, config, min_history=1)["status"] == "NO_DEPENDENCY_OBSERVED"
    assert (rows, config) == before


def test_unstable_callback_is_inconclusive():
    from tradeoff.audit import audit
    count = 0
    def unstable(rows, config, seed):
        nonlocal count
        count += 1
        return [{"timestamp": row["timestamp"], "target": count % 2} for row in rows]
    result = audit(unstable, tape(), min_history=1)
    assert result["status"] == "INCONCLUSIVE"
    assert "unstable" in result["reason"].lower()
    assert result["coverage"]["runs"] == 2


@pytest.mark.parametrize("kind", ["failure", "short", "bad_target"])
def test_callback_failures_and_incomplete_traces_are_inconclusive(kind):
    from tradeoff.audit import audit
    def broken(rows, config, seed):
        if kind == "failure":
            raise RuntimeError("blocked strategy")
        trace = clean(rows, config, seed)
        if kind == "short":
            return trace[:-1]
        trace[0]["target"] = True
        return trace
    result = audit(broken, tape(), min_history=1)
    assert result["status"] == "INCONCLUSIVE"
    assert result["reason"]


def test_bounded_search_does_not_certify_a_budget_exhausted_result():
    from tradeoff.audit import audit
    calls = 0
    def counted(rows, config, seed):
        nonlocal calls
        calls += 1
        return clean(rows, config, seed)
    result = audit(counted, tape(), min_history=1, max_calls=9)
    assert calls <= 9
    assert result["status"] == "INCONCLUSIVE"
    assert not result["coverage"]["complete"]
    assert "budget" in result["reason"].lower()


def test_budget_reserves_final_witness_verification():
    from tradeoff.audit import audit
    result = audit(future_last, tape(), min_history=1, max_calls=8)
    assert result["status"] == "FOUND"
    assert result["coverage"]["runs"] == 8
    assert not result["witness"]["reduction_complete"]


def test_invalid_input_fails_before_strategy_is_called():
    from tradeoff.audit import audit
    def forbidden(*args):
        pytest.fail("invalid rows reached callback")
    with pytest.raises(ValueError, match="rows"):
        audit(forbidden, [])


def test_final_verification_detects_original_state_drift():
    from tradeoff.audit import audit
    calls = 0
    def drift(rows, config, seed):
        nonlocal calls
        calls += 1
        value = int(rows[-1]["close"] > 20) if calls <= 4 else 1
        return [{"timestamp": row["timestamp"], "target": value} for row in rows]
    result = audit(drift, tape(), min_history=1, max_calls=8)
    assert result["status"] == "INCONCLUSIVE"
    assert "unstable" in result["reason"].lower()
    assert result["witness"] is None


def test_mutation_keeps_available_bars_and_json_extras_unchanged():
    from tradeoff.audit import audit
    from tradeoff.validation import parse_timestamp
    rows = tape()
    result = audit(future_last, rows, min_history=1)
    witness = result["witness"]
    for before, after in zip(witness["original_rows"], witness["mutated_rows"]):
        if parse_timestamp(before["available_at"]) <= parse_timestamp(witness["cutoff"]):
            assert before == after
        assert before["timestamp"] == after["timestamp"]
        assert before["available_at"] == after["available_at"]
        assert before["symbol"] == after["symbol"]
        assert before["extra"] == after["extra"]
        assert after["low"] <= min(after["open"], after["close"])
        assert after["high"] >= max(after["open"], after["close"])


def test_negative_integer_seed_is_portable_callback_configuration():
    from tradeoff.audit import audit
    def negative_seed(rows, config, seed):
        assert seed == -4
        return clean(rows, config, seed)
    assert audit(negative_seed, tape(), seed=-4, min_history=1)["status"] == "NO_DEPENDENCY_OBSERVED"


@pytest.mark.parametrize("max_calls", range(1, 13))
def test_every_small_budget_is_respected(max_calls):
    from tradeoff.audit import audit
    calls = 0
    def counted(rows, config, seed):
        nonlocal calls
        calls += 1
        return future_last(rows, config, seed)
    result = audit(counted, tape(), max_calls=max_calls, min_history=1)
    assert calls == result["coverage"]["runs"]
    assert calls <= max_calls
    if result["status"] == "FOUND":
        assert calls >= 8
    else:
        assert result["status"] == "INCONCLUSIVE"

def test_extreme_finite_prices_keep_mutations_inside_valid_bar_contract():
    import math
    import sys
    from tradeoff.demos import synthetic_rows
    from tradeoff.mutations import mutate_future
    from tradeoff.validation import validate_rows
    rows = synthetic_rows(4)
    edge = math.nextafter(sys.float_info.max, 0.0)
    for row in rows:
        for key in ("open", "high", "low", "close", "volume"):
            row[key] = edge
    changed, _ = mutate_future(rows, rows[0]["timestamp"], "scale_up")
    assert all(math.isfinite(row[key]) for row in changed
               for key in ("open", "high", "low", "close", "volume"))
    assert validate_rows(changed) == changed


def test_audit_copies_runner_metadata_and_infers_observed_trace_kind():
    from tradeoff.audit import audit

    def run(rows, config, seed):
        return clean(rows, config, seed)

    run.trace_kind = "observed_position"
    run.runner_spec = {"engine": "backtesting", "engine_settings": {"cash": 5000, "margin": 0.5}}
    run.adapter_info = {"engine": "backtesting", "notes": ["observed after processing"]}
    report = audit(run, tape(), min_history=1)
    assert report["trace_kind"] == "observed_position"
    assert report["runner_spec"] == run.runner_spec
    assert report["adapter_info"] == run.adapter_info
    run.runner_spec["engine_settings"]["cash"] = 9000
    run.adapter_info["notes"].append("changed later")
    assert report["runner_spec"]["engine_settings"]["cash"] == 5000
    assert report["adapter_info"]["notes"] == ["observed after processing"]


def test_explicit_trace_kind_overrides_metadata_and_raw_callbacks_default_to_targets():
    from tradeoff.audit import audit

    def run(rows, config, seed):
        return clean(rows, config, seed)

    run.trace_kind = "observed_position"
    assert audit(run, tape(), min_history=1, trace_kind="target_units")["trace_kind"] == "target_units"
    assert audit(clean, tape(), min_history=1)["trace_kind"] == "target_units"


def test_report_identity_binds_effective_runner_settings_and_trace_semantics():
    from tradeoff.audit import audit

    def run(rows, config, seed):
        return clean(rows, config, seed)

    run.trace_kind = "observed_position"
    run.runner_spec = {"engine": "backtesting", "engine_settings": {"cash": 5000, "margin": 0.5}}
    first = audit(run, tape(), min_history=1, strategy_ref="strategy:Example")
    same = audit(run, tape(), min_history=1, strategy_ref="strategy:Example")
    overridden = audit(run, tape(), min_history=1, strategy_ref="strategy:Example", trace_kind="target_units")
    run.runner_spec["engine_settings"]["cash"] = 9000
    changed = audit(run, tape(), min_history=1, strategy_ref="strategy:Example")
    assert first["report_id"] == same["report_id"]
    assert len({first["report_id"], overridden["report_id"], changed["report_id"]}) == 3


@pytest.mark.parametrize("attribute", ["runner_spec", "adapter_info"])
def test_invalid_runner_metadata_fails_before_callback_execution(attribute):
    from tradeoff.audit import audit

    def forbidden(*args):
        pytest.fail("invalid metadata reached callback")

    setattr(forbidden, attribute, {"invalid": float("nan")})
    with pytest.raises(ValueError, match=attribute):
        audit(forbidden, tape())
