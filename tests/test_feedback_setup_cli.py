"""Safe new-user command output and actionable statuses."""
import json
from importlib.util import find_spec

import pytest


def test_connect_bad_python_prints_actionable_safe_json(tmp_path, capsys):
    from tradeoff.cli import main
    assert main(['connect', '--project', str(tmp_path), '--python', str(tmp_path / 'missing'), '--json']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'SETUP_BLOCKED'
    assert 'environment' in result['next_step']


def test_doctor_missing_project_has_nonzero_status(tmp_path, capsys):
    from tradeoff.cli import main
    assert main(['doctor', '--project', str(tmp_path), '--json']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'SETUP_REQUIRED'
    assert not (tmp_path / '.tradeoff').exists()


@pytest.mark.parametrize('command', ['connect', 'doctor'])
def test_invalid_arguments_are_never_echoed(command, capsys):
    from tradeoff.cli import main
    assert main([command, '--api-key', 'SYNTHETIC_SECRET_SENTINEL']) == 2
    output = capsys.readouterr()
    assert 'SYNTHETIC_SECRET_SENTINEL' not in output.out + output.err
    assert json.loads(output.out)['status'] == 'ERROR'


@pytest.mark.skipif(find_spec('mcp') is None, reason='Optional MCP SDK not installed')
def test_setup_human_output_points_to_prompt_and_does_not_claim_agent_connected(tmp_path, capsys):
    from tradeoff.cli import main
    assert main(['connect', '--project', str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert 'AGENT_SETUP.md' in output
    assert 'NOT_VERIFIED' in output
    assert main(['doctor', '--project', str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert 'NO_DECISIONS' in output and 'next' in output.lower()
