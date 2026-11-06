"""New-user commands collect evidence without constructing mark JSON."""
import json

from feedback_helpers import AFTER_HORIZON, decision, feedback_project


def test_cli_configures_collects_and_opens_an_offline_report(feedback_project,capsys):
    from tradeoff.cli import main
    from tradeoff.feedback.recorder import Recorder
    Recorder(feedback_project).record_decision(decision(),event_id='d1')
    (feedback_project/'prices.csv').write_text('time,close,received\n2026-01-05T15:30:00Z,12,2026-01-05T15:30:01Z\n')
    assert main(['feedback','price-source','--project',str(feedback_project),'--data','prices.csv',
        '--symbol','SYNTH','--currency','USD','--source','fixture','--feed','fixture-feed','--price-kind','mid',
        '--timestamp-column','time','--price-column','close','--available-at-column','received','--json'])==0
    assert json.loads(capsys.readouterr().out)['status']=='SOURCE_CONFIGURED'
    assert main(['feedback','collect','--project',str(feedback_project),'--as-of',AFTER_HORIZON,'--output','feedback-output'])==0
    output=capsys.readouterr().out
    assert '1 available' in output
    assert 'index.html' in output
    assert (feedback_project/'feedback-output/index.html').is_file()
    assert main(['feedback','collect','--project',str(feedback_project),'--as-of',AFTER_HORIZON,'--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['collection']['new_marks']==0
    assert result['feedback']['evaluation']['decisions'][0]['outcome_status']=='AVAILABLE'


def test_cli_missing_source_is_actionable_and_private(feedback_project,capsys):
    from tradeoff.cli import main
    assert main(['feedback','collect','--project',str(feedback_project),'--json'])==2
    output=capsys.readouterr().out
    assert 'PRICE_SOURCE_NOT_CONFIGURED' in output
    assert str(feedback_project) not in output
