"""Run Riskkit's original Backtesting.py example, with its actual position sizer."""

from ._loader import SOURCE_DIR, load_rows, load_source, patch_once, riskkit_sizing, strategy_namespace

DESCRIPTION = "A backfilled 100-bar volatility baseline changes earlier order quantities."
AUDIT_SETTINGS = {"min_history": 45, "max_probes": 8, "max_calls": 256}
STRATEGY_HASH = "c048814bd21cae26002958c9b769c52ecf89ce052c89a47b18476015b4700d9b"
SIZING_HASH = "d32d36591d22b5643224075f854385015f01ff9a6a1a19e9169c4e581cd26f95"
ENGINE_SETTINGS = {"cash": 100000, "commission": 0.002, "exclusive_orders": False}
PROVENANCE = {
    "repository": "https://github.com/HasibVortex369/riskkit",
    "commit": "99d1d167dc55c8a564526ef42d87e298f3e74fad",
    "source_url": "https://github.com/HasibVortex369/riskkit/blob/99d1d167dc55c8a564526ef42d87e298f3e74fad/examples/backtesting_py_strategy.py",
    "source_sha256": STRATEGY_HASH, "sizing_sha256": SIZING_HASH,
    "license": "MIT; Copyright (c) 2026 Hasib; bundled riskkit_LICENSE",
    "original_strategy": "RiskkitSMA; original PositionSizer and SizingInputs from upstream sizing.py",
    "fixed_patch": "Remove .bfill() in rolling_std. Backtesting.py then waits for trailing indicator warmup.",
    "input": "Frozen synthetic stress tape, 160 hourly bars. Seed 2; 25 flat bars, 25 uniform [45,155] closes, 110 flat bars. Not market performance evidence.",
    "engine_settings": {**ENGINE_SETTINGS, "margin": 1, "hedging": False, "finalize_trades": False},
    "engine_changes": "Original cash, commission and nonexclusive order behavior retained; terminal positions remain open. Trading rules and sizer are unchanged.",
    "tested_versions": {"backtesting": "0.6.6", "pandas": "2.2.3", "numpy": "2.3.5"},
}


def rows():
    return load_rows("riskkit")


EXECUTION_INPUT = ("Frozen synthetic execution stress tape, 400 hourly bars: the original 160-bar leakage input "
                   "plus 240 oscillating closes 100 + 12*sin(i/10) + uniform[-0.25,0.25], Python seed 17. "
                   "Next open equals previous close; coherent 0.3% high/low envelope; volume 1000. "
                   "Constructed to exercise post-warmup roundtrips, not market performance evidence.")


def execution_rows():
    return load_rows('riskkit_execution')


def _strategy(*, fixed):
    strategy_path = SOURCE_DIR / "riskkit_strategy.py"
    sizing_path = SOURCE_DIR / "riskkit_sizing.py"
    source = load_source(strategy_path, STRATEGY_HASH)
    sizing = riskkit_sizing(load_source(sizing_path, SIZING_HASH), str(sizing_path))
    if fixed:
        source = patch_once(source, ".rolling(n).std().bfill().values", ".rolling(n).std().values")
    namespace = strategy_namespace(source, str(strategy_path),
                                   extra={"PositionSizer": sizing.PositionSizer, "SizingInputs": sizing.SizingInputs})
    return namespace["RiskkitSMA"]


def _run(tape, config, seed, *, fixed):
    from ..adapters.backtesting import make_backtesting_runner
    return make_backtesting_runner(_strategy(fixed=fixed), engine_settings=ENGINE_SETTINGS)(tape, config, seed)


def _execution(tape, config, seed, scenario, *, fixed):
    from ..execution import make_backtesting_execution_runner
    return make_backtesting_execution_runner(_strategy(fixed=fixed),
        engine_settings=ENGINE_SETTINGS)(tape, config, seed, scenario)


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
    _callback.adapter_info = {"engine": "backtesting", "public_case": "riskkit", "provenance": PROVENANCE}


for _callback in (original_execution, fixed_execution):
    _callback.runner_spec = {"engine": "callback", "engine_settings": {}}
    _callback.adapter_info = {"engine": "backtesting", "version": "0.6.6", "public_case": "riskkit"}
