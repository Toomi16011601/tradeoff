"""Run a real pinned FinRL PPO policy and verify local feedback collection.

Downloads one pinned public historical CSV. No account, live orders or LLM.
This deliberately short experiment establishes integration, not policy quality.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import inspect
import json
import os
from pathlib import Path
from urllib.request import urlopen

from tradeoff.feedback.api import FeedbackApp
from tradeoff.feedback.contracts import utc_time
from tradeoff.feedback.recorder import Recorder
from tradeoff.feedback.store import FeedbackStore

from .finrl_hook import build_finrl_intent

FINRL_COMMIT = '7e98df461cbc7772f16a545a2f13b521e5d0b8f4'
DATA_COMMIT = '1498ea7ce56493913e805e15a16d5892c52e4b69'
DATA_URL = f'https://raw.githubusercontent.com/AminHP/gym-anytrading/{DATA_COMMIT}/gym_anytrading/datasets/data/STOCKS_GOOGL.csv'
DATA_SHA256 = '7a9e5fa6130b926a2c3c8ca96d206e3c6d6502933d6bd5b73ff8db9473ecbe8e'
SOURCE = 'gym-anytrading-stock-googl'
FEED = 'bundled-date-labels'


def run(output, *, mode='stochastic', steps=2048):
    """Train/save/reload the upstream agent, then compare native and observed runs."""
    target = FeedbackApp(Path.cwd())._output(output)
    target.mkdir(mode=0o700, parents=True)
    os.environ['MPLBACKEND'] = 'Agg'
    os.environ['MPLCONFIGDIR'] = str(target / 'plot-cache')
    import numpy as np
    import pandas as pd
    import torch
    from finrl.agents.stablebaselines3.models import DRLAgent
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
    from stable_baselines3 import PPO

    expected = {StockTradingEnv:'d2d7539cbcc0b386e698bfccffac4eb218e2100efb40a7eb2662f24c891dc520',
                DRLAgent:'e71707d0eaae0117fad36f9aa1be59da0186619db59111fe43372d92ad9510b0'}
    for component, digest in expected.items():
        if hashlib.sha256(Path(inspect.getfile(component)).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Install the documented pinned FinRL source before running this pilot')
    with urlopen(DATA_URL, timeout=30) as response:
        raw = response.read(2*1024*1024)
    if hashlib.sha256(raw).hexdigest() != DATA_SHA256:
        raise RuntimeError('Public sample checksum differs; no data or price provenance was guessed')
    prices = target / 'public-prices.csv'
    prices.write_bytes(raw)
    data = pd.read_csv(prices)
    frame = pd.DataFrame(dict(date=data.Date, close=data.Close, tic='GOOGL'))
    train, heldout = frame.iloc[:1600].reset_index(drop=True), frame.iloc[1600:1729].reset_index(drop=True)
    options = dict(stock_dim=1, hmax=100, initial_amount=10000, num_stock_shares=[0],
        buy_cost_pct=[0.001], sell_cost_pct=[0.001], reward_scaling=1e-4,
        state_space=3, action_space=1, tech_indicator_list=[], print_verbosity=10**9,
        make_plots=False, turbulence_threshold=None, member_col=None)
    torch.set_num_threads(1)
    train_env = StockTradingEnv(df=train, **options)
    try:
        agent = DRLAgent(train_env)
        model = agent.get_model('ppo', seed=7, verbose=0,
            policy_kwargs={'net_arch':{'pi':[32,32], 'vf':[32,32]}},
            model_kwargs={'n_steps':64,'batch_size':32,'n_epochs':3,'learning_rate':0.0003,'device':'cpu'})
        model = agent.train_model(model,'integration-pilot',total_timesteps=steps)
        model.save(target / 'ppo-policy')
    finally:
        train_env.close()
    policy = PPO.load(target / 'ppo-policy', device='cpu')
    with FeedbackStore(target, create=True, environment='simulated'):
        pass
    app, recorder = FeedbackApp(target), Recorder(target)
    label = lambda i: str(heldout.iloc[i]['date']) + 'T00:00:00+00:00'
    boundary = str(train.iloc[-1]['date']) + 'T00:00:00+00:00'
    common = dict(source_alias='finrl-simulation',symbol='GOOGL',asset_class='us_equity',currency='USD')
    app.import_evidence({'records':[
        dict(event_id='initial-inventory',kind='inventory',environment='simulated',payload={**common,
            'quantity':'0','observed_at':boundary,'capture_started_at':boundary,'capture_completed_at':boundary,
            'open_order_ids':[],'origin':'imported'}),
        dict(event_id='historical-clock-note',kind='source_note',environment='simulated',payload={
            'source_alias':'finrl-simulation','note_id':'historical-clock','code':'HISTORICAL_TIMESTAMPS_UNVERIFIED',
            'interval_start':label(0),'interval_end':label(len(heldout)-1),'symbol':'GOOGL',
            'metadata':{'activity_type':'historical-date-labels-not-venue-times'}})]})

    def evaluate(record):
        env = StockTradingEnv(df=heldout.copy(), **options)
        state, _ = env.reset(seed=7)
        torch.manual_seed(700)
        trace, episode = [], 0
        try:
            for index in range(len(heldout)-1):
                action, _ = policy.predict(np.asarray(state), deterministic=mode=='deterministic')
                did, oid = f'decision-{index}', f'simulation-order-{index}'
                metadata = dict(decision_id=did,agent_id='finrl-ppo',agent_version=f'seed7-{steps}steps-{mode}',
                    opportunity_id=f'bar-{index}',symbol='GOOGL',asset_class='us_equity',currency='USD',
                    decision_at=label(index),horizon_end=label(index+1),episode_id=f'episode-{episode}',
                    input_hash=hashlib.sha256(np.asarray(state).tobytes()).hexdigest(),
                    reference=dict(price=str(heldout.iloc[index]['close']),price_kind='close',source=SOURCE,feed=FEED,
                                   observed_at=label(index),available_at=label(index),max_age_seconds=0))
                intent = build_finrl_intent(env, action, metadata)
                if record:
                    receipt = recorder.record_decision(intent,event_id=f'record-{index}')
                    assert recorder.record_decision(intent,event_id=f'record-{index}') == receipt
                previous_holdings = int(env.state[2])
                state, _, _, _, _ = env.step(action.copy())
                executed = int(env.actions_memory[-1][0])
                assert executed == int(intent['quantity_delta']), 'Native execution no longer matches the supported intent adapter'
                assert int(env.state[2])-previous_holdings == executed
                if record and executed:
                    binding = recorder.bind_order(dict(decision_id=did,source_alias='finrl-simulation',order_id=oid),event_id=f'bind-{index}')
                    assert binding['seq'] > receipt['seq']
                    # IDs are caller-owned simulation scaffolding, not real broker orders.
                    order = {**common,'order_id':oid,'side':intent['action'],'quantity':str(abs(executed)),
                             'filled_quantity':str(abs(executed)),'status':'filled','submitted_at':label(index)}
                    fill = {**common,'fill_id':f'fill-{index}','order_id':oid,'quantity_delta':str(executed),
                            'price':str(heldout.iloc[index]['close']),'occurred_at':label(index)}
                    app.import_evidence({'records':[
                        dict(event_id=f'order-{index}',kind='order',payload=order,environment='simulated'),
                        dict(event_id=f'fill-{index}',kind='fill',payload=fill,environment='simulated')]})
                trace.append(dict(quantity=executed,cash=float(env.state[0]),shares=int(env.state[2]),equity=float(env.asset_memory[-1])))
                if previous_holdings and not env.state[2]:
                    episode += 1
        finally:
            env.close()
        return trace

    native, observed = evaluate(False), evaluate(True)
    assert native == observed, 'Observation changed the native action or account path'
    before = app.evaluate_decisions({'as_of':utc_time(datetime.now(timezone.utc))})
    assert all(d['outcome_status']=='UNAVAILABLE' for d in before['evaluation']['decisions'])
    app.configure_price_source(dict(data_file=str(prices.absolute()),symbol='GOOGL',currency='USD',source=SOURCE,
        feed=FEED,price_kind='close',timestamp_column='Date',price_column='Close',timezone='UTC',session_close='00:00'))
    after = app.collect_outcomes({'output':'report'})
    assert all(d['outcome_status']=='AVAILABLE' for d in after['feedback']['evaluation']['decisions'])
    assert all(e['observed_net'] is None for e in after['feedback']['evaluation']['episodes'])
    head = after['feedback']['evidence']
    again = app.collect_outcomes({})
    assert again['collection']['new_marks']==0 and again['feedback']['evidence']==head
    old = app.evaluate_decisions({'as_of':before['as_of'],'as_of_seq':before['evidence']['as_of_seq']})
    assert all(d['outcome_status']=='UNAVAILABLE' for d in old['evaluation']['decisions'])
    summary = dict(status='VERIFIED_INTEGRATION',mode=mode,agent_commit=FINRL_COMMIT,data_commit=DATA_COMMIT,
        data_sha256=DATA_SHA256,versions={name:version(name) for name in ('finrl','stable-baselines3','torch','numpy','gymnasium')},
        training_steps=int(model.num_timesteps),training_rows=len(train),heldout_rows=len(heldout),
        decisions=len(observed),fills=sum(bool(t['quantity']) for t in observed),holds=sum(not t['quantity'] for t in observed),
        unavailable_before=len(before['evaluation']['decisions']),available_after=len(after['feedback']['evaluation']['decisions']),
        repeated_collection_new_marks=again['collection']['new_marks'],native_trace_identical=True,
        capture=dict(Counter(d['capture']['classification'] for d in after['feedback']['evaluation']['decisions'])),
        report='report/index.html',limitations='Historical simulation; daily ordering labels, unverified receipt/venue times, caller-owned execution IDs and incomplete observed fees. No account API, LLM, prospective timing or trading-performance claim.')
    (target/'pilot-result.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='feedback-output-finrl')
    parser.add_argument('--mode',choices=['stochastic','deterministic'],default='stochastic')
    parser.add_argument('--steps',type=int,default=2048)
    args = parser.parse_args()
    if not 64 <= args.steps <= 100000:
        parser.error('Use 64 through 100000 training steps; this is an integration pilot')
    print(json.dumps(run(args.output,mode=args.mode,steps=args.steps),indent=2))


if __name__=='__main__':
    main()
