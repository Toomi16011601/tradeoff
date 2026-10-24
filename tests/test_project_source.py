"""Fresh runner imports retain local module state without leaking import state."""
from importlib.abc import MetaPathFinder, Loader
from importlib.util import spec_from_loader
from pathlib import Path
import sys
from types import ModuleType

import pytest


def test_runner_preserves_custom_import_hook_and_cleans_scope_on_callback_error(tmp_path, monkeypatch):
    from tradeoff.adapters import resolve_runner
    from tradeoff.demos import synthetic_rows

    (tmp_path / 'strategy.py').write_text(
        'import hook_helper\n'
        'def positions(rows, config, seed):\n'
        '    import lazy_helper\n'
        '    assert hook_helper.value == 7\n'
        '    raise RuntimeError("callback failed")\n')
    (tmp_path / 'hook_helper.py').write_text('value = -1\n')
    (tmp_path / 'lazy_helper.py').write_text('value = 8\n')

    class Hook(MetaPathFinder, Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'hook_helper':
                return spec_from_loader(fullname, self)

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.value = 7

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'meta_path', [Hook(), *sys.meta_path])
    previous = ModuleType('strategy')
    monkeypatch.setitem(sys.modules, 'strategy', previous)
    before = Path.cwd(), sys.path[:], sys.meta_path[:]
    runner = resolve_runner('strategy:positions', engine='targets')
    assert sys.modules['strategy'] is previous
    for _ in range(2):
        with pytest.raises(RuntimeError, match='callback failed'):
            runner(synthetic_rows(4), {}, 7)
        assert (Path.cwd(), sys.path, sys.meta_path) == before
        assert sys.modules['strategy'] is previous
        assert 'lazy_helper' not in sys.modules and 'hook_helper' not in sys.modules


def test_failed_resolution_restores_modules_and_hooks(tmp_path, monkeypatch):
    from tradeoff.adapters import resolve_runner
    from tradeoff.demos import synthetic_rows
    (tmp_path / 'strategy.py').write_text('import companion\nraise RuntimeError("import failed")\n')
    (tmp_path / 'companion.py').write_text('value = 3\n')
    monkeypatch.chdir(tmp_path)
    previous = ModuleType('strategy')
    monkeypatch.setitem(sys.modules, 'strategy', previous)
    before = Path.cwd(), sys.path[:], sys.meta_path[:]
    with pytest.raises(RuntimeError, match='import failed'):
        resolve_runner('strategy:positions', engine='targets')
    assert (Path.cwd(), sys.path, sys.meta_path) == before
    assert sys.modules['strategy'] is previous
    assert 'companion' not in sys.modules


def test_runner_retains_its_own_module_state_and_relative_package_imports(tmp_path, monkeypatch):
    from tradeoff.adapters import resolve_runner
    from tradeoff.demos import synthetic_rows
    package = tmp_path / 'local_package'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'strategy.py').write_text(
        'from . import counter\n'
        'def positions(rows, config, seed):\n'
        '    from . import helper\n'
        '    counter.value += 1\n'
        '    return [counter.value + helper.value] * len(rows)\n')
    (package / 'counter.py').write_text('value = 0\n')
    (package / 'helper.py').write_text('value = 10\n')
    monkeypatch.chdir(tmp_path)
    runner = resolve_runner('local_package.strategy:positions', engine='targets')
    rows = synthetic_rows(4)
    assert runner(rows, {}, 7)[0]['target'] == 11
    assert runner(rows, {}, 7)[0]['target'] == 12
    assert not any(name.startswith('local_package') for name in sys.modules)
    other = resolve_runner('local_package.strategy:positions', engine='targets')
    assert other(rows, {}, 7)[0]['target'] == 11


@pytest.mark.parametrize('error', [PermissionError, OSError])
def test_unstatable_sibling_does_not_block_runner_or_hide_chosen_import_error(tmp_path, monkeypatch, error):
    from tradeoff.adapters import resolve_runner
    from tradeoff.demos import synthetic_rows
    source = tmp_path / 'strategy.py'
    source.write_text('def positions(rows, config, seed):\n    return [2] * len(rows)\n')
    sibling = tmp_path / 'protected_sibling'
    sibling.mkdir()
    real_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == sibling:
            raise error('unrelated sibling cannot be inspected')
        return real_stat(path, *args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, 'stat', stat)
    before = Path.cwd(), sys.path[:], sys.meta_path[:]
    runner = resolve_runner('strategy:positions', engine='targets')
    assert runner(synthetic_rows(4), {}, 7)[0]['target'] == 2
    source.write_text('raise PermissionError("chosen strategy import failed")\n')
    with pytest.raises(PermissionError, match='chosen strategy import failed'):
        resolve_runner('strategy:positions', engine='targets')
    assert (Path.cwd(), sys.path, sys.meta_path) == before
    assert 'strategy' not in sys.modules
