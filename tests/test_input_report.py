"""Input limitations must remain visible beside a completed simulation result."""
from backtest_witness.failure_lab import run_failure_lab
from backtest_witness.report import write_failure_report
from test_failure_lab import bars, execution


def test_html_shows_acknowledged_input_limitations_before_scenario_results(tmp_path):
    report = run_failure_lab(execution, bars(), scenarios=[{'commission_bps': 200}])
    report['input_checks'] = {
        'required_columns': ['Close', 'Volume'], 'required_globals': [],
        'warnings': ['Zero volume acknowledged; volume filters may be ineffective.'],
        'data_warnings': [{'code': 'IRREGULAR_INTERVALS',
                           'message': 'Observed bars have irregular spacing.', 'columns': ['timestamp']}],
        'checks': {'source_available': True, 'data_scope': 'direct reads only'}}
    write_failure_report(report, tmp_path)
    html = (tmp_path / 'index.html').read_text()
    # Check the rendered visible block, not the embedded JSON copy alone.
    content = html.split('<script', 1)[0]
    assert 'id="input-checks"' in content
    assert 'Zero volume acknowledged' in content
    assert 'Observed bars have irregular spacing.' in content
    assert content.index('id="input-checks"') < content.index('id="scenarios"')
