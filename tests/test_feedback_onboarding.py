"""Local setup from real installed environments, without an agent or broker."""
import json
from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys

import pytest

from feedback_helpers import ROOT

requires_mcp = pytest.mark.skipif(find_spec('mcp') is None, reason='Optional MCP SDK not installed')


def _connect(project, **kwargs):
    from tradeoff.feedback.onboarding import connect
    return connect(project, **kwargs)


def _files(project):
    return {str(p.relative_to(project)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in Path(project).rglob('*') if p.is_file()}


@requires_mcp
def test_setup_generates_private_configuration_and_never_seeds_real_evidence(tmp_path):
    project = tmp_path / 'agent workspace with spaces'
    project.mkdir()
    source = project / 'agent.py'
    source.write_text("raise RuntimeError('must never import me')\n")
    result = _connect(project)
    assert result['status'] == 'SETUP_READY'
    assert result['agent_hook'] == 'NOT_VERIFIED'
    assert result['self_test']['status'] == 'PASS'
    assert result['self_test']['tools'] == 10
    bundle = project / '.tradeoff/feedback/connection'
    config = json.loads((bundle / 'mcp.json').read_text())['mcpServers']['tradeoff']
    assert config['command'] == sys.executable
    assert config['args'] == ['-I', '-m', 'tradeoff', 'feedback', 'mcp', '--project', str(project)]
    prompt = (bundle / 'AGENT_SETUP.md').read_text()
    assert 'BEFORE' in prompt and 'fake' in prompt.lower()
    assert '[mcp_servers.tradeoff]' in (bundle / 'codex.toml').read_text()
    assert (project / '.tradeoff/feedback/.gitignore').read_text() == '*\n'
    if sys.platform != 'win32':
        assert bundle.stat().st_mode & 0o077 == 0
        assert (bundle / 'mcp.json').stat().st_mode & 0o077 == 0
    from tradeoff.feedback.store import FeedbackStore
    with FeedbackStore(project, readonly=True) as store:
        assert store.snapshot()['events'] == []
    before = _files(project)
    assert _connect(project)['status'] == 'SETUP_READY'
    assert _files(project) == before
    assert source.read_text().startswith('raise RuntimeError')


@requires_mcp
def test_edited_config_and_extra_files_are_preserved(tmp_path):
    _connect(tmp_path)
    folder = tmp_path / '.tradeoff/feedback/connection'
    (folder / 'mcp.json').write_text('user edits must survive')
    (folder / 'custom.txt').write_text('custom')
    before = _files(tmp_path)
    from tradeoff.feedback.contracts import FeedbackError
    with pytest.raises(FeedbackError) as caught:
        _connect(tmp_path)
    assert caught.value.code == 'CONNECTION_CONFLICT'
    assert _files(tmp_path) == before
    from tradeoff.feedback.diagnostics import diagnose
    result = diagnose(tmp_path)
    assert next(c for c in result['checks'] if c['id'] == 'connection')['status'] == 'FAIL'
    assert _files(tmp_path) == before


def test_bad_interpreter_is_safe_and_does_not_create_project(tmp_path):
    result = _connect(tmp_path, python=tmp_path / 'missing-python-SYNTHETIC_SECRET_SENTINEL')
    assert result['status'] == 'SETUP_BLOCKED'
    assert result['self_test']['status'] == 'FAIL'
    assert 'SYNTHETIC_SECRET_SENTINEL' not in json.dumps(result)
    assert not (tmp_path / '.tradeoff').exists()


@requires_mcp
def test_environment_conflict_does_not_change_evidence(tmp_path):
    _connect(tmp_path, environment='simulated')
    before = _files(tmp_path)
    from tradeoff.feedback.contracts import FeedbackError
    with pytest.raises(FeedbackError) as caught:
        _connect(tmp_path, environment='paper')
    assert caught.value.code == 'ENVIRONMENT_CONFLICT'
    assert _files(tmp_path) == before


@requires_mcp
def test_doctor_checks_generated_config_without_writing_target(tmp_path):
    _connect(tmp_path)
    before = _files(tmp_path)
    from tradeoff.feedback.diagnostics import diagnose
    result = diagnose(tmp_path)
    checks = {c['id']: c for c in result['checks']}
    assert checks['connection']['status'] == checks['interpreter']['status'] == 'PASS'
    assert result['agent_hook'] == 'NOT_VERIFIED'
    assert result['evidence_status'] == 'NO_DECISIONS'
    assert _files(tmp_path) == before


def test_core_probe_reports_missing_sdk_from_clean_venv(tmp_path):
    import venv
    env = tmp_path / 'core-only'
    venv.EnvBuilder(with_pip=False, symlinks=sys.platform != 'win32').create(env)
    executable = env / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    # Install a .pth exactly as an editable core installation; no optional SDK.
    query = subprocess.check_output([str(executable), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True)
    Path(query.strip(), 'tradeoff-test.pth').write_text(str(ROOT / 'src') + '\n')
    project = tmp_path / 'new-workspace'
    project.mkdir()
    result = _connect(project, python=executable)
    assert result['status'] == 'SETUP_BLOCKED'
    assert result['self_test']['code'] == 'MCP_NOT_INSTALLED'
    assert not (project / '.tradeoff').exists()


@requires_mcp
def test_setup_refuses_symlink_target(tmp_path):
    project = tmp_path / 'real'
    project.mkdir()
    linked = tmp_path / 'linked'
    linked.symlink_to(project, target_is_directory=True)
    from tradeoff.feedback.contracts import FeedbackError
    with pytest.raises(FeedbackError) as caught:
        _connect(linked)
    assert caught.value.code == 'UNSAFE_PATH'
    assert not (project / '.tradeoff').exists()


@requires_mcp
def test_generated_config_reaches_the_selected_workspace(tmp_path):
    import asyncio
    _connect(tmp_path)
    from mcp import Client, StdioServerParameters
    config = json.loads((tmp_path / '.tradeoff/feedback/connection/mcp.json').read_text())['mcpServers']['tradeoff']
    async def check():
        async with Client(StdioServerParameters(**config)) as client:
            result = await client.call_tool('tradeoff_evaluate_decisions', {'as_of': '2026-01-05T16:00:00Z'})
            assert not result.is_error
            assert result.structured_content['quality']['decision_count'] == 0
    asyncio.run(check())


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX executable fixture')
def test_probe_timeout_cleans_up_its_own_process_group(tmp_path):
    from tradeoff.feedback.onboarding import probe
    program = tmp_path / 'slow-python'
    program.write_text('#!/bin/sh\nsleep 30\n')
    program.chmod(0o700)
    result = probe(program, timeout=0.1)
    assert result == {'status': 'FAIL', 'code': 'PROBE_TIMEOUT'}


@requires_mcp
def test_venv_path_is_preserved_when_replacing_managed_configuration(tmp_path):
    # A new environment can replace an unchanged managed configuration.
    _connect(tmp_path)
    before = (tmp_path / '.tradeoff/feedback/events.sqlite3').read_bytes()
    import sysconfig
    import venv
    tool_env = tmp_path / 'tool environment'
    venv.EnvBuilder(with_pip=False, symlinks=sys.platform != 'win32').create(tool_env)
    executable = tool_env / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    query = subprocess.check_output([str(executable), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True)
    Path(query.strip(), 'tradeoff-test.pth').write_text(str(ROOT / 'src') + '\n' + sysconfig.get_path('purelib') + '\n')
    _connect(tmp_path, python=executable)
    config = json.loads((tmp_path / '.tradeoff/feedback/connection/mcp.json').read_text())['mcpServers']['tradeoff']
    assert config['command'] == str(executable)
    assert (tmp_path / '.tradeoff/feedback/events.sqlite3').read_bytes() == before


@requires_mcp
def test_edited_manifest_is_preserved_instead_of_regenerated(tmp_path):
    _connect(tmp_path)
    manifest = tmp_path / '.tradeoff/feedback/connection/connection.json'
    content = json.loads(manifest.read_text())
    content['user_note'] = 'preserve my connection metadata'
    manifest.write_text(json.dumps(content))
    before = _files(tmp_path)
    from tradeoff.feedback.contracts import FeedbackError
    with pytest.raises(FeedbackError) as caught:
        _connect(tmp_path)
    assert caught.value.code == 'CONNECTION_CONFLICT'
    assert _files(tmp_path) == before
