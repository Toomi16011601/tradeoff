"""Private opt-in tracebacks must not weaken portable-report privacy."""
from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from backtest_witness.failure_lab import run_failure_lab
from backtest_witness.privacy import ExecutionUnavailable, callback_error
from test_failure_lab import bars


def test_callback_failure_records_cause_only_in_private_diagnostics(tmp_path, capsys):
    # Losing the callback_error hook would leave the nested missing-column cause hidden.
    from backtest_witness.diagnostics import local_diagnostics

    destination = tmp_path / "private.txt"
    def broken(*args):
        private_local = "SYNTHETIC_LOCAL_NOT_IN_EXCEPTION"
        try:
            raise KeyError("SYNTHETIC_PRIVATE_DIAGNOSTIC_COLUMN")
        except KeyError as exc:
            raise ExecutionUnavailable("strategy execution failed") from exc

    with local_diagnostics(destination):
        report = run_failure_lab(broken, bars())

    text = destination.read_text()
    assert "KeyError" in text
    assert "SYNTHETIC_PRIVATE_DIAGNOSTIC_COLUMN" in text
    assert "ExecutionUnavailable" in text
    assert "direct cause" in text
    assert "SYNTHETIC_LOCAL_NOT_IN_EXCEPTION" not in text
    assert "SYNTHETIC_PRIVATE_DIAGNOSTIC_COLUMN" not in str(report)
    assert capsys.readouterr() == ("", "")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_diagnostics_refuses_existing_files_without_touching_them(tmp_path):
    # Removing O_EXCL would overwrite a private file and make this test fail.
    from backtest_witness.diagnostics import DiagnosticsError, local_diagnostics

    destination = tmp_path / "private.txt"
    destination.write_text("keep this existing content")
    with pytest.raises(DiagnosticsError):
        with local_diagnostics(destination):
            pytest.fail("an occupied destination must be rejected before the body")
    assert destination.read_text() == "keep this existing content"


@pytest.mark.parametrize("dangling", [False, True])
def test_diagnostics_refuses_final_symlink_without_following_it(tmp_path, dangling):
    # Following a symlink could disclose raw diagnostics into an unintended file.
    from backtest_witness.diagnostics import DiagnosticsError, local_diagnostics

    target = tmp_path / "target.txt"
    if not dangling:
        target.write_text("keep target")
    destination = tmp_path / "private.txt"
    destination.symlink_to(target)
    with pytest.raises(DiagnosticsError):
        with local_diagnostics(destination):
            pytest.fail("a symlink destination must not be followed")
    assert destination.is_symlink()
    assert not target.exists() if dangling else target.read_text() == "keep target"


def test_context_restores_prior_recorder_and_does_not_capture_other_threads(tmp_path):
    # A global sink or failure to reset ContextVar would misroute private failures.
    from backtest_witness.diagnostics import local_diagnostics, record_exception

    outer = tmp_path / "outer.txt"
    inner = tmp_path / "inner.txt"
    record_exception(RuntimeError("SYNTHETIC_NO_ACTIVE_CONTEXT"))
    with local_diagnostics(outer):
        record_exception(RuntimeError("SYNTHETIC_OUTER_FIRST"))
        with local_diagnostics(inner):
            record_exception(RuntimeError("SYNTHETIC_INNER_ONLY"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(record_exception, RuntimeError("SYNTHETIC_OTHER_THREAD")).result()
        record_exception(RuntimeError("SYNTHETIC_OUTER_LAST"))
    record_exception(RuntimeError("SYNTHETIC_AFTER_EXIT"))

    outer_text, inner_text = outer.read_text(), inner.read_text()
    assert "SYNTHETIC_OUTER_FIRST" in outer_text
    assert "SYNTHETIC_OUTER_LAST" in outer_text
    assert "SYNTHETIC_INNER_ONLY" not in outer_text
    assert "SYNTHETIC_INNER_ONLY" in inner_text
    assert "SYNTHETIC_OUTER" not in inner_text
    for value in ("SYNTHETIC_NO_ACTIVE_CONTEXT", "SYNTHETIC_OTHER_THREAD", "SYNTHETIC_AFTER_EXIT"):
        assert value not in outer_text + inner_text


def test_escaping_exception_is_recorded_once_and_not_suppressed(tmp_path):
    # CLI callers can catch/record explicitly; escaping must retain original behavior.
    from backtest_witness.diagnostics import local_diagnostics, record_exception

    destination = tmp_path / "private.txt"
    with pytest.raises(RuntimeError, match="SYNTHETIC_ESCAPING_FAILURE"):
        with local_diagnostics(destination):
            try:
                raise RuntimeError("SYNTHETIC_ESCAPING_FAILURE")
            except RuntimeError as exc:
                record_exception(exc)
                raise
    assert destination.read_text().count("RuntimeError: SYNTHETIC_ESCAPING_FAILURE") == 1


def test_success_creates_private_explanatory_file_without_exception(tmp_path):
    from backtest_witness.diagnostics import local_diagnostics

    destination = tmp_path / "private.txt"
    with local_diagnostics(destination):
        pass
    assert destination.is_file()
    assert "No exceptions recorded" in destination.read_text()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_partial_write_failure_removes_diagnostics_and_resets_context(tmp_path, monkeypatch):
    # A write failure must not strand a partial file containing raw exception values.
    from backtest_witness.diagnostics import DiagnosticsError, local_diagnostics, record_exception

    destination = tmp_path / "private.txt"
    real_write = os.write
    first_write = True
    def partial_then_fail(fd, data):
        nonlocal first_write
        if first_write:
            first_write = False
            return real_write(fd, data[:20])
        raise OSError("SYNTHETIC_PRIVATE_WRITE_ERROR")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", partial_then_fail)
        with pytest.raises(DiagnosticsError) as raised:
            with local_diagnostics(destination):
                record_exception(ValueError("SYNTHETIC_PRIVATE_EXCEPTION"))
    assert not destination.exists()
    assert "SYNTHETIC_PRIVATE" not in str(raised.value)
    record_exception(RuntimeError("SYNTHETIC_AFTER_FAILED_WRITE"))
    second = tmp_path / "second.txt"
    with local_diagnostics(second):
        pass
    assert "SYNTHETIC_AFTER_FAILED_WRITE" not in second.read_text()


def test_unopted_callback_error_stays_portable_and_does_not_create_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    public = callback_error(RuntimeError("SYNTHETIC_PRIVATE_UNOPTED_MESSAGE"))
    assert "RuntimeError" in public
    assert "SYNTHETIC_PRIVATE_UNOPTED_MESSAGE" not in public
    assert list(tmp_path.iterdir()) == []


def test_non_utf8_exception_text_is_saved_without_losing_diagnostics(tmp_path):
    # Filesystem paths can contain surrogate escapes; a diagnostic must remain readable.
    from backtest_witness.diagnostics import local_diagnostics, record_exception

    destination = tmp_path / "private.txt"
    with local_diagnostics(destination):
        record_exception(RuntimeError("SYNTHETIC_NON_UTF8_\udcff"))
    assert "SYNTHETIC_NON_UTF8_\\udcff" in destination.read_text()


def test_failed_write_clears_partial_text_even_when_unlink_is_unavailable(tmp_path, monkeypatch):
    # Directory permissions may change after open; truncation must precede cleanup.
    from pathlib import Path
    from backtest_witness.diagnostics import DiagnosticsError, local_diagnostics, record_exception

    destination = tmp_path / "private.txt"
    real_write = os.write
    written = False
    def partial_then_fail(fd, data):
        nonlocal written
        if not written:
            written = True
            return real_write(fd, data[:20])
        raise OSError("write unavailable")
    def cannot_unlink(path, *args, **kwargs):
        raise PermissionError("directory unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", partial_then_fail)
        patch.setattr(Path, "unlink", cannot_unlink)
        with pytest.raises(DiagnosticsError):
            with local_diagnostics(destination):
                record_exception(RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION"))
    assert destination.read_bytes() == b""


@pytest.mark.parametrize('command', ['reproduce', 'replay-failure'])
@pytest.mark.parametrize('diagnostics_folder', ['real-report', 'alias'])
def test_replay_fixture_symlink_cannot_route_private_diagnostics_into_artifacts(
        tmp_path, command, diagnostics_folder):
    # Resolving only the alias parent misses the real report; resolving only the
    # target parent drops the existing protection for the selected alias folder.
    import json
    from pathlib import Path
    import subprocess
    import sys
    from backtest_witness.audit import audit
    from backtest_witness.failure_reproduce import export_failure_reproducer
    from backtest_witness.reproduce import export_reproducer
    from test_audit import future_last
    from test_failure_lab import execution, scenario
    from test_validation import tape

    root = Path(__file__).resolve().parents[1]
    real_report = tmp_path / 'real-report'
    aliases = tmp_path / 'alias'
    aliases.mkdir()
    if command == 'replay-failure':
        report = run_failure_lab(execution, bars(), scenarios=[scenario(200)])
        export_failure_reproducer(report, real_report, 'local_callback:run')
        fixture = real_report / 'failure-fixture.json'
    else:
        report = audit(future_last, tape(), min_history=1)
        export_reproducer(report, real_report, 'local_callback:run')
        fixture = real_report / 'reproducer.json'
    assert json.loads(fixture.read_text())
    alias = aliases / 'fixture-link.json'
    alias.symlink_to(fixture)
    private = tmp_path / diagnostics_folder / 'private.txt'
    marker = tmp_path / 'callback-ran.txt'
    (tmp_path / 'local_callback.py').write_text('from pathlib import Path\n'
        'def run(*args):\n'
        '    Path("callback-ran.txt").write_text("callback ran")\n'
        '    raise RuntimeError("SYNTHETIC_PRIVATE_CALLBACK_DETAIL")\n')

    result = subprocess.run([sys.executable, '-m', 'backtest_witness', command,
        str(alias), '--diagnostics', str(private)], cwd=tmp_path,
        env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(root / 'src'), str(tmp_path)])},
        capture_output=True, text=True)

    assert result.returncode == 2
    assert 'outside' in result.stderr
    assert 'Traceback' not in result.stdout + result.stderr
    assert 'SYNTHETIC_PRIVATE_CALLBACK_DETAIL' not in result.stdout + result.stderr
    assert not private.exists()
    assert not marker.exists()
