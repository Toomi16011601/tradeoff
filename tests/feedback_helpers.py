"""Independent synthetic feedback evidence; no broker or user data."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
START = "2026-01-05T14:30:00+00:00"
END = AFTER_HORIZON = "2026-01-05T16:00:00+00:00"


def fixed_clock():
    return datetime.fromisoformat("2026-01-05T14:30:01+00:00")


def after_horizon_clock():
    return datetime.fromisoformat(AFTER_HORIZON)


def decision(**overrides):
    item = {"decision_id": "d1", "agent_id": "agent-a", "agent_version": "v1",
        "opportunity_id": "opportunity-1", "symbol": "SYNTH", "asset_class": "us_equity",
        "currency": "USD", "action": "buy", "quantity_delta": "1.25",
        "decision_at": "2026-01-05T14:30:01+00:00", "horizon_end": "2026-01-05T15:30:00+00:00",
        "input_hash": "a" * 64, "episode_id": "episode-long",
        "reference": {"price": "10", "price_kind": "mid", "observed_at": START,
            "available_at": START, "source": "fixture", "feed": "fixture-feed", "max_age_seconds": 60}}
    return {**deepcopy(item), **overrides}


def order(**overrides):
    return {**dict(source_alias="paper_a", order_id="order-entry", symbol="SYNTH",
        asset_class="us_equity", currency="USD", side="buy", quantity="1.25",
        filled_quantity="0.5", status="canceled", submitted_at="2026-01-05T14:30:02+00:00"), **overrides}


def fill(**overrides):
    return {**dict(source_alias="paper_a", fill_id="fill-entry", order_id="order-entry", symbol="SYNTH",
        asset_class="us_equity", currency="USD", quantity_delta="0.5", price="10",
        occurred_at="2026-01-05T14:30:03+00:00"), **overrides}


def inventory(**overrides):
    return {**dict(source_alias="paper_a", symbol="SYNTH", asset_class="us_equity", currency="USD",
        quantity="0", observed_at=START, capture_started_at=START, capture_completed_at=START,
        open_order_ids=[], origin="synthetic_fixture"), **overrides}


def cost(**overrides):
    return {**dict(cost_id="cost-entry", source_alias="paper_a", component="commission", amount="0.02",
        currency="USD", evidence_kind="observed", applies_at="2026-01-05T14:30:03+00:00",
        order_id="order-entry"), **overrides}


def mark(**overrides):
    return {**dict(mark_id="mark-horizon", symbol="SYNTH", currency="USD", price="12", price_kind="mid",
        source="fixture", feed="fixture-feed", observed_at="2026-01-05T15:30:00+00:00",
        available_at="2026-01-05T15:30:00+00:00"), **overrides}


def plan(**overrides):
    return {**dict(plan_id="comparison-1", baseline_version="v1", candidate_version="v2",
        window_start=START, window_end=END, metric="episode_net_return_bps",
        horizon_policy="decision_at_declared_end", reference_policy="exact_reference",
        cost_policy="complete_observed", match_policy="exact_opportunity", minimum_pairs=2), **overrides}


def complete_cost_scope(episode_id, *, short=False, borrow="0"):
    components = {name: {"applicable": True, "evidence_ref": "synthetic-cost-contract"}
                  for name in ("commission", "transaction", "venue", "regulatory")}
    components["borrow"] = {"applicable": (None if borrow is None else True) if short else False,
                            "evidence_ref": "synthetic-cost-contract"}
    components["financing"] = {"applicable": False, "evidence_ref": "synthetic-fully-funded"}
    return {"episode_id": episode_id, "components": components, "evidence_kind": "observed"}


@pytest.fixture
def feedback_project(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(tmp_path, create=True):
        pass
    return tmp_path


def episode_records(*, short=False, mixed=False, alias="paper_a", version="v1", suffix=""):
    """Two explicit decisions/orders/fills, independent known cost records."""
    eid = ("episode-short" if short else "episode-long") + suffix
    d1 = decision(decision_id="d1"+suffix, agent_version=version, episode_id=eid,
        action="sell" if short else "buy", quantity_delta="-0.25" if short else "1.25")
    d2 = decision(decision_id="d2"+suffix, agent_version="v2" if mixed else version,
        episode_id=eid, opportunity_id="opportunity-close", action="buy" if short else "sell",
        quantity_delta="0.25" if short else "-0.5", decision_at="2026-01-05T14:31:00+00:00")
    d1["reference"]["price"] = "20" if short else "10"
    d2["reference"].update(price="18" if short else "12", observed_at="2026-01-05T14:30:59+00:00",
                           available_at="2026-01-05T14:30:59+00:00")
    entry_order, exit_order = "order-entry"+suffix, "order-exit"+suffix
    items = [("inventory", inventory(source_alias=alias)), ("decision", d1), ("decision", d2),
        ("order_binding", dict(decision_id=d1["decision_id"], source_alias=alias, order_id=entry_order)),
        ("order_binding", dict(decision_id=d2["decision_id"], source_alias=alias, order_id=exit_order)),
        ("order", order(source_alias=alias, order_id=entry_order, side="sell" if short else "buy",
            quantity="0.25" if short else "1.25", filled_quantity="0.25" if short else "0.5",
            status="filled" if short else "canceled")),
        ("order", order(source_alias=alias, order_id=exit_order, side="buy" if short else "sell",
            quantity="0.25" if short else "0.5", filled_quantity="0.25" if short else "0.5", status="filled",
            submitted_at="2026-01-05T14:31:01+00:00")),
        ("fill", fill(source_alias=alias, fill_id="fill-entry"+suffix, order_id=entry_order,
            quantity_delta="-0.25" if short else "0.5", price="20" if short else "10")),
        ("fill", fill(source_alias=alias, fill_id="fill-exit"+suffix, order_id=exit_order,
            quantity_delta="0.25" if short else "-0.5", price="18" if short else "12",
            occurred_at="2026-01-05T14:31:02+00:00")),
        ("cost", cost(source_alias=alias, cost_id="cost-entry"+suffix, order_id=entry_order, amount="0.02")),
        ("cost", cost(source_alias=alias, cost_id="cost-exit"+suffix, order_id=exit_order,
            amount="0" if short else "0.03", applies_at="2026-01-05T14:31:02+00:00")),
        ("cost_scope", complete_cost_scope(eid, short=short, borrow=None if short else "0"))]
    for component in ("transaction", "venue", "regulatory"):
        items.append(("cost", dict(cost_id=component+suffix, source_alias=alias, component=component,
            amount="0", currency="USD", evidence_kind="observed", applies_at=START, episode_id=eid)))
    return [dict(event_id=f"fixture-{i}"+suffix, kind=kind, payload=payload,
        origin="captured" if kind == "decision" else "broker", environment="paper")
        for i, (kind, payload) in enumerate(items)]


def make_snapshot(project, records):
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(project, create=True) as store:
        for record in records:
            timestamp = record["payload"]["decision_at"] if record["kind"] == "decision" else AFTER_HORIZON
            store.clock = lambda t=timestamp: datetime.fromisoformat(t)
            store.append_batch([record])
        return store.snapshot()


@pytest.fixture
def partial_cancel_snapshot(tmp_path):
    return make_snapshot(tmp_path, episode_records())


@pytest.fixture
def mixed_version_snapshot(tmp_path):
    return make_snapshot(tmp_path, episode_records(mixed=True))
