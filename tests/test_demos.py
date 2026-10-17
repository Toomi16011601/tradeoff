def test_synthetic_demo_controls_distinguish_leakage_causality_and_instability():
    from tradeoff.audit import audit
    from tradeoff.demos import synthetic_rows, leaky_run, causal_run, make_unstable_run
    rows = synthetic_rows()
    assert audit(leaky_run, rows)["status"] == "FOUND"
    assert audit(causal_run, rows)["status"] == "NO_DEPENDENCY_OBSERVED"
    assert audit(make_unstable_run(), rows)["status"] == "INCONCLUSIVE"
    assert synthetic_rows() == rows


def test_default_demo_finishes_reduction_with_a_single_changed_bar():
    from tradeoff.audit import audit
    from tradeoff.demos import synthetic_rows, leaky_run
    report = audit(leaky_run, synthetic_rows())
    assert len(report["witness"]["changed_rows"]) == 1
    assert report["witness"]["reduction_complete"]
    assert report["coverage"]["runs"] <= 96
