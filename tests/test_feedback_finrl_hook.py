"""Caller-owned intent mapping for the supported public FinRL simulation."""
from types import SimpleNamespace

import pytest

from feedback_helpers import decision, feedback_project

np = pytest.importorskip('numpy')


def env(cash=500,shares=3,**overrides):
    return SimpleNamespace(state=[cash,10,shares],stock_dim=1,hmax=100,buy_cost_pct=[0.01],
                           member_col=None,turbulence_threshold=None,day=0,
                           df=SimpleNamespace(index=SimpleNamespace(unique=lambda:[0,1])),**overrides)


@pytest.mark.parametrize('action,shares,quantity,label',[(0.8,3,'49','buy'),(-0.5,3,'-3','sell'),(-0.5,0,'0','hold')])
def test_policy_proposals_become_executable_intents(action,shares,quantity,label,feedback_project):
    from examples.decision_feedback.finrl_hook import build_finrl_intent
    from tradeoff.feedback.recorder import Recorder
    from tradeoff.feedback.store import FeedbackStore
    intent=build_finrl_intent(env(shares=shares),np.array([action],dtype=np.float32),decision())
    assert intent['quantity_delta']==quantity and intent['action']==label
    Recorder(feedback_project).record_decision(intent,event_id='mapped-intent')
    with FeedbackStore(feedback_project,readonly=True) as store:
        saved=store.snapshot()['events']
    assert len(saved)==1 and saved[0]['payload']['quantity_delta']==quantity
    assert all(e['kind']!='order_binding' for e in saved)


@pytest.mark.parametrize('field,value',[('stock_dim',2),('turbulence_threshold',10),('member_col','is_member')])
def test_forced_execution_modes_require_a_different_explicit_adapter(field,value):
    from examples.decision_feedback.finrl_hook import build_finrl_intent
    from tradeoff.feedback.contracts import FeedbackError
    target=env()
    setattr(target,field,value)
    with pytest.raises(FeedbackError) as caught:
        build_finrl_intent(target,np.array([0.5],dtype=np.float32),decision())
    assert caught.value.code=='UNSUPPORTED_FINRL_MODE'


def test_terminal_only_day_never_becomes_an_executable_order():
    from examples.decision_feedback.finrl_hook import build_finrl_intent
    from tradeoff.feedback.contracts import FeedbackError
    target=env()
    target.day=1
    target.terminal=False  # Upstream updates terminal only on the following step.
    target.df=SimpleNamespace(index=SimpleNamespace(unique=lambda:[0,1]))
    with pytest.raises(FeedbackError) as caught:
        build_finrl_intent(target,np.array([0.8],dtype=np.float32),decision())
    assert caught.value.code=='FINRL_EPISODE_COMPLETE'
