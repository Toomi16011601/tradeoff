"""Scoped current-source imports for local project strategies and their helpers.

This executes project code with normal import hooks; it is not an import sandbox.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
from importlib.machinery import PathFinder, SourceFileLoader
import os
from pathlib import Path
import sys

_ACTIVE = ContextVar('tradeoff_project_sources', default={})
_PROTECTED = {'tradeoff', 'backtest_witness'}


def _local_source(root, filename):
    if not filename:
        return False
    source = Path(filename).resolve()
    return root in source.parents and not {'site-packages', 'dist-packages'} & set(source.parts)


class _ProjectSourceLoader(SourceFileLoader):
    def __init__(self, fullname, path, reviewed_source, reviewed_digest):
        super().__init__(fullname, path)
        self.reviewed_source = reviewed_source
        self.reviewed_digest = reviewed_digest

    def get_code(self, fullname):
        source = self.get_data(self.path)
        if Path(self.path).resolve() == self.reviewed_source and (
                hashlib.sha256(source).hexdigest() != self.reviewed_digest):
            exc = ValueError('Strategy source changed after review; rerun check')
            exc.code = 'PROJECT_CHANGED'
            raise exc
        return self.source_to_code(source, self.path)


class _ProjectSourceFinder:
    def __init__(self, root, reviewed_source, reviewed_digest):
        self.root = root
        self.reviewed_source = reviewed_source
        self.reviewed_digest = reviewed_digest

    def find_spec(self, fullname, path=None, target=None):
        spec = PathFinder.find_spec(fullname, path, target)
        if (fullname.split('.')[0] not in _PROTECTED and spec is not None
                and isinstance(spec.loader, SourceFileLoader)
                and (_local_source(self.root, spec.origin) or (spec.origin and Path(spec.origin).resolve() == self.reviewed_source))):
            spec.loader = _ProjectSourceLoader(fullname, spec.origin,
                                               self.reviewed_source, self.reviewed_digest)
        return spec


@contextmanager
def current_project_source(root=None, reviewed_source=None, reviewed_digest=None, *, modules=None):
    """Compile local source, preserve package/hooks semantics, then restore imports.

    A runner can retain its own module objects across calls through ``modules``;
    resolving a new runner always reads current source. Nested checks share their
    existing review guard and module scope.
    """
    root = Path(root or Path.cwd()).resolve()
    active = _ACTIVE.get()
    if root in active:
        yield active[root]
        return
    retained = {} if modules is None else modules
    cwd, paths, finders = Path.cwd(), sys.path[:], sys.meta_path[:]
    local_names = {item.stem for item in root.iterdir() if item.suffix == '.py'}
    for item in root.iterdir():
        if item.name.isidentifier():
            try:
                if item.is_dir():
                    local_names.add(item.name)
            except OSError:
                # Unrelated protected/disappearing entries are not import candidates.
                continue
    local_names -= _PROTECTED

    def local(name, module):
        return name.split('.')[0] not in _PROTECTED and (
            name.split('.')[0] in local_names or _local_source(root, getattr(module, '__file__', None)))

    displaced = {name: module for name, module in list(sys.modules.items()) if local(name, module)}
    for name in displaced:
        del sys.modules[name]
    token = _ACTIVE.set({**active, root: retained})
    try:
        os.chdir(root)
        sys.path.insert(0, str(root))
        sys.modules.update(retained)
        # Earlier custom finders retain priority over normal filesystem imports.
        position = next((index for index, item in enumerate(sys.meta_path) if item is PathFinder), 0)
        sys.meta_path.insert(position, _ProjectSourceFinder(root, reviewed_source, reviewed_digest))
        yield retained
    finally:
        for name, module in list(sys.modules.items()):
            if local(name, module):
                retained[name] = module
                sys.modules.pop(name, None)
        sys.modules.update(displaced)
        os.chdir(cwd)
        sys.path[:] = paths
        sys.meta_path[:] = finders
        _ACTIVE.reset(token)


def current_source_runner(factory):
    """Resolve fresh code and keep its import scope for lazy callback helpers."""
    @wraps(factory)
    def resolve(*args, **kwargs):
        root = Path.cwd()
        with current_project_source(root) as modules:
            runner = factory(*args, **kwargs)

        @wraps(runner)
        def run(*args, **kwargs):
            with current_project_source(root, modules=modules):
                return runner(*args, **kwargs)
        return run
    return resolve
