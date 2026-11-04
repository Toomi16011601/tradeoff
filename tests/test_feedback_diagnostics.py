"""Read-only setup/evidence checks, independent of broker/model access."""
import json
from pathlib import Path

import pytest

from feedback_helpers import (AFTER_HORIZON, START, decision, episode_records,
                              feedback_project, make_snapshot)


def _doctor(project, **kwargs):
    from tradeoff.feedback.diagnostics import diagnose
    return diagnose(project, **kwargs)


def _checks(result):
    return {row['id']: row for row in result['checks']}


def _bytes(project):
    return {str(p.relative_to(project)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in Path(project).rglob('*') if p.is_file()}


def test_missing_project_does_not_initialize(tmp_path):
    result = _doctor(tmp_path)
    assert result['status'] == 'SETUP_REQUIRED'
    assert _checks(result)['storage']['status'] == 'FAIL'
    assert not (tmp_path / '.tradeoff').exists()


def test_empty_evidence_is_not_connected_and_doctor_is_readonly(feedback_project):
    from tradeoff.feedback.store import FeedbackStore
    before = _bytes(feedback_project)
    result = _doctor(feedback_project, as_of=AFTER_HORIZON)
    assert result['agent_hook'] == 'NOT_VERIFIED'
    assert result['evidence_status'] == 'NO_DECISIONS'
    assert _checks(result)['decisions']['status'] == 'WARN'
    assert _bytes(feedback_project) == before
    with FeedbackStore(feedback_project, readonly=True) as store:
        assert store.db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(Exception):
            store.append('test-write', 'decision', decision())
    assert _bytes(feedback_project) == before


@pytest.mark.parametrize('bound,expected', [(False, 'bindings'), (True, 'order_evidence')])
def test_missing_binding_is_distinct_from_missing_order(feedback_project, bound, expected):
    from tradeoff.feedback.recorder import Recorder
    recorder = Recorder(feedback_project)
    recorder.record_decision(decision(), event_id='decision-receipt')
    if bound:
        recorder.bind_order(dict(decision_id='d1', source_alias='paper_a', order_id='order-entry'), event_id='binding-receipt')
    result = _doctor(feedback_project, as_of=AFTER_HORIZON)
    checks = _checks(result)
    assert checks[expected]['status'] == 'WARN'
    if bound:
        assert checks['bindings']['status'] == 'PASS'
    assert result['agent_hook'] == 'NOT_VERIFIED'
    assert 'order-entry' not in json.dumps(result)
    assert 'opportunity-1' not in json.dumps(result)


def test_pending_horizon_is_waiting_not_missing(feedback_project):
    from tradeoff.feedback.recorder import Recorder
    Recorder(feedback_project).record_decision(decision(), event_id='d1-event')
    pending = _doctor(feedback_project, as_of='2026-01-05T14:31:00Z')
    assert _checks(pending)['outcomes']['status'] == 'WAIT'
    mature = _doctor(feedback_project, as_of=AFTER_HORIZON)
    assert _checks(mature)['outcomes']['status'] == 'WARN'
    assert mature['counts']['missing_outcomes'] == 1


def test_missing_inventory_and_costs_have_specific_next_steps(tmp_path):
    records = [r for r in episode_records() if r['kind'] not in {'inventory', 'cost', 'cost_scope'}]
    make_snapshot(tmp_path, records)
    result = _doctor(tmp_path, as_of=AFTER_HORIZON)
    checks = _checks(result)
    assert checks['inventory']['status'] == checks['costs']['status'] == 'WARN'
    assert 'before' in checks['inventory']['next_step'].lower()
    assert 'zero' in checks['costs']['next_step'].lower()
    assert str(tmp_path) not in json.dumps(result)


def test_complete_costs_do_not_hide_missing_horizon_marks(tmp_path):
    make_snapshot(tmp_path, episode_records())
    checks = _checks(_doctor(tmp_path, as_of=AFTER_HORIZON))
    assert checks['inventory']['status'] == checks['costs']['status'] == 'PASS'
    assert checks['outcomes']['status'] == 'WARN'


def test_tampered_database_fails_safely_and_remains_untouched(feedback_project):
    import sqlite3
    from tradeoff.feedback.recorder import Recorder
    Recorder(feedback_project).record_decision(decision(), event_id='d1-event')
    database = feedback_project / '.tradeoff/feedback/events.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute("UPDATE events SET event_hash='bad'")
    before = _bytes(feedback_project)
    result = _doctor(feedback_project)
    assert result['status'] == 'BLOCKED'
    assert _checks(result)['storage']['status'] == 'FAIL'
    assert _bytes(feedback_project) == before


def test_readonly_store_cannot_initialize(tmp_path):
    from tradeoff.feedback.contracts import FeedbackError
    from tradeoff.feedback.store import FeedbackStore
    with pytest.raises(FeedbackError) as caught:
        FeedbackStore(tmp_path, readonly=True, create=True)
    assert caught.value.code == 'READ_ONLY'
    assert not (tmp_path / '.tradeoff').exists()


def test_doctor_invalid_timestamp_remains_safe(tmp_path):
    from tradeoff.feedback.contracts import FeedbackError
    with pytest.raises(FeedbackError):
        _doctor(tmp_path, as_of='SYNTHETIC_SECRET_SENTINEL')
    assert not (tmp_path / '.tradeoff').exists()


def test_filled_order_without_fills_is_a_gap_even_with_horizon_mark(tmp_path):
    from feedback_helpers import mark
    records = [r for r in episode_records() if r['kind'] not in {'fill', 'inventory', 'cost', 'cost_scope'}]
    records.append(dict(event_id='horizon', kind='mark', payload=mark(), origin='broker', environment='paper'))
    make_snapshot(tmp_path, records)
    result = _doctor(tmp_path, as_of=AFTER_HORIZON)
    assert _checks(result)['fills']['status'] == 'WARN'
    assert result['counts']['orders_missing_fills'] == 2
    assert result['evidence_status'] == 'GAPS'


@pytest.mark.parametrize('active', [False, True])
def test_wal_projects_are_refused_without_creating_or_changing_sidecars(feedback_project, active):
    import sqlite3
    database = feedback_project / '.tradeoff/feedback/events.sqlite3'
    writer = sqlite3.connect(database)
    writer.execute('PRAGMA journal_mode=WAL')
    if active:
        # Leave a real committed WAL frame not checkpointed into the main file.
        writer.execute("INSERT INTO state VALUES ('synthetic-wal-test','{}')")
        writer.commit()
    else:
        writer.close()
    try:
        before = _bytes(feedback_project)
        result = _doctor(feedback_project)
        assert result['status'] == 'BLOCKED'
        assert 'WAL' in _checks(result)['storage']['message']
        assert _bytes(feedback_project) == before
    finally:
        if active:
            writer.close()
