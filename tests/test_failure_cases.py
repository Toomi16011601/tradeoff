"""Public case execution remains actual, pinned, and independently replayable."""
import pytest


@pytest.mark.parametrize('name', ['riskkit', 'coinglass'])
def test_public_case_has_explicit_original_and_causal_execution_callbacks(name):
    from tradeoff.cases import get_case
    case = get_case(name)
    assert callable(case.get('original_execution')), 'Public original execution boundary missing'
    assert callable(case.get('fixed_execution')), 'Public causal execution boundary missing'


def test_causal_riskkit_execution_tape_exercises_actual_roundtrips():
    pytest.importorskip('backtesting')
    from tradeoff.cases import get_case
    case = get_case('riskkit')
    assert callable(case.get('execution_rows')), 'Separate execution stress input missing'
    result = case['fixed_execution'](case['execution_rows'](), {}, 7,
        {'commission_bps': 0, 'spread_bps': 0, 'delay_bars': 0})
    assert len(result['trades']) >= 2, 'An inactive control does not exercise cost/delay execution'


@pytest.mark.parametrize('name', ['riskkit', 'coinglass'])
def test_public_execution_reports_native_complete_equity_and_preserves_tape(name):
    pytest.importorskip('backtesting')
    from copy import deepcopy
    from tradeoff.cases import get_case
    case = get_case(name)
    rows = case['rows']()
    before = deepcopy(rows)
    result = case['fixed_execution'](rows, {}, 7,
        {'commission_bps': 25, 'spread_bps': 0, 'delay_bars': 1})
    assert rows == before
    assert result['engine'] == 'backtesting'
    assert result['engine_version'] == '0.6.6'
    assert len(result['equity']) == len(rows)
    assert result['effective_settings']['commission'] == pytest.approx(
        case['provenance']['engine_settings']['commission'] + 0.0025)
    assert result['scenario']['delay_bars'] == 1
