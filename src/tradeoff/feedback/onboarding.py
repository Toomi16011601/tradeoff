"""Private connection bundles and isolated installed-environment self-tests."""
import hashlib
from contextlib import suppress
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import signal
import subprocess
import sys
import tempfile

from .contracts import FeedbackError, canonical_json, parse_json
from .store import FeedbackStore, _no_symlinks

CONNECTION = '.tradeoff/feedback/connection'
FILES = {'mcp.json', 'codex.toml', 'AGENT_SETUP.md'}
SCHEMA = 'tradeoff.connection.v1'
_CODES = {'MCP_NOT_INSTALLED', 'MCP_VERSION_MISMATCH', 'PROBE_FAILED', 'PROBE_TIMEOUT',
          'PYTHON_UNAVAILABLE', 'INSTALL_UNAVAILABLE', 'INSTALL_VERIFIED', 'SELF_TEST_VERIFIED'}


def _conflict():
    raise FeedbackError('CONNECTION_CONFLICT', 'Connection files were edited, moved or are incomplete; preserve them, move the connection folder aside, then rerun connect')


def _system_taskkill():
    """Resolve Windows cleanup through the system API, never PATH or cwd."""
    import ctypes
    from ctypes import wintypes
    lookup = ctypes.WinDLL('kernel32', use_last_error=True, winmode=0x800).GetSystemDirectoryW
    lookup.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    lookup.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    size = lookup(buffer, len(buffer))
    directory = PureWindowsPath(buffer.value)
    if not size or size >= len(buffer) or not directory.is_absolute():
        raise OSError('Cannot resolve the Windows system directory')
    return str(directory / 'taskkill.exe')


def probe(python, *, self_test=False, timeout=45):
    """Trust only the chosen installed interpreter, never the project's imports.

    Output/error logs live in an owned temporary folder and are discarded. No
    credentials, PYTHONPATH or project code are passed to the subprocess.
    """
    executable = Path(os.path.abspath(os.fspath(python)))  # Keep a venv symlink.
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return dict(status='FAIL', code='PYTHON_UNAVAILABLE')
    env = {k: v for k, v in os.environ.items() if k in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL', 'LC_CTYPE'}}
    args = [str(executable), '-I', '-m', 'tradeoff.feedback._setup_probe']
    if self_test:
        args.append('--self-test')
    with tempfile.TemporaryDirectory(prefix='tradeoff-probe-') as temporary:
        root = Path(temporary).resolve()
        try:
            with (root / 'result').open('wb') as output, (root / 'errors').open('wb') as errors:
                options = dict(start_new_session=True) if os.name == 'posix' else dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                with subprocess.Popen(args, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                      stdout=output, stderr=errors, **options) as process:
                    try:
                        process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        if os.name == 'posix':
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            # If tree cleanup is unavailable, still kill and reap
                            # the parent; never search a user's workspace for it.
                            with suppress(OSError, subprocess.SubprocessError):
                                subprocess.run([_system_taskkill(), '/PID', str(process.pid), '/T', '/F'],
                                               cwd=root, env=env, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, timeout=10)
                            process.kill()
                        process.wait()
                        return dict(status='FAIL', code='PROBE_TIMEOUT')
            with (root / 'result').open('rb') as stream:
                result = parse_json(stream.read(8193))
            code = result.get('code')
            if code not in _CODES or result.get('status') not in {'PASS', 'FAIL'}:
                raise ValueError('invalid probe')
            if process.returncode != 0 and result['status'] == 'PASS':
                raise ValueError('failed probe')
            safe = dict(status=result['status'], code=code)
            from .api import operation_definitions
            expected_tools = len(operation_definitions())
            if code == 'SELF_TEST_VERIFIED' and safe['status'] == 'PASS' and result.get('tools') == expected_tools:
                safe.update(tools=expected_tools, scope='Isolated synthetic Python and MCP test; real agent hook and broker not tested')
            elif self_test and safe['status'] == 'PASS':
                raise ValueError('self-test missing')
            return safe
        except (OSError, ValueError, subprocess.SubprocessError):
            return dict(status='FAIL', code='INSTALL_UNAVAILABLE')


def _contents(project, python):
    entry = dict(command=python, args=['-I', '-m', 'tradeoff', 'feedback', 'mcp', '--project', project])
    toml = '[mcp_servers.tradeoff]\ncommand = ' + json.dumps(python, ensure_ascii=False) + '\nargs = ' + json.dumps(entry['args'], ensure_ascii=False) + '\n'
    prompt = '''# Connect your trading agent

Setup checked the installed Python and MCP tools with isolated synthetic data.
It has NOT verified this project's real hook. No strategy files were imported.

## Register the local tool (once)

For a client that supports mcpServers JSON, merge the tradeoff entry from
mcp.json beside this file into that client's local MCP configuration. Preserve
other servers. Codex uses TOML: merge codex.toml into its trusted project
.codex/config.toml or existing local config, preserving other settings.
Restart/reload the client's MCP connection. No hosted server is required.
These files contain local paths: keep them private on this device.

## Paste this into your coding agent

Connect this project to the installed Tradeoff decision-feedback tool.
Inspect my existing decision callback and broker submission path. Use the
tradeoff.feedback.recorder.Recorder API or the registered local MCP tools.
Record explicit intent BEFORE submission, then bind the actual returned order
ID afterward. Record holds/skips too; use stable event IDs for retry safety.
Read schema_for("decision") from tradeoff.feedback.contracts for the contract;
for MCP use tradeoff_record_decision's input schema. Map real signed quantities,
agent versions, opportunity and episode IDs, timestamped inputs/reference and
an explicit outcome horizon. Ask about choices the code cannot establish.
Keep my trading behavior unchanged. Do not place/cancel orders, start my agent,
read credentials into files or upload data. Do not invent historical inventory,
timestamps, quantities or costs. Add and run a fake-broker integration test
proving record-before-submit and bind-after-return, including a retry. Show me
the integration diff and remaining evidence gaps. Run tradeoff doctor --project .
--json afterward. The self-test alone must never be called a connected agent.

## Next checks

Run `tradeoff doctor --project .` from this trading workspace after wiring.
Import actual normalized orders/fills/marks and applicable costs, or explicitly
configure read-only Alpaca paper sync. Capture initial inventory BEFORE future
episodes. Missing historical evidence stays unknown. Open a local report with
`tradeoff feedback report --project . --output feedback-output` and then open
`feedback-output/index.html` as a file. Setup never starts trading.
'''
    return {'mcp.json': json.dumps({'mcpServers': {'tradeoff': entry}}, indent=2, ensure_ascii=False) + '\n',
            'codex.toml': toml, 'AGENT_SETUP.md': prompt}


def read_connection(project, *, project_id=None):
    """Validate managed content before trusting or replacing it. No writes."""
    folder = Path(project) / CONNECTION
    _no_symlinks(folder)
    if not folder.exists():
        return None
    try:
        if not folder.is_dir() or {p.name for p in folder.iterdir()} != FILES | {'connection.json'}:
            _conflict()
        for path in folder.iterdir():
            _no_symlinks(path)
            if not path.is_file() or path.stat().st_size > 65536:
                _conflict()
        manifest = parse_json((folder / 'connection.json').read_bytes())
        if not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'project_id', 'project', 'python', 'files'}:
            _conflict()
        if manifest.get('schema_version') != SCHEMA or (project_id is not None and manifest.get('project_id') != project_id):
            _conflict()
        if not all(isinstance(manifest.get(k), str) and Path(manifest[k]).is_absolute() for k in ('python', 'project')):
            _conflict()
        contents = _contents(manifest['project'], manifest['python'])
        hashes = {name: hashlib.sha256(content.encode()).hexdigest() for name, content in contents.items()}
        if manifest.get('files') != hashes or any((folder / name).read_text(encoding='utf-8') != content for name, content in contents.items()):
            _conflict()
        return manifest
    except (OSError, ValueError, TypeError, KeyError):
        _conflict()


def _write_connection(store, executable):
    folder = store.project / CONNECTION
    previous = read_connection(store.project, project_id=store.metadata['project_id'])
    contents = _contents(str(store.project), executable)
    manifest = dict(schema_version=SCHEMA, project_id=store.metadata['project_id'],
                    project=str(store.project), python=executable,
                    files={name: hashlib.sha256(content.encode()).hexdigest() for name, content in contents.items()})
    if manifest == previous:
        return
    stage = Path(tempfile.mkdtemp(prefix='.connection-', dir=store.folder))
    backup = None
    try:
        for name, content in {**contents, 'connection.json': canonical_json(manifest) + '\n'}.items():
            path = stage / name
            path.write_text(content, encoding='utf-8')
            path.chmod(0o600)
        if previous is not None:
            backup = Path(tempfile.mkdtemp(prefix='.connection-old-', dir=store.folder))
            backup.rmdir()
            folder.rename(backup)
        try:
            stage.rename(folder)
        except Exception:
            if backup is not None:
                backup.rename(folder)
            raise
        if backup is not None:
            shutil.rmtree(backup)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def connect(project, *, python=None, environment=None):
    project = Path(project).absolute()
    _no_symlinks(project)
    _no_symlinks(project / CONNECTION)
    if not project.is_dir():
        raise FeedbackError('INVALID_PROJECT', 'Choose an existing trading workspace directory')
    # Validate an existing workspace before probing; never reset an environment.
    if (project / '.tradeoff/feedback').exists():
        with FeedbackStore(project, readonly=True, environment=environment) as store:
            store.snapshot()
            read_connection(project, project_id=store.metadata['project_id'])
    executable = os.path.abspath(os.fspath(python if python is not None else sys.executable))
    result = probe(executable, self_test=True)
    base = dict(schema_version='tradeoff.connect.v1', agent_hook='NOT_VERIFIED', self_test=result)
    if result['status'] != 'PASS':
        return dict(base, status='SETUP_BLOCKED', next_step="In the chosen Python environment run: python -m pip install 'tradeoff[mcp] @ git+https://github.com/Toomi16011601/tradeoff.git', then rerun connect; use --python for a separate tool environment.")
    with FeedbackStore(project, create=True, environment=environment) as store, store.transaction():
        store.verify_chain()
        _write_connection(store, executable)
    return dict(base, status='SETUP_READY', configuration=CONNECTION + '/mcp.json',
                codex_configuration=CONNECTION + '/codex.toml', instructions=CONNECTION + '/AGENT_SETUP.md',
                next_step='Register the generated MCP entry in your client, then give its AGENT_SETUP.md prompt to your coding agent. A real hook still needs wiring and a fake-broker test.')
