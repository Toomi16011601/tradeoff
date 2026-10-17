"""Audit target decisions for reproducible dependencies on unavailable data."""

from copy import deepcopy
from datetime import datetime, timezone
from .mutations import MUTATION_NAMES, mutate_future
from .privacy import callback_error, reject_sensitive_data
from .validation import canonical_hash, prefix_trace, validate_config, validate_rows, validate_trace


class _RunFailure(Exception):
    pass


def _integer(value, label, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _runner_metadata(run, name):
    value = getattr(run, name, None)
    if value is None:
        return None
    try:
        return validate_config(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite JSON object: {exc}") from exc


def audit(run, rows, config=None, *, seed=7, min_history=3, max_probes=12,
          max_calls=96, strategy_ref=None, trace_kind=None):
    """Inspect bounded OHLC/volume interventions and return an evidence receipt.

    Only target decisions at or before a fixed cutoff are compared. A scoped
    negative result is never a certificate of causality or profitability.
    Runner metadata is copied into the report for API exports. Trace semantics
    default to the runner's metadata, then target_units; explicit overrides win.
    """
    tape = validate_rows(rows)
    configuration = validate_config(config)
    if not callable(run):
        raise ValueError("run must be callable")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    _integer(min_history, "min_history", 1)
    _integer(max_probes, "max_probes", 1)
    _integer(max_calls, "max_calls", 1)
    if strategy_ref is not None and not isinstance(strategy_ref, str):
        raise ValueError("strategy_ref must be a string or None")
    if trace_kind is None:
        trace_kind = getattr(run, "trace_kind", None)
        if trace_kind is None:
            trace_kind = "target_units"
    if not isinstance(trace_kind, str) or not trace_kind:
        raise ValueError("trace_kind must be a nonempty string")
    runner_spec = _runner_metadata(run, "runner_spec")
    adapter_info = _runner_metadata(run, "adapter_info")
    reject_sensitive_data({'strategy_ref': strategy_ref, 'trace_kind': trace_kind})
    settings = {"seed": seed, "min_history": min_history, "max_probes": max_probes, "max_calls": max_calls}
    eligible = list(range(min_history - 1, len(tape) - 1))
    coverage = {"runs": 0, "probes": 0, "cutoffs_probed": 0, "eligible_cutoffs": len(eligible), "complete": False, "reduction_runs": 0, "notes": [
        "Coverage is limited to two deterministic OHLC/volume scaling interventions on sampled cutoffs.",
        "Target decisions are compared; diagnostic features and reasons do not determine equivalence.",
    ]}
    known = {"timestamp", "available_at", "symbol", "open", "high", "low", "close", "volume"}
    extras = sorted({field for row in tape for field in row if field not in known})
    if extras:
        coverage["notes"].append("Extra fields are preserved but outside mutation coverage: " + ", ".join(extras))
    report = {
        "schema_version": "edgelab.audit.v1",
        "report_id": canonical_hash({"rows": tape, "config": configuration, "settings": settings,
                                     "strategy_ref": strategy_ref, "runner_spec": runner_spec,
                                     "trace_kind": trace_kind})[:16],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "INCONCLUSIVE", "headline": "Audit could not establish a comparable result", "reason": None,
        "strategy_ref": strategy_ref, "trace_kind": trace_kind,
        "dataset": {"symbol": tape[0]["symbol"], "row_count": len(tape), "start": tape[0]["timestamp"], "end": tape[-1]["timestamp"], "input_hash": canonical_hash(tape)},
        "settings": settings, "config": configuration, "coverage": coverage,
        "baseline": {"trace": []}, "witness": None, "economics": None, "artifacts": {"json": "report.json"},
    }
    if runner_spec is not None:
        report["runner_spec"] = runner_spec
    if adapter_info is not None:
        report["adapter_info"] = adapter_info

    def invoke(candidate, *, reduction=False):
        if coverage["runs"] >= max_calls:
            raise _RunFailure("Callback-call budget exhausted before a comparable result was verified")
        coverage["runs"] += 1
        if reduction:
            coverage["reduction_runs"] += 1
        try:
            validated_candidate = validate_rows(candidate)
        except Exception as exc:
            raise _RunFailure(f"Callback or trace validation failed: {type(exc).__name__}: {exc}") from exc
        try:
            output = run(deepcopy(validated_candidate), deepcopy(configuration), seed)
        except Exception as exc:
            raise _RunFailure(callback_error(exc)) from exc
        try:
            return validate_trace(output, validated_candidate)
        except Exception as exc:
            raise _RunFailure('Callback trace validation failed; invalid or sensitive observations omitted') from exc

    def paired(candidate, *, reduction=False):
        first = invoke(candidate, reduction=reduction)
        second = invoke(candidate, reduction=reduction)
        if prefix_trace(first) != prefix_trace(second):
            raise _RunFailure("Unstable target decisions on identical tape, configuration and seed")
        return first

    def inconclusive(reason):
        report["status"] = "INCONCLUSIVE"
        report["headline"] = "Audit is inconclusive"
        report["reason"] = reason
        coverage["complete"] = False
        return report

    try:
        baseline = paired(tape)
        report["baseline"]["trace"] = baseline
        if not eligible:
            return inconclusive("Insufficient row history for an eligible cutoff with future data")
        count = min(max_probes, len(eligible))
        cutoffs = [eligible[0]] if count == 1 else [eligible[round(index * (len(eligible) - 1) / (count - 1))] for index in range(count)]
        coverage["notes"].append(f"Sampled {count} of {len(eligible)} eligible cutoffs; two interventions per cutoff.")
        for cutoff_index in cutoffs:
            cutoff = tape[cutoff_index]["timestamp"]
            before_prefix = prefix_trace(baseline, cutoff)
            for mutation_name in MUTATION_NAMES:
                # A witness needs two more original and two intervention runs.
                if max_calls - coverage["runs"] < 6:
                    return inconclusive("Callback-call budget exhausted; inspected interventions did not establish a dependency")
                if mutation_name == MUTATION_NAMES[0]:
                    coverage["cutoffs_probed"] += 1
                mutated, changes = mutate_future(tape, cutoff, mutation_name)
                if not changes:
                    coverage["notes"].append(f"{mutation_name} at {cutoff} produced no representable edits and was skipped.")
                    continue
                mutated_trace = paired(mutated)
                coverage["probes"] += 1
                if prefix_trace(mutated_trace, cutoff) == before_prefix:
                    continue
                original_change_count = len(changes)
                selected = [record["index"] for record in changes]
                reduction_complete = True
                for removed_index in list(selected):
                    # Removing the sole changed row restores the known original
                    # tape exactly; final original verification already covers it.
                    if len(selected) == 1:
                        break
                    if max_calls - coverage["runs"] < 6:
                        reduction_complete = False
                        coverage["notes"].append("Reduction stopped at the callback-call budget; final witness verification was reserved.")
                        break
                    candidate_indices = [index for index in selected if index != removed_index]
                    candidate, candidate_changes = mutate_future(tape, cutoff, mutation_name, candidate_indices)
                    candidate_trace = paired(candidate, reduction=True)
                    if prefix_trace(candidate_trace, cutoff) != before_prefix:
                        selected, mutated, changes, mutated_trace = candidate_indices, candidate, candidate_changes, candidate_trace
                # Recheck both full tapes after reduction to catch hidden state drift.
                verified_original = paired(tape)
                verified_mutated = paired(mutated)
                if prefix_trace(verified_original) != prefix_trace(baseline):
                    return inconclusive("Unstable original target decisions changed during final witness verification")
                after_prefix = prefix_trace(verified_mutated, cutoff)
                if after_prefix == before_prefix:
                    return inconclusive("Observed dependency did not reproduce during final paired verification")
                decision_index = next(index for index, (before, after) in enumerate(zip(before_prefix, after_prefix)) if before != after)
                report["witness"] = {
                    "cutoff": cutoff, "decision_timestamp": baseline[decision_index]["timestamp"], "decision_index": decision_index,
                    "before_decision": deepcopy(baseline[decision_index]), "after_decision": deepcopy(verified_mutated[decision_index]),
                    "mutation_name": mutation_name, "changed_rows": changes,
                    "original_rows": deepcopy(tape), "mutated_rows": mutated, "mutated_trace": verified_mutated,
                    "reduced": len(changes) < original_change_count, "reduction_complete": reduction_complete,
                }
                report["status"] = "FOUND"
                report["headline"] = "A future-data dependency was reproduced"
                report["reason"] = "A target at or before the fixed cutoff changed when only unavailable bars were intervened on."
                coverage["notes"].append("Search stopped on the first verified witness. Greedy reduction does not establish a globally smallest fixture.")
                return report
        if coverage["probes"] == 0:
            return inconclusive("No representable future-only interventions were completed")
        coverage["complete"] = True
        report["status"] = "NO_DEPENDENCY_OBSERVED"
        report["headline"] = "No dependency observed in inspected interventions"
        report["reason"] = "Targets at or before the inspected cutoffs were unchanged under the tested OHLC/volume interventions; untested dependencies remain possible."
        return report
    except _RunFailure as exc:
        return inconclusive(str(exc))
