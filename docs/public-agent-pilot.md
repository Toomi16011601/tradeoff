# Real public-agent pilot: FinRL PPO

This pilot tests whether a real public agent can get usable Tradeoff feedback. It runs the installed upstream FinRL agent and environment, trains and reloads an actual Stable Baselines3 neural PPO policy, and evaluates it on held-out historical prices. It uses no paid model API, brokerage account or private trading project.

## Sources and setup actually tested

- [FinRL commit `7e98df4`](https://github.com/AI4Finance-Foundation/FinRL/tree/7e98df461cbc7772f16a545a2f13b521e5d0b8f4), MIT. The full package installed normally, resolving 175 packages. There was no environment-file extraction, import stub or upstream source modification. Its agent and environment source hashes are checked by the example.
- [gym-anytrading GOOGL CSV at `1498ea7`](https://github.com/AminHP/gym-anytrading/blob/1498ea7ce56493913e805e15a16d5892c52e4b69/gym_anytrading/datasets/data/STOCKS_GOOGL.csv): 2,335 bundled historical OHLCV observations. SHA-256 `7a9e5fa6130b926a2c3c8ca96d206e3c6d6502933d6bd5b73ff8db9473ecbe8e`. This is the upstream public sample; its original vendor/timestamp availability is not independently certified. The dataset is downloaded, not copied into Tradeoff.
- Observed runtime: Python 3.12.13, FinRL 0.3.8, Stable Baselines3 2.9.2, PyTorch 2.15.0, NumPy 2.5.4, Gymnasium 1.4.0. FinRL and Tradeoff installed together with no broken requirements. The full dependency graph is not a frozen environment lock.

The first 1,600 observations train the policy for 2,048 CPU steps. The next 129 observations yield 128 held-out decisions. A fixed seed and one CPU thread bound this integration experiment. Neither data nor weights are selected for profitability.

## What actually blocked the workflow

1. **Policy output is not executable intent.** FinRL scales/truncates a continuous action, then applies cash/share limits. Logging the raw proposal can create imaginary short orders or fills. The supported [adapter](../examples/decision_feedback/finrl_hook.py) computes the executable long-only intent before `step`, records holds when clipping reaches zero, and checks the observed native transition afterward. Forced liquidations and multi-stock ordering are explicitly unsupported. The final terminal-only day is not an order opportunity.
2. **Recorded decisions still had no later-price observations.** On Tradeoff 0.5.1, a valid recording hook left all 128 matured outcomes `UNAVAILABLE`. Syncing orders/fills cannot supply horizon prices by itself.
3. **The first collector attempt rejected ordinary home-directory paths.** The existing portable-data guard correctly rejected those strings. Price-source configuration now normalizes the explicitly selected local path to a project-relative reference before portable-data validation. Credential-pattern checks remain intact; file paths never enter feedback reports.

## Observed before and after

The same real trained policy was run without and with the recording hook. Every executable action, cash balance, holding and account-value observation matched exactly.

| Held-out run | Executed transitions | Holds | Outcomes before collection | Outcomes after collection |
| --- | ---: | ---: | --- | --- |
| Default deterministic inference | 0 | 128 | 128 unavailable | 128 available |
| Seeded stochastic inference | 67 | 61 | 128 unavailable | 128 available |

The stochastic variant exercises the actual trained policy's sampling mode; it is labelled explicitly and does not replace the deterministic result. These counts describe the tested environment, not guaranteed cross-platform policy behavior.

Repeating collection added **zero** marks. The original evidence head still reproduced missing outcomes. Every historical decision remained `LATE_CAPTURE`; collection did not convert replay into prospective evidence. Missing observed costs and source-time uncertainty remained unresolved, and no observed net return was asserted. Caller-generated execution IDs are simulation scaffolding; FinRL's environment is not a real broker order ledger.

## Reproduce from a fresh checkout

From the Tradeoff checkout, create an isolated Python 3.12 environment and install the normal packages:

```bash
python3.12 -m venv .venv-finrl
source .venv-finrl/bin/activate
python -m pip install '.[mcp]' \
  'finrl @ git+https://github.com/AI4Finance-Foundation/FinRL.git@7e98df461cbc7772f16a545a2f13b521e5d0b8f4' \
  'stable-baselines3==2.9.2' 'torch==2.15.0' 'numpy==2.5.4' 'gymnasium==1.4.0'
python -m pip check
python -m examples.decision_feedback.finrl_pilot --output feedback-output-finrl
```

Keep `.venv-finrl/` out of version control using your local ignore rules. FinRL's normal installation is substantially larger than Tradeoff's core; this optional example is not a core dependency. The command downloads the pinned public CSV, trains/saves/reloads the real policy, verifies native parity, configures the local source and collects outcomes automatically. Open **`feedback-output-finrl/report/index.html`** directly. The machine-readable receipt is `feedback-output-finrl/pilot-result.json`. Use a fresh output folder for each run.

To retain the public policy's deterministic mode:

```bash
python -m examples.decision_feedback.finrl_pilot \
  --mode deterministic --output feedback-output-finrl-deterministic
```

No order is sent to a broker. The example applies an explicit simulation configuration and caller-owned adapter; it does not run FinRL's network-dependent stock-selection/data-download application unchanged. The actual upstream model/environment execute normally, without mocks or code patches.

## What this does and does not establish

It demonstrates a working recording/collection/report loop for this public RL simulation, including real model inference and actual historical input. Date-only CSV labels are encoded as midnight UTC for ordering, **not** exchange-close, venue-fill or known-at-the-time timestamps. Same-close fills and fixed simulated fees are FinRL's model assumptions. This is not a live broker test, full LLM-agent run, future-data audit of FinRL, realistic execution certification or evidence of better/profitable trading.

Alpaca-account and full public LLM-agent tests remain separate and opt-in. [Main verification record](verification.md) · [Connect your own agent and price source](feedback-integration.md).
