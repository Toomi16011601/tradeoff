import json
import os
import subprocess
import sys

from feedback_helpers import ROOT, AFTER_HORIZON, decision, feedback_project, fixed_clock


def invoke_feedback(project, *args, input=None):
    return subprocess.run([sys.executable, "-m", "tradeoff", "feedback", *args, "--project", str(project)],
        cwd=project, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, input=input)


def test_cli_and_python_evaluate_same_snapshot(feedback_project):
    from tradeoff.feedback.api import FeedbackApp
    expected = FeedbackApp(feedback_project, clock=fixed_clock).evaluate_decisions({"as_of": AFTER_HORIZON})
    result = invoke_feedback(feedback_project, "evaluate", "--as-of", AFTER_HORIZON, "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


def test_new_workspace_setup_record_and_repeat(tmp_path):
    initialized = invoke_feedback(tmp_path, "init", "--json")
    assert initialized.returncode == 0, initialized.stderr
    payload = json.dumps({"event_id": "d1", "decision": decision()})
    first = invoke_feedback(tmp_path, "record", "--input", "-", "--json", input=payload)
    repeat = invoke_feedback(tmp_path, "record", "--input", "-", "--json", input=payload)
    assert first.returncode == repeat.returncode == 0
    assert json.loads(first.stdout) == json.loads(repeat.stdout)


def test_bad_json_and_parser_values_do_not_echo_input(feedback_project):
    result = invoke_feedback(feedback_project, "record", "--input", "-", "--json", input='{"api_key":"SYNTHETIC_SECRET",}')
    assert result.returncode == 2
    assert "SYNTHETIC_SECRET" not in result.stdout + result.stderr


def test_duplicate_value_flags_are_rejected(feedback_project):
    result = invoke_feedback(feedback_project, "evaluate", "--as-of", AFTER_HORIZON,
        "--as-of", "2026-01-05T15:00:00Z", "--json")
    assert result.returncode == 2
    result = invoke_feedback(feedback_project, "evaluate", "--as-of", "SYNTHETIC_SECRET", "--json")
    assert result.returncode == 2
    assert "SYNTHETIC_SECRET" not in result.stdout + result.stderr


def test_parser_failure_is_private_even_without_json_flag(feedback_project):
    result = invoke_feedback(feedback_project, "evaluate", "--api-key", "SYNTHETIC_SECRET_SENTINEL")
    assert result.returncode == 2
    assert "SYNTHETIC_SECRET_SENTINEL" not in result.stdout + result.stderr
