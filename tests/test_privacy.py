"""Synthetic regression checks for accidental private-data exports."""
from copy import deepcopy
import traceback
import pytest

from backtest_witness.audit import audit
from backtest_witness.failure_lab import run_failure_lab
from backtest_witness.report.renderer import write_report
from backtest_witness.report.failure_renderer import write_failure_report
from backtest_witness.reproduce import export_reproducer
from backtest_witness.failure_reproduce import export_failure_reproducer
from test_audit import clean, future_last
from test_validation import tape
from test_failure_lab import bars, execution, scenario


@pytest.mark.parametrize('lab', [False, True])
@pytest.mark.parametrize('private', [
    {'api_key': 'SYNTHETIC_CREDENTIAL_SENTINEL'},
    {'nested': [{'clientSecret': 'SYNTHETIC_CREDENTIAL_SENTINEL'}]},
    {'owner_email': 'example-person@example.invalid'},
    {'source': '/Users/example-person/private/data.json'},
    {'note': '-----BEGIN PRIVATE KEY----- synthetic'},
])
def test_private_inputs_are_rejected_before_callback(lab, private):
    calls = []
    def run(*args):
        calls.append(args)
        return execution(*args) if lab else clean(*args)
    with pytest.raises(ValueError, match='sensitive') as exc:
        (run_failure_lab if lab else audit)(run, bars() if lab else tape(), private)
    assert calls == []
    assert 'SYNTHETIC_CREDENTIAL_SENTINEL' not in str(exc.value)
    assert 'example-person' not in str(exc.value)


def test_private_extra_rows_are_rejected_before_callback():
    rows = bars()
    rows[0]['account_number'] = 'SYNTHETIC_ACCOUNT_SENTINEL'
    with pytest.raises(ValueError, match='sensitive'):
        run_failure_lab(execution, rows)


@pytest.mark.parametrize('lab', [False, True])
def test_unknown_callback_exception_text_is_not_saved(lab):
    def broken(*args):
        raise RuntimeError('SYNTHETIC_PRIVATE_EXCEPTION_SENTINEL')
    report = (run_failure_lab if lab else audit)(broken, bars() if lab else tape())
    assert 'SYNTHETIC_PRIVATE_EXCEPTION_SENTINEL' not in str(report)
    assert 'RuntimeError' in report['reason']


def test_private_trace_diagnostics_are_not_retained():
    def run(rows, config, seed):
        result = clean(rows, config, seed)
        result[0]['features'] = {'api_key': 'SYNTHETIC_TRACE_SENTINEL'}
        return result
    report = audit(run, tape())
    assert report['status'] == 'INCONCLUSIVE'
    assert 'SYNTHETIC_TRACE_SENTINEL' not in str(report)


@pytest.mark.parametrize('lab', [False, True])
def test_private_report_cannot_be_written_or_exported(tmp_path, lab):
    report = (run_failure_lab(execution, bars(), scenarios=[scenario(200)])
              if lab else audit(future_last, tape(), min_history=1))
    report['config']['api_key'] = 'SYNTHETIC_REPORT_SENTINEL'
    destination = tmp_path / 'output'
    with pytest.raises(ValueError, match='sensitive'):
        (write_failure_report if lab else write_report)(report, destination)
    assert not destination.exists()
    with pytest.raises(ValueError, match='sensitive'):
        (export_failure_reproducer if lab else export_reproducer)(report, destination, 'example:run')
    assert not destination.exists()


def test_ordinary_parameters_and_empty_credential_slots_remain_usable():
    config = {'token_limit': 200, 'secret_window': 3, 'api_key': None, 'api_secret': ''}
    original = deepcopy(config)
    report = audit(clean, tape(), config)
    assert report['config'] == original
    assert config == original


@pytest.mark.parametrize('lab', [False, True])
def test_replay_does_not_repeat_private_callback_exception(tmp_path, lab):
    from backtest_witness.reproduce import load_fixture, assert_future_invariance
    from backtest_witness.failure_reproduce import load_failure_fixture, assert_failure_resilience
    report = (run_failure_lab(execution, bars(), scenarios=[scenario(200)])
              if lab else audit(future_last, tape(), min_history=1))
    (export_failure_reproducer if lab else export_reproducer)(report, tmp_path, 'example:run')
    fixture = (load_failure_fixture(tmp_path / 'failure-fixture.json') if lab
               else load_fixture(tmp_path / 'reproducer.json'))
    def broken(*args):
        raise RuntimeError('SYNTHETIC_PRIVATE_REPLAY_SENTINEL')
    with pytest.raises(ValueError) as exc:
        (assert_failure_resilience if lab else assert_future_invariance)(broken, fixture)
    assert 'SYNTHETIC_PRIVATE_REPLAY_SENTINEL' not in ''.join(traceback.format_exception(exc.value))


def test_known_private_warning_does_not_enter_failure_report():
    def run(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        result['warnings'] = ['Contact example-person@example.invalid']
        return result
    report = run_failure_lab(run, bars())
    assert report['status'] == 'INCONCLUSIVE'
    assert 'example-person' not in str(report)


def test_safe_backend_limitation_remains_explanatory():
    from backtest_witness.privacy import ExecutionUnavailable
    def unsupported(*args):
        raise ExecutionUnavailable('delayed stop orders are unsupported')
    report = run_failure_lab(unsupported, bars())
    assert 'delayed stop orders' in report['reason']


def test_sensitive_backend_limitation_is_suppressed():
    from backtest_witness.privacy import ExecutionUnavailable
    def unsupported(*args):
        raise ExecutionUnavailable('Contact example-person@example.invalid')
    report = run_failure_lab(unsupported, bars())
    assert 'example-person' not in str(report)


def test_invalid_json_cannot_echo_a_private_key_into_diagnostics():
    def run(rows, config, seed, stress):
        result = execution(rows, config, seed, stress)
        result['example-person@example.invalid'] = object()
        return result
    report = run_failure_lab(run, bars())
    assert report['status'] == 'INCONCLUSIVE'
    assert 'example-person' not in str(report)


def test_token_shaped_callback_reference_cannot_be_exported(tmp_path):
    report = audit(future_last, tape(), min_history=1)
    with pytest.raises(ValueError, match='sensitive'):
        export_reproducer(report, tmp_path, 'ghp_' + 'A' * 24 + ':run')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('lab', [False, True])
def test_gallery_does_not_export_recognized_private_names(tmp_path, lab):
    from backtest_witness.report.renderer import write_gallery
    from backtest_witness.report.failure_renderer import write_failure_gallery
    destination = tmp_path / 'gallery'
    entries = [dict(status='FAILURE_FOUND' if lab else 'FOUND', path='case/index.html',
                    name='example-person@example.invalid')]
    with pytest.raises(ValueError, match='sensitive'):
        (write_failure_gallery if lab else write_gallery)(destination, entries)
    assert not destination.exists()


@pytest.mark.parametrize('lab', [False, True])
@pytest.mark.parametrize('container', [list, tuple])
@pytest.mark.parametrize('field', ['api_key', 'email'])
def test_report_exports_reject_sensitive_fields_nested_in_serializable_sequences(
        tmp_path, lab, container, field):
    # JSON serialization accepts tuples, so privacy checks must inspect them
    # before either writer can put recognized credentials/contact fields on disk.
    report = (run_failure_lab(execution, bars(), scenarios=[scenario(200)])
              if lab else audit(future_last, tape(), min_history=1))
    report['extra_context'] = [container([{'nested': [{field: 'SYNTHETIC_SEQUENCE_SENTINEL'}]}])]
    destination = tmp_path / 'portable'
    with pytest.raises(ValueError, match='sensitive'):
        (write_failure_report if lab else write_report)(report, destination)
    assert not destination.exists()


def test_privacy_checks_reject_tuple_cycles_and_excessive_nesting():
    from backtest_witness.privacy import reject_sensitive_data
    children = []
    cycle = (children,)
    children.append(cycle)
    with pytest.raises(ValueError, match='cycle'):
        reject_sensitive_data(cycle)
    nested = 'ordinary'
    for _ in range(258):
        nested = (nested,)
    with pytest.raises(ValueError, match='nesting depth'):
        reject_sensitive_data(nested)


def test_privacy_checks_allow_empty_tuple_credential_slots_and_shared_sequences():
    from backtest_witness.privacy import reject_sensitive_data
    shared = ('ordinary', {'window': 3})
    value = {'api_key': (), 'email': (), 'features': [shared, shared]}
    before = deepcopy(value)
    reject_sensitive_data(value)
    assert value == before
