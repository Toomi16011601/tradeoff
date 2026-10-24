"""Project setup stays static until review; check exercises the normal audit."""
import csv
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ('from backtesting import Strategy\nclass LocalStrategy(Strategy):\n'
          '    def init(self):\n        self.leaked = self.data.Close[-1] > 110\n'
          '    def next(self):\n        if self.leaked and not self.position:\n            self.buy(size=3)\n')


def invoke(cwd, *args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    return subprocess.run([sys.executable, '-m', 'tradeoff', *map(str, args)],
                          cwd=cwd, env=env, capture_output=True, text=True)


def project(tmp_path, source=NATIVE, labels=None):
    from tradeoff.demos import synthetic_rows
    source_path = tmp_path / 'strategy.py'
    source_path.write_text(source)
    rows = synthetic_rows()
    if labels:
        for index, row in enumerate(rows):
            row['timestamp'] = labels(index, row['timestamp'])
            row['available_at'] = row['timestamp']
    data = tmp_path / 'bars.csv'
    with data.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return source_path, data


def initialize(tmp_path, *options):
    return invoke(tmp_path, 'init', '--strategy', 'strategy.py', '--data', 'bars.csv', '--json', '--timestamp-kind', 'close', *options)


def test_init_never_imports_strategy_and_requires_explicit_review(tmp_path):
    project(tmp_path, "raise RuntimeError('must never import during init')\n" + NATIVE)
    result = initialize(tmp_path)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary['status'] == 'NEEDS_INPUT'
    assert any(item['code'] == 'IMPORT_REVIEW_REQUIRED' for item in summary['issues'])
    manifest = json.loads((tmp_path / 'tradeoff.json').read_text())
    assert manifest['schema_version'] == 'tradeoff.project.v1'
    assert manifest['adapter'] == 'strategy:LocalStrategy'
    assert manifest['engine'] == 'backtesting'
    checked = invoke(tmp_path, 'check', '--json')
    assert checked.returncode == 2
    assert json.loads(checked.stdout)['error']['code'] == 'PROJECT_NEEDS_INPUT'
    assert not (tmp_path / '.tradeoff').exists()


def test_init_refuses_existing_manifest(tmp_path):
    project(tmp_path)
    (tmp_path / 'tradeoff.json').write_text('keep me')
    result = initialize(tmp_path, '--review-imports')
    assert result.returncode == 2
    assert json.loads(result.stdout)['error']['code'] == 'PROJECT_EXISTS'
    assert (tmp_path / 'tradeoff.json').read_text() == 'keep me'


def test_ambiguous_classes_need_selection_and_can_be_selected_with_flags(tmp_path):
    project(tmp_path, NATIVE + '\nclass Other(Strategy):\n    pass\n')
    result = initialize(tmp_path, '--review-imports')
    assert json.loads(result.stdout)['status'] == 'NEEDS_INPUT'
    assert any(item['code'] == 'STRATEGY_SELECTION_REQUIRED' for item in json.loads(result.stdout)['issues'])
    pytest.importorskip('backtesting')
    checked = invoke(tmp_path, 'check', '--strategy-class', 'LocalStrategy', '--json', '--max-calls', '12')
    assert checked.returncode == 1, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)['status'] == 'FOUND'


@pytest.mark.parametrize('execution', ['Backtest([], LocalStrategy).run()', 'engine.run()',
                                       '@decorate()\nclass Extra(Strategy):\n    engine.run()'])
def test_recognized_unguarded_execution_blocks_even_review_ack(tmp_path, execution):
    project(tmp_path, NATIVE + '\n' + execution + '\n')
    result = initialize(tmp_path, '--review-imports', '--strategy-class', 'LocalStrategy')
    assert json.loads(result.stdout)['status'] == 'NEEDS_INPUT'
    checked = invoke(tmp_path, 'check', '--review-imports', '--json')
    assert checked.returncode == 2
    assert not (tmp_path / '.tradeoff').exists()


@pytest.mark.parametrize('labels,options,code', [
    (lambda i, stamp: stamp[:19], ['--timezone', 'UTC'], 'TIMEZONE_REQUIRED'),
    (lambda i, stamp: (date(2026, 1, 1) + timedelta(days=i)).isoformat(), ['--timezone', 'UTC', '--session-close', '16:00'], 'SESSION_CLOSE_REQUIRED'),
])
def test_clock_conventions_are_required_and_resolved_with_check_flags(tmp_path, labels, options, code):
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n', labels)
    result = initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    summary = json.loads(result.stdout)
    assert any(item['code'] == code for item in summary['issues'])
    checked = invoke(tmp_path, 'check', '--json', *options)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)['status'] == 'NO_DEPENDENCY_OBSERVED'


def test_check_resolves_manifest_paths_and_companion_imports_from_other_cwd(tmp_path):
    folder = tmp_path / 'project'
    folder.mkdir()
    (folder / 'helper.py').write_text('units = 2\n')
    (folder / 'companion.txt').write_text('2')
    source = ('from helper import units\n'
              'with open("companion.txt") as stream:\n    assert int(stream.read()) == units\n'
              'def positions(rows, config, seed):\n    return [units] * len(rows)\n')
    project(folder, source)
    initialized = initialize(folder, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    assert json.loads(initialized.stdout)['status'] == 'READY'
    checked = invoke(tmp_path, 'check', '--project', folder / 'tradeoff.json', '--output', 'chosen', '--json')
    assert checked.returncode == 0, checked.stdout + checked.stderr
    summary = json.loads(checked.stdout)
    assert Path(summary['report']) == folder / 'chosen' / 'report.json'
    assert (folder / 'chosen' / 'index.html').exists()
    assert not (tmp_path / 'chosen').exists()


def test_repeated_default_checks_choose_fresh_output(tmp_path):
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    first = invoke(tmp_path, 'check', '--json')
    second = invoke(tmp_path, 'check', '--json')
    assert first.returncode == second.returncode == 0, first.stdout + second.stdout
    assert json.loads(first.stdout)['report'] != json.loads(second.stdout)['report']
    assert Path(json.loads(first.stdout)['report']).exists()


def test_check_rejects_occupied_output_and_bad_data_before_import(tmp_path):
    project(tmp_path, 'from pathlib import Path\nPath("imported").touch()\n'
            'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    occupied = tmp_path / 'occupied'
    occupied.mkdir()
    (occupied / 'keep').write_text('mine')
    checked = invoke(tmp_path, 'check', '--output', occupied, '--json')
    assert checked.returncode == 2 and not (tmp_path / 'imported').exists()
    (tmp_path / 'bars.csv').write_text('bad data')
    checked = invoke(tmp_path, 'check', '--json')
    assert checked.returncode == 2 and not (tmp_path / 'imported').exists()


def test_changed_source_requires_review_again(tmp_path):
    source, _ = project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    source.write_text(source.read_text() + '\nraise RuntimeError("changed after review")\n')
    checked = invoke(tmp_path, 'check', '--json')
    assert checked.returncode == 2
    assert json.loads(checked.stdout)['error']['code'] == 'PROJECT_NEEDS_INPUT'


def test_manifest_and_direct_audit_have_identical_findings(tmp_path):
    pytest.importorskip('backtesting')
    project(tmp_path)
    initialized = initialize(tmp_path, '--review-imports')
    assert json.loads(initialized.stdout)['status'] == 'READY'
    checked = invoke(tmp_path, 'check', '--json', '--max-calls', '12')
    direct = invoke(tmp_path, 'audit', '--adapter', 'strategy:LocalStrategy', '--engine', 'backtesting',
                    '--data', 'bars.csv', '--output', 'direct', '--json', '--max-calls', '12')
    assert checked.returncode == direct.returncode == 1, checked.stdout + direct.stdout
    result = json.loads(Path(json.loads(checked.stdout)['report']).read_text())
    expected = json.loads((tmp_path / 'direct' / 'report.json').read_text())
    assert result['status'] == expected['status'] == 'FOUND'
    assert result['witness'] == expected['witness']
    assert json.loads(checked.stdout)['replay'].startswith('tradeoff reproduce ')


def test_check_restores_cwd_and_import_path(tmp_path, monkeypatch, capsys):
    from tradeoff.cli import main
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    cwd, path = Path.cwd(), sys.path[:]
    assert main(['check', '--project', str(tmp_path / 'tradeoff.json'), '--json']) == 0
    assert Path.cwd() == cwd and sys.path == path


def test_missing_native_engine_is_actionable_before_strategy_import(tmp_path, monkeypatch, capsys):
    import importlib.util
    from tradeoff.cli import main
    project(tmp_path)
    initialize(tmp_path, '--review-imports')
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None if name == 'backtesting' else real(name))
    assert main(['check', '--project', str(tmp_path / 'tradeoff.json'), '--json']) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary['error']['code'] == 'OPTIONAL_ENGINE_REQUIRED'
    assert 'tradeoff[audit] @ git+https://github.com/Toomi16011601/tradeoff.git' in summary['error']['message']


def test_aware_labels_still_require_open_or_close_declaration(tmp_path):
    project(tmp_path)
    result = invoke(tmp_path, 'init', '--strategy', 'strategy.py', '--data', 'bars.csv', '--review-imports', '--json')
    summary = json.loads(result.stdout)
    assert summary['status'] == 'NEEDS_INPUT'
    assert any(issue['code'] == 'TIMESTAMP_KIND_REQUIRED' for issue in summary['issues'])
    assert 'next_command' in summary


def test_check_persists_explicit_resolution_flags(tmp_path):
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n',
            lambda i, stamp: stamp[:19])
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets')
    checked = invoke(tmp_path, 'check', '--json', '--review-imports', '--timezone', 'UTC')
    assert checked.returncode == 0, checked.stdout + checked.stderr
    again = invoke(tmp_path, 'check', '--json')
    assert again.returncode == 0, again.stdout + again.stderr


def test_manifest_rejects_unknown_schema_and_types_before_import(tmp_path):
    project(tmp_path, 'raise RuntimeError("do not import")\n' + NATIVE)
    initialize(tmp_path, '--review-imports')
    manifest = tmp_path / 'tradeoff.json'
    content = json.loads(manifest.read_text())
    content['review'] = 'yes'
    manifest.write_text(json.dumps(content))
    result = invoke(tmp_path, 'check', '--json')
    assert result.returncode == 2
    assert json.loads(result.stdout)['error']['code'] == 'INVALID_PROJECT'


def test_multiple_in_process_checks_do_not_reuse_other_projects_modules(tmp_path, capsys):
    from tradeoff.cli import main
    for name, expression, expected in [('first', '[0] * len(rows)', 0),
                                       ('second', '[int(rows[-1]["close"] > 110)] * len(rows)', 1)]:
        folder = tmp_path / name
        folder.mkdir()
        project(folder, 'def positions(rows, config, seed):\n    return ' + expression + '\n')
        result = initialize(folder, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
        assert result.returncode == 0
        assert main(['check', '--project', str(folder / 'tradeoff.json'), '--json']) == expected
    assert 'strategy' not in sys.modules


def test_numeric_engine_and_audit_flags_work_without_editing_manifest(tmp_path):
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    result = initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets',
                        '--review-imports', '--initial-cash', '5000.5')
    assert json.loads(result.stdout)['status'] == 'READY'
    checked = invoke(tmp_path, 'check', '--json', '--initial-cash', '3000.25')
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_main_guard_calls_and_alias_native_strategy_discovery(tmp_path):
    project(tmp_path, NATIVE.replace('import Strategy', 'import Strategy as Base').replace('(Strategy)', '(Base)') +
            '\nif __name__ == "__main__":\n    Backtest([], LocalStrategy).run()\n')
    result = initialize(tmp_path, '--review-imports')
    assert json.loads(result.stdout)['status'] == 'READY'


def test_legacy_project_alias_has_same_api():
    import tradeoff.project
    import backtest_witness.project
    assert backtest_witness.project.add_project_commands is tradeoff.project.add_project_commands


def test_recognized_execution_in_eager_annotation_is_blocked(tmp_path):
    project(tmp_path, NATIVE + '\ndef helper(value: engine.run()):\n    pass\n')
    result = initialize(tmp_path, '--review-imports')
    assert json.loads(result.stdout)['status'] == 'NEEDS_INPUT'
    assert any(issue['code'] == 'IMPORT_TIME_EXECUTION' for issue in json.loads(result.stdout)['issues'])


def test_new_strategy_path_requires_new_import_review(tmp_path):
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    (tmp_path / 'different.py').write_text((tmp_path / 'strategy.py').read_text())
    checked = invoke(tmp_path, 'check', '--strategy', 'different.py', '--adapter', 'different:positions', '--json')
    assert checked.returncode == 2
    assert json.loads(checked.stdout)['error']['code'] == 'PROJECT_NEEDS_INPUT'


def test_diagnostics_cannot_be_written_inside_manifest_relative_output(tmp_path):
    folder = tmp_path / 'project'
    folder.mkdir()
    project(folder, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(folder, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    (folder / 'chosen').mkdir()
    checked = invoke(tmp_path, 'check', '--project', folder / 'tradeoff.json', '--output', 'chosen',
                     '--diagnostics', folder / 'chosen' / 'private.txt', '--json')
    assert checked.returncode == 2
    assert json.loads(checked.stdout)['error']['code'] == 'DIAGNOSTICS_LOCATION'


def test_manifest_relative_symlink_output_is_rejected_before_import(tmp_path):
    project(tmp_path, 'from pathlib import Path\nPath("imported").touch()\n'
            'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    target = tmp_path / 'target'
    target.mkdir()
    (tmp_path / 'link').symlink_to(target, target_is_directory=True)
    result = invoke(tmp_path, 'check', '--output', 'link', '--json')
    assert result.returncode == 2
    assert not (tmp_path / 'imported').exists()
    assert list(target.iterdir()) == []


def test_changing_source_cannot_silently_keep_previous_callback(tmp_path):
    project(tmp_path, 'def positions(rows, config, seed):\n    return [0] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    (tmp_path / 'new.py').write_text('def positions(rows, config, seed):\n'
                                   '    return [int(rows[-1]["close"] > 110)] * len(rows)\n')
    changed = invoke(tmp_path, 'check', '--strategy', 'new.py', '--review-imports', '--json')
    assert changed.returncode == 2, changed.stdout + changed.stderr
    assert json.loads(changed.stdout)['error']['code'] == 'PROJECT_NEEDS_INPUT'
    assert not (tmp_path / '.tradeoff').exists()
    selected = invoke(tmp_path, 'check', '--strategy', 'new.py', '--adapter', 'new:positions',
                      '--engine', 'targets', '--review-imports', '--json')
    assert selected.returncode == 1, selected.stdout + selected.stderr
    assert json.loads(selected.stdout)['status'] == 'FOUND'
    saved = json.loads((tmp_path / 'tradeoff.json').read_text())
    assert saved['strategy'] == 'new.py' and saved['adapter'] == 'new:positions'


def test_changing_source_discovers_new_native_class(tmp_path):
    pytest.importorskip('backtesting')
    causal = NATIVE.replace('self.leaked = self.data.Close[-1] > 110', 'self.leaked = False')
    project(tmp_path, causal)
    initialize(tmp_path, '--review-imports')
    (tmp_path / 'new.py').write_text(NATIVE.replace('LocalStrategy', 'NewStrategy'))
    changed = invoke(tmp_path, 'check', '--strategy', 'new.py', '--review-imports', '--json')
    assert changed.returncode == 1, changed.stdout + changed.stderr
    assert json.loads(changed.stdout)['status'] == 'FOUND'
    saved = json.loads((tmp_path / 'tradeoff.json').read_text())
    assert saved['adapter'] == 'new:NewStrategy'


@pytest.mark.parametrize('module', ['strategy', 'helper', 'signals.helper', 'lazy_helper'])
def test_check_executes_current_source_even_with_matching_stale_bytecode(tmp_path, module):
    import py_compile
    if module == 'strategy':
        source, _ = project(tmp_path, 'def positions(rows, config, seed):\n'
                            '    return [0 * int(rows[-1]["close"] > 110)] * len(rows)\n')
    else:
        if module == 'lazy_helper':
            project(tmp_path, 'def positions(rows, config, seed):\n'
                    '    from lazy_helper import positions as helper\n'
                    '    return helper(rows, config, seed)\n')
        else:
            project(tmp_path, f'from {module} import positions\n')
        source = tmp_path.joinpath(*module.split('.')).with_suffix('.py')
        source.parent.mkdir(exist_ok=True)
        if '.' in module:
            (source.parent / '__init__.py').write_text('')
        source.write_text('def positions(rows, config, seed):\n'
                          '    return [0 * int(rows[-1]["close"] > 110)] * len(rows)\n')
    initialize(tmp_path, '--adapter', 'strategy:positions', '--engine', 'targets', '--review-imports')
    py_compile.compile(str(source), doraise=True)
    stat = source.stat()
    source.write_text(source.read_text().replace('0 * int', '1 * int'))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    direct = invoke(tmp_path, 'audit', '--adapter', 'strategy:positions', '--engine', 'targets',
                    '--data', 'bars.csv', '--output', 'direct', '--json')
    assert direct.returncode == 1, direct.stdout + direct.stderr
    assert json.loads(direct.stdout)['status'] == 'FOUND'
    checked = invoke(tmp_path, 'check', '--review-imports', '--json')
    assert checked.returncode == 1, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)['status'] == 'FOUND'

    summary = json.loads(checked.stdout)
    fixture = Path(summary['report']).with_name('reproducer.json')
    replayed = invoke(tmp_path, 'reproduce', fixture)
    assert replayed.returncode == 1, replayed.stdout + replayed.stderr
    assert 'DEPENDENCY REPRODUCED' in replayed.stdout
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    exported_test = fixture.with_name('test_future_invariance.py')
    regression = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--tb=short', str(exported_test)],
                                cwd=tmp_path, env=env, capture_output=True, text=True)
    assert regression.returncode == 1, regression.stdout + regression.stderr
    assert 'InvarianceError' in regression.stdout
    # A real repair must win even over a matching stale leaky cache.
    py_compile.compile(str(source), doraise=True)
    source.write_text(source.read_text().replace('1 * int', '0 * int'))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    fixed = invoke(tmp_path, 'reproduce', fixture)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    regression = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--tb=short', str(exported_test)],
                                cwd=tmp_path, env=env, capture_output=True, text=True)
    assert regression.returncode == 0, regression.stdout + regression.stderr
