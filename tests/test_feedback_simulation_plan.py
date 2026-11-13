"""Public plan registration keeps simulation assumptions explicit."""
from copy import deepcopy

import pytest

from tradeoff.feedback.api import FeedbackApp
from tradeoff.feedback.contracts import FeedbackError
from tradeoff.feedback.store import FeedbackStore


def simulated_plan():
    return {
        "plan_id":"sim-plan", "baseline_version":"baseline", "candidate_version":"candidate",
        "window_start":"2020-01-02T00:00:00+00:00", "window_end":"2020-01-04T00:00:00+00:00",
        "metric":"simulated_account_return_bps", "horizon_policy":"decision_at_declared_end",
        "reference_policy":"exact_reference", "cost_policy":"complete_modeled",
        "match_policy":"same_market_calendar", "minimum_pairs":1,
        "simulation": {
            "baseline_source_alias":"sim-baseline", "candidate_source_alias":"sim-candidate",
            "initial_cash":"10000", "currency":"USD", "symbol":"SYNTH", "asset_class":"us_equity",
            "valuation_source":"public-fixture", "valuation_feed":"fixture-feed", "price_kind":"close",
            "initial_at":"2020-01-02T16:00:00+00:00", "terminal_at":"2020-01-03T16:00:00+00:00",
            "expected_decisions":1, "cost_model_id":"declared-fees-v1", "execution_policy_id":"next-open-v1",
            "timestamp_policy":"declared_historical_ordering", "acknowledge_assumptions":True,
        },
    }


def test_public_api_registers_and_routes_a_simulation_plan(tmp_path):
    with FeedbackStore(tmp_path,create=True,environment="simulated"):
        pass
    app=FeedbackApp(tmp_path)
    plan=simulated_plan()
    first=app.register_comparison({"event_id":"plan-1","plan":plan})
    assert first==app.register_comparison({"event_id":"plan-1","plan":plan})
    result=app.compare_versions({"plan_id":"sim-plan","as_of":"2021-01-01T00:00:00+00:00"})
    assert result["schema_version"]=="tradeoff.simulated-account-comparison.v1"
    assert result["status"]=="INSUFFICIENT_EVIDENCE"
    assert result["accounts"]=={}
    assert all(value is None for value in result["metrics"].values())


@pytest.mark.parametrize("changes",[
    {"initial_cash":"0"}, {"initial_cash":"-1"}, {"acknowledge_assumptions":False},
    {"candidate_source_alias":"sim-baseline"}, {"currency":"EUR"}, {"asset_class":"option"},
    {"expected_decisions":0}, {"timestamp_policy":"live"},
    {"terminal_at":"2020-01-02T15:00:00+00:00"},
    {"initial_at":"2019-01-01T00:00:00+00:00"},
])
def test_incomplete_or_inconsistent_simulation_declarations_are_rejected(tmp_path,changes):
    with FeedbackStore(tmp_path,create=True,environment="simulated"):
        pass
    plan=simulated_plan()
    plan["simulation"].update(changes)
    with pytest.raises(FeedbackError):
        FeedbackApp(tmp_path).register_comparison({"event_id":"bad-plan","plan":plan})


@pytest.mark.parametrize("field,value",[
    ("metric","episode_net_return_bps"),("cost_policy","complete_observed"),("match_policy","exact_opportunity"),
])
def test_simulated_and_observed_contracts_cannot_be_mixed(tmp_path,field,value):
    with FeedbackStore(tmp_path,create=True,environment="simulated"):
        pass
    plan=simulated_plan()
    plan[field]=value
    with pytest.raises(FeedbackError):
        FeedbackApp(tmp_path).register_comparison({"event_id":"bad-plan","plan":plan})


def test_modelled_plan_needs_explicit_metadata_and_simulated_workspace(tmp_path):
    with FeedbackStore(tmp_path,create=True,environment="paper"):
        pass
    plan=simulated_plan()
    with pytest.raises(FeedbackError) as error:
        FeedbackApp(tmp_path).register_comparison({"event_id":"paper-plan","plan":plan})
    assert error.value.code=="SIMULATION_WORKSPACE_REQUIRED"
    del plan["simulation"]
    with pytest.raises(FeedbackError):
        FeedbackApp(tmp_path).register_comparison({"event_id":"missing-metadata","plan":plan})
