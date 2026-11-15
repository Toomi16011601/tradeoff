"""Behavior boundaries for recorded evidence; never derive prices from positions."""
import json

from tradeoff.report import render_report
from test_report import Document, report


def payload(data):
    doc = Document(render_report(data))
    return doc, json.loads(next(value for attrs, value in doc.scripts if attrs.get('id') == 'report-data'))


def node(doc, identity):
    return next((attrs for _, attrs in doc.nodes if attrs.get('id') == identity), {})


def test_price_and_two_step_traces_render_from_recorded_rows_without_economics():
    data = report()
    data['economics'] = None
    doc, browser = payload(data)
    assert node(doc, 'temporal-chart').get('role') == 'img'
    assert any(attrs.get('class') == 'position-original' for _, attrs in doc.nodes)
    assert any(attrs.get('class') == 'position-intervention' for _, attrs in doc.nodes)
    assert len([1 for _, attrs in doc.nodes if 'candle-body' in attrs.get('class', '').split()]) == 4
    assert browser['workstation']['bars'][1]['original_target'] == '1'
    assert browser['workstation']['bars'][1]['intervention_target'] == '0'
    assert node(doc, 'trace-scrubber')['value'] == '1'
    assert '2026-01-02T16:00:00+00:00' in doc.text


def test_pair_alignment_uses_instant_and_absent_pair_stays_unavailable():
    data = report()
    data['witness']['mutated_trace'] = [
        {'timestamp': '2026-01-02T17:00:00+01:00', 'target': 8},
        {'timestamp': '2026-01-01T16:00:00+00:00', 'target': -4},
    ]
    _, browser = payload(data)
    bars = browser['workstation']['bars']
    assert [bar['intervention_target'] for bar in bars] == ['-4', '8', None, None]
    assert bars[2]['original_target'] == '0'


def test_missing_ohlc_keeps_trace_without_fabricated_candles():
    data = report('NO_DEPENDENCY_OBSERVED')
    doc, browser = payload(data)
    assert node(doc, 'temporal-chart')
    assert 'Recorded OHLC unavailable' in doc.text
    assert browser['workstation']['has_prices'] is False
    assert all(bar['ohlc'] is None for bar in browser['workstation']['bars'])
    assert not any('candle-body' in attrs.get('class', '').split() for _, attrs in doc.nodes)
    assert all(bar['intervention_target'] is None for bar in browser['workstation']['bars'])


def test_missing_trace_disables_recorded_replay_and_witness_actions():
    data = report('INCONCLUSIVE')
    data['baseline'] = None
    doc, browser = payload(data)
    assert browser['workstation']['bars'] == []
    assert 'Recorded decision trace unavailable' in doc.text
    for identity in ['trace-scrubber', 'trace-previous', 'trace-next', 'trace-replay', 'witness-select', 'changed-row-select']:
        assert 'disabled' in node(doc, identity), identity


def test_exact_targets_changed_fields_and_hostile_symbols_remain_inert():
    data = report()
    data['dataset']['symbol'] = '<img src=x onerror=owned()>'
    data['baseline']['trace'][1]['target'] = 9007199254740992
    data['witness']['mutated_trace'][1]['target'] = 9007199254740993
    doc, browser = payload(data)
    bar = browser['workstation']['bars'][1]
    assert (bar['original_target'], bar['intervention_target']) == ('9007199254740992', '9007199254740993')
    changed = browser['workstation']['bars'][3]
    assert changed['changed'] is True
    assert changed['changes'][0] == {'field': 'open', 'before': '10', 'after': '100'}
    assert not any(tag == 'img' or 'onerror' in attrs for tag, attrs in doc.nodes)
    assert len(doc.scripts) == 2


def test_adjacent_huge_targets_do_not_claim_equal_plot_values():
    data = report()
    data['baseline']['trace'][1]['target'] = 9007199254740992
    data['witness']['mutated_trace'][1]['target'] = 9007199254740993
    _, browser = payload(data)
    assert browser['workstation']['exact_scale'] is False
    assert 'Exact values in inspector' in Document(render_report(data)).text


def test_unavailability_uses_availability_and_cutoff_marker_does_not_require_a_bar():
    data = report()
    data['witness']['cutoff'] = '2026-01-02T17:00:00+00:00'
    data['witness']['original_rows'][0]['available_at'] = '2026-01-04T17:00:00+00:00'
    doc, browser = payload(data)
    bars = browser['workstation']['bars']
    assert bars[0]['unavailable'] is True
    assert bars[1]['unavailable'] is False
    assert any(attrs.get('class') == 'cutoff-marker' for _, attrs in doc.nodes)
    # Day 1 is already unavailable despite its earlier event timestamp.
    shaded = [attrs for tag, attrs in doc.nodes if tag == 'rect' and attrs.get('class') == 'unavailable-region']
    assert any(float(attrs['x']) == 68 for attrs in shaded)


def test_inspector_keeps_exact_cutoff():
    doc, _ = payload(report())
    assert node(doc, 'selected-cutoff')


def test_extreme_prices_do_not_emit_nonfinite_geometry():
    import math

    data = report()
    data['economics'] = None
    for row in data['witness']['original_rows']:
        row.update(open=1.7976931348623157e308, high=1.7976931348623157e308,
                   low=1.7976931348623157e308, close=1.7976931348623157e308)
    doc, _ = payload(data)
    for tag, attrs in doc.nodes:
        if tag in {'line', 'rect', 'text'}:
            for key in ['x', 'x1', 'x2', 'y', 'y1', 'y2', 'width', 'height']:
                if key in attrs:
                    assert math.isfinite(float(attrs[key])), (tag, key, attrs[key])


def test_ohlc_display_preserves_adjacent_large_integer_values():
    data = report()
    data['witness']['original_rows'][1].update(open=9007199254740992,
        high=9007199254740995, low=9007199254740991, close=9007199254740993)
    _, browser = payload(data)
    assert browser['workstation']['bars'][1]['ohlc_display'] == {
        'open': '9007199254740992', 'high': '9007199254740995',
        'low': '9007199254740991', 'close': '9007199254740993'}


def test_wide_finite_price_range_keeps_geometry_and_axis_labels_finite():
    import math

    data = report()
    data['economics'] = None
    for index, row in enumerate(data['witness']['original_rows']):
        value = 10 if index % 2 else 1e308
        row.update(open=value, high=value, low=value, close=value)
    doc, _ = payload(data)
    for tag, attrs in doc.nodes:
        if tag in {'line', 'rect', 'text'}:
            for key in ['x', 'x1', 'x2', 'y', 'y1', 'y2', 'width', 'height']:
                if key in attrs:
                    assert math.isfinite(float(attrs[key])), (tag, key, attrs[key])
    assert '-inf' not in doc.text.lower()
