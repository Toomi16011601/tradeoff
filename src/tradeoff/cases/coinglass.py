"""Run the published CoinGlass example's real preprocessing and strategy logic."""

from ._loader import SOURCE_DIR, load_rows, load_source, patch_once, strategy_namespace

DESCRIPTION = "Whole-series sentiment storage and preprocessing alter earlier positions."
AUDIT_SETTINGS = {"min_history": 240, "max_probes": 6, "max_calls": 128}
STRATEGY_HASH = "2c97d75c14f74901493b3bf292d8f8e36787bb52b1c463828f83f60eda67fbd5"
ENGINE_SETTINGS = {"cash": 100000, "commission": 0.001, "exclusive_orders": True}
PROVENANCE = {
    "repository": "https://github.com/aria-tjr/coinglass-trading-strategy",
    "commit": "761b236cfa93a1e6223ce5813da4b956a7481737",
    "source_url": "https://github.com/aria-tjr/coinglass-trading-strategy/blob/761b236cfa93a1e6223ce5813da4b956a7481737/simple_backtest.py",
    "source_sha256": STRATEGY_HASH,
    "license": "MIT; Copyright (c) 2026 Aria Tajeri; bundled coinglass_LICENSE",
    "original_strategy": "SimpleCoinGlassStrategy with original simple_rsi/simple_ema/simple_atr and get_simple_data sentiment calculations",
    "fixed_patch": "Use progressive self.I sentiment, trailing 3-bar smoothing with min_periods=1, trailing volume mean with min_periods=1, and forward-only filling.",
    "input": "Frozen synthetic stress tape, 256 hourly bars. NumPy seed 73 log-return std 0.07; final three volumes 2000 vs 1000 earlier. Not market performance evidence.",
    "engine_settings": {**ENGINE_SETTINGS, "exclusive_orders": True, "margin": 1, "hedging": False, "finalize_trades": False},
    "engine_changes": "Original example cash, commission and exclusive-orders settings retained; terminal positions remain open for the audit trace.",
    "isolation": "AST extracts original helper/class definitions and exact pure sentiment statements. Yahoo/API connection and main/report/plot paths are omitted; input bars replace downloaded data.",
    "tested_versions": {"backtesting": "0.6.6", "pandas": "2.2.3", "numpy": "2.3.5"},
}


def rows():
    return load_rows("coinglass")


def _strategy(*, fixed):
    path = SOURCE_DIR / "coinglass_strategy.py"
    source = load_source(path, STRATEGY_HASH)
    if fixed:
        source = patch_once(source, "self.sentiment = self.data.Sentiment",
                            "self.sentiment = self.I(lambda values: np.asarray(values), self.data.Sentiment)")
        source = patch_once(source, "rolling(20).mean().fillna(volume.mean())", "rolling(20, min_periods=1).mean()")
        source = patch_once(source, "rolling(3, center=True).mean()", "rolling(3, min_periods=1).mean()")
        source = patch_once(source, "sentiment_smooth.bfill().ffill().values", "sentiment_smooth.ffill().fillna(0).values")
    namespace = strategy_namespace(source, str(path), prepare_sentiment=True)
    return namespace["SimpleCoinGlassStrategy"], namespace["prepare"]


def _run(tape, config, seed, *, fixed):
    from ..adapters.backtesting import make_backtesting_runner
    strategy, prepare = _strategy(fixed=fixed)
    return make_backtesting_runner(strategy, engine_settings=ENGINE_SETTINGS,
                                   prepare=prepare)(tape, config, seed)


def _execution(tape, config, seed, scenario, *, fixed):
    from ..execution import make_backtesting_execution_runner
    strategy, prepare = _strategy(fixed=fixed)
    return make_backtesting_execution_runner(strategy, engine_settings=ENGINE_SETTINGS,
                                            prepare=prepare)(tape, config, seed, scenario)


def original_execution(rows, config, seed, scenario):
    return _execution(rows, config, seed, scenario, fixed=False)


def fixed_execution(rows, config, seed, scenario):
    return _execution(rows, config, seed, scenario, fixed=True)


def original_run(rows, config, seed):
    return _run(rows, config, seed, fixed=False)


def fixed_run(rows, config, seed):
    return _run(rows, config, seed, fixed=True)


for _callback in (original_run, fixed_run):
    _callback.trace_kind = "observed_position"
    _callback.adapter_info = {"engine": "backtesting", "public_case": "coinglass", "provenance": PROVENANCE}


for _callback in (original_execution, fixed_execution):
    _callback.runner_spec = {"engine": "callback", "engine_settings": {}}
    _callback.adapter_info = {"engine": "backtesting", "version": "0.6.6", "public_case": "coinglass"}
