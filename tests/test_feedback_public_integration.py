"""Public engine on historical data; public LLM-agent contract fixture is separate."""
from datetime import datetime, timedelta
from decimal import Decimal
import importlib.util
import os

import pytest

from feedback_helpers import decision, fixed_clock


def test_riskkit_native_closed_trade_gross_on_real_historical_data(tmp_path):
    pytest.importorskip("backtesting")
    from tradeoff.cases.riskkit import original_execution
    from tradeoff.historical_demo import historical_rows
    from examples.decision_feedback.agent import import_native_closed_trades
    from tradeoff.feedback.api import FeedbackApp
    rows = historical_rows()
    native = original_execution(rows, {}, 7, {"commission_bps": 0, "spread_bps": 0, "delay_bars": 0})
    result = import_native_closed_trades(tmp_path, rows=rows, native=native)
    report = FeedbackApp(tmp_path).evaluate_decisions({"as_of": rows[-1]["timestamp"]})
    episodes = report["evaluation"]["episodes"]
    assert len(episodes) == len(native["trades"]) == 32
    for episode in episodes:
        trade = native["trades"][int(episode["episode_id"].split("-")[-1])]
        expected = (Decimal(str(trade["exit_price"])) - Decimal(str(trade["entry_price"]))) * Decimal(str(trade["size"]))
        assert Decimal(episode["gross_cashflow"]) == expected
        assert abs(Decimal(str(trade["pnl"])) + Decimal(str(trade["commission"])) - expected) < Decimal("0.000001")
        assert episode["observed_net"] is None
    assert all(d["capture"]["classification"] == "IMPORTED" for d in report["evaluation"]["decisions"])
    assert result["open_native_trades"] == len(native["open_trades"]) == 1
    assert result["pending_native_orders"] == len(native["pending_orders"]) == 1


def test_tradingagents_rating_hook_uses_explicit_intent_on_real_observation(tmp_path):
    pytest.importorskip("backtesting")
    from tradeoff.historical_demo import historical_rows
    from tradeoff.feedback.store import FeedbackStore
    from tradeoff.feedback.recorder import Recorder
    from examples.decision_feedback.tradingagents_hook import record_tradingagents_decision
    from tradeoff.feedback.contracts import FeedbackError
    row = historical_rows()[100]
    at = datetime.fromisoformat(row["timestamp"])
    payload = decision(symbol="GOOG", decision_at=at.isoformat(), horizon_end=(at+timedelta(days=1)).isoformat())
    payload["reference"].update(price=str(row["close"]), observed_at=at.isoformat(), available_at=at.isoformat(),
        source="backtesting_GOOG_daily", feed="public-daily-ordering-labels", price_kind="close", max_age_seconds=86400)
    with FeedbackStore(tmp_path, create=True, environment="simulated"):
        pass
    recorder = Recorder(tmp_path, clock=lambda: at)
    receipt = record_tradingagents_decision(recorder, decision=payload, rating="Buy", event_id="fixture-ta")
    assert receipt["event_id"] == "fixture-ta"
    with pytest.raises(FeedbackError):
        record_tradingagents_decision(recorder, decision={**payload, "decision_id": "review"}, rating="REVIEW", event_id="review")
    with FeedbackStore(tmp_path) as store:
        saved = store.snapshot()["events"][0]["payload"]
    assert saved["quantity_delta"] == "1.25"
    assert saved["prediction"]["label"] == "Buy"


@pytest.mark.skipif(os.environ.get("TRADEOFF_RUN_TRADINGAGENTS") != "1", reason="NOT_RUN: public LLM-agent runtime/model opt-in required")
def test_actual_public_tradingagents_model_run(tmp_path):
    pytest.importorskip("tradingagents")
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    config = dict(DEFAULT_CONFIG)
    config.update(max_debate_rounds=1, max_risk_discuss_rounds=1, results_dir=str(tmp_path / "agent-results"))
    graph = TradingAgentsGraph(debug=False, config=config)
    state, rating = graph.propagate("GOOG", "2026-01-05")
    assert isinstance(state, dict)
    assert rating in {"Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"}
