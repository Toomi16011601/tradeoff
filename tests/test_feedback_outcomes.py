"""Automatic local price collection closes real workflow gaps without inventing evidence."""
from datetime import datetime
import json

import pytest

from feedback_helpers import AFTER_HORIZON, decision, feedback_project


def setup_source(project, text=None, **overrides):
    from tradeoff.feedback.api import FeedbackApp
    file = project / 'prices.csv'
    file.write_text(text or 'timestamp,price\n2026-01-05T15:30:00Z,12.000000000000000001\n')
    app = FeedbackApp(project, clock=lambda: datetime.fromisoformat(AFTER_HORIZON))
    args = dict(data_file='prices.csv', symbol='SYNTH', currency='USD', source='fixture',
                feed='fixture-feed', price_kind='mid', **overrides)
    return app, args


def record(project, **overrides):
    from tradeoff.feedback.recorder import Recorder
    return Recorder(project).record_decision(decision(**overrides), event_id='decision-event')


def snapshot(project):
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(project, readonly=True) as store:
        return store.snapshot()


def test_collect_completes_trade_and_hold_outcomes_with_exact_prices(feedback_project):
    from tradeoff.feedback.recorder import Recorder
    app, args = setup_source(feedback_project)
    record(feedback_project)
    Recorder(feedback_project).record_decision(decision(decision_id='hold', action='hold', quantity_delta='0'), event_id='hold-event')
    app.dispatch('configure_price_source', args)
    before = app.evaluate_decisions({'as_of':AFTER_HORIZON})
    assert all(d['outcome_status']=='UNAVAILABLE' for d in before['evaluation']['decisions'])
    result = app.dispatch('collect_outcomes', {})
    assert result['status']=='COLLECTED'
    assert result['collection']['new_marks']==1
    assert result['collection']['newly_available_outcomes']==2
    assert all(d['outcome_status']=='AVAILABLE' for d in result['feedback']['evaluation']['decisions'])
    assert {d['horizon_price_change'] for d in result['feedback']['evaluation']['decisions']} == {'2.000000000000000001'}
    saved = [e for e in snapshot(feedback_project)['events'] if e['kind']=='mark']
    assert saved[0]['origin']=='imported'
    assert saved[0]['payload']['price']=='12.000000000000000001'
    assert saved[0]['payload']['available_at']==AFTER_HORIZON
    assert result['feedback']['evaluation']['decisions'][0]['realized_decision_pnl'] is None
    assert str(feedback_project) not in json.dumps(result)


def test_repeated_collection_does_not_duplicate_or_rewrite_old_availability(feedback_project):
    app, args = setup_source(feedback_project)
    record(feedback_project)
    app.configure_price_source(args)
    app.collect_outcomes({})
    before = snapshot(feedback_project)
    app.clock = lambda: datetime.fromisoformat('2026-01-06T16:00:00+00:00')
    again = app.collect_outcomes({})
    assert again['collection']['new_marks']==0
    assert again['collection']['newly_available_outcomes']==0
    assert snapshot(feedback_project)==before


@pytest.mark.parametrize('mismatch', ['feed','source','price_kind','symbol','currency'])
def test_wrong_source_identity_never_fills_a_missing_outcome(feedback_project, mismatch):
    app, args = setup_source(feedback_project)
    record(feedback_project)
    args[mismatch] = {'price_kind':'close','currency':'EUR'}.get(mismatch,'different')
    app.configure_price_source(args)
    result = app.collect_outcomes({})
    assert result['collection']['new_marks']==0
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='UNAVAILABLE'
    assert result['collection']['unresolved'][0]['code']=='SOURCE_MISMATCH'


@pytest.mark.parametrize('price_time', ['2026-01-05T15:29:00Z','2026-01-05T15:31:00Z'])
def test_stale_and_future_prices_are_not_substituted(feedback_project, price_time):
    app, args = setup_source(feedback_project, f'timestamp,price\n{price_time},12\n')
    item = decision()
    item['reference']['max_age_seconds']=0
    record(feedback_project, **item)
    app.configure_price_source(args)
    result = app.collect_outcomes({})
    assert result['collection']['new_marks']==0
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='UNAVAILABLE'


def test_pending_horizons_remain_waiting_without_reading_future_prices(feedback_project):
    app, args = setup_source(feedback_project)
    record(feedback_project)
    app.configure_price_source(args)
    app.clock=lambda: datetime.fromisoformat('2026-01-05T15:00:00+00:00')
    result=app.collect_outcomes({})
    assert result['collection']['new_marks']==0
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='PENDING'


def test_current_file_receipt_does_not_backdate_price_availability(feedback_project):
    app, args=setup_source(feedback_project)
    record(feedback_project)
    app.configure_price_source(args)
    result=app.collect_outcomes({'as_of':'2026-01-05T15:31:00Z'})
    assert result['collection']['new_marks']==0
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='UNAVAILABLE'


def test_explicit_receipt_times_support_historical_as_of_without_guessing(feedback_project):
    app, args=setup_source(feedback_project,
        'timestamp,price,available_at\n2026-01-05T15:30:00Z,12,2026-01-05T15:30:05Z\n', available_at_column='available_at')
    record(feedback_project)
    app.configure_price_source(args)
    result=app.collect_outcomes({'as_of':'2026-01-05T15:31:00Z'})
    assert result['collection']['new_marks']==1
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='AVAILABLE'


def test_changed_observation_is_rejected_without_partial_appends(feedback_project):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project)
    record(feedback_project)
    app.configure_price_source(args)
    app.collect_outcomes({})
    before=snapshot(feedback_project)
    (feedback_project/'prices.csv').write_text('timestamp,price\n2026-01-05T15:30:00Z,99\n')
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({})
    assert caught.value.code=='PRICE_OBSERVATION_CONFLICT'
    assert snapshot(feedback_project)==before


def test_configuration_preserves_existing_settings_until_explicit_replace(feedback_project):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project)
    app.configure_price_source(args)
    config=feedback_project/'.tradeoff/feedback/price-source.json'
    before=(config.read_bytes(),config.stat().st_mtime_ns)
    app.configure_price_source(args)
    assert (config.read_bytes(),config.stat().st_mtime_ns)==before
    with pytest.raises(FeedbackError) as caught:
        app.configure_price_source({**args,'feed':'other'})
    assert caught.value.code=='PRICE_SOURCE_EXISTS'
    assert config.read_bytes()==before[0]
    app.configure_price_source({**args,'feed':'other','replace':True})
    assert json.loads(config.read_text())['feed']=='other'


@pytest.mark.parametrize('bad_csv', [
    'timestamp,price,price\n2026-01-05T15:30:00Z,12,99\n',
    'timestamp,price\n2026-01-05T15:30:00Z,12,99\n',
    'timestamp,price\n2026-01-05T15:30:00Z,NaN\n',
    'timestamp,price\n2026-01-05T15:30:00Z,-1\n',
    'timestamp,price,api_key\n2026-01-05T15:30:00Z,12,SYNTHETIC_SECRET_SENTINEL\n',
])
def test_bad_price_files_fail_safely_without_ledger_changes(feedback_project,bad_csv):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project,bad_csv)
    record(feedback_project)
    app.configure_price_source(args)
    before=snapshot(feedback_project)
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({})
    assert 'SYNTHETIC_SECRET_SENTINEL' not in str(caught.value)
    assert str(feedback_project) not in str(caught.value)
    assert snapshot(feedback_project)==before


def test_date_only_source_needs_declared_time_conventions(feedback_project):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project,'Date,Close\n2026-01-05,12\n',timestamp_column='Date',price_column='Close')
    record(feedback_project,horizon_end='2026-01-05T16:00:00+00:00')
    app.configure_price_source(args)
    with pytest.raises(FeedbackError):
        app.collect_outcomes({})
    app.configure_price_source({**args,'timezone':'UTC','session_close':'16:00','replace':True})
    result=app.collect_outcomes({})
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='AVAILABLE'


def test_wrong_clock_options_are_rejected_before_replacing_configuration(feedback_project):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project)
    app.configure_price_source(args)
    config=feedback_project/'.tradeoff/feedback/price-source.json'
    before=config.read_bytes()
    with pytest.raises(FeedbackError) as caught:
        app.configure_price_source({**args,'timezone':'not-a-zone','replace':True})
    assert caught.value.code=='INVALID_TIMEZONE'
    assert config.read_bytes()==before


def test_existing_manually_imported_observation_cannot_be_overridden_by_a_new_id(feedback_project):
    from feedback_helpers import mark
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project)
    record(feedback_project)
    app.import_evidence({'records':[dict(event_id='existing-mark',kind='mark',payload=mark(price='99'))]})
    app.configure_price_source(args)
    before=snapshot(feedback_project)
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({})
    assert caught.value.code=='PRICE_OBSERVATION_CONFLICT'
    assert snapshot(feedback_project)==before


def test_embedded_feed_identity_is_not_silently_relabelled(feedback_project):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project,'timestamp,price,feed\n2026-01-05T15:30:00Z,12,other-feed\n')
    record(feedback_project)
    app.configure_price_source(args)
    before=snapshot(feedback_project)
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({})
    assert caught.value.code=='PRICE_SOURCE_IDENTITY_CONFLICT'
    assert snapshot(feedback_project)==before


def test_absolute_home_path_is_normalized_locally_without_leaking_into_feedback(tmp_path):
    from tradeoff.feedback.store import FeedbackStore
    project=tmp_path/'home'/'synthetic-owner'/'agent'
    project.mkdir(parents=True)
    with FeedbackStore(project,create=True):
        pass
    app,args=setup_source(project)
    args['data_file']=str(project/'prices.csv')
    record(project)
    app.configure_price_source(args)
    result=app.collect_outcomes({})
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='AVAILABLE'
    config=json.loads((project/'.tradeoff/feedback/price-source.json').read_text())
    assert config['data_file']=='prices.csv'
    assert 'synthetic-owner' not in json.dumps(result)
    assert 'synthetic-owner' not in json.dumps(config)


def test_duplicate_manual_mark_ids_with_conflicting_payloads_block_collection(feedback_project):
    from feedback_helpers import mark
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project,'timestamp,price\n2026-01-05T15:30:00Z,12\n')
    record(feedback_project)
    app.import_evidence({'records':[dict(event_id='old-mark',kind='mark',payload=mark(price='99')),
                                     dict(event_id='conflicting-mark',kind='mark',payload=mark(price='12'))]})
    app.configure_price_source(args)
    before=snapshot(feedback_project)
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({})
    assert caught.value.code=='PRICE_OBSERVATION_CONFLICT'
    assert snapshot(feedback_project)==before


def test_an_earlier_conflicting_observation_blocks_a_later_candidate_atomically(feedback_project):
    from feedback_helpers import mark
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project,
        'timestamp,price\n2026-01-05T15:29:30Z,12\n2026-01-05T15:30:00Z,13\n')
    record(feedback_project)
    app.import_evidence({'records':[dict(event_id='old-mark',kind='mark',payload=mark(price='99',observed_at='2026-01-05T15:29:30Z'))]})
    app.configure_price_source(args)
    before=snapshot(feedback_project)
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({})
    assert caught.value.code=='PRICE_OBSERVATION_CONFLICT'
    assert snapshot(feedback_project)==before


def test_future_as_of_cannot_turn_unobserved_future_prices_into_available_evidence(feedback_project):
    from tradeoff.feedback.contracts import FeedbackError
    app,args=setup_source(feedback_project)
    record(feedback_project)
    app.configure_price_source(args)
    app.clock=lambda:datetime.fromisoformat('2026-01-05T15:00:00+00:00')
    before=snapshot(feedback_project)
    with pytest.raises(FeedbackError) as caught:
        app.collect_outcomes({'as_of':AFTER_HORIZON})
    assert caught.value.code=='FUTURE_COLLECTION_CUTOFF'
    assert snapshot(feedback_project)==before
