"""Fresh native Backtesting.py execution under explicit cost/delay assumptions.

Optional engine imports are lazy. The delay hook is local to one broker and
strictly gated to the tested Backtesting.py version; native accounting, order
matching, protections and sizing remain the engine's responsibility.
"""
from copy import deepcopy
from functools import wraps
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys
import warnings

from .adapters import _import_callable
from .adapters._shared import (engine_version, frame_from_rows, numeric_setting,
                              position_target, seeded, settings_dict)
from .validation import validate_config, validate_rows
from .privacy import ExecutionUnavailable


_SUPPORTED_VERSION = '0.6.6'
_DEFAULTS = {'cash': 10000, 'commission': 0, 'spread': 0, 'margin': 1,
             'trade_on_close': False, 'exclusive_orders': False}
_INPUT_DEFAULTS = {'required_columns': [], 'required_globals': [],
                   'allow_zero_volume': False, 'allow_uninitialized_globals': [], 'companions': []}


def _companion_path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('Companion files must use relative paths inside the current project')
    root = Path.cwd().resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Companion file is unavailable inside the current project')
    return path


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def companion_manifest(paths):
    """Bind explicitly selected local side inputs; never copy their contents."""
    result = []
    for value in paths:
        # Absolute CLI inputs are accepted only if they resolve in this project.
        try:
            relative = Path(value).expanduser().resolve().relative_to(Path.cwd().resolve()).as_posix()
        except (ValueError, OSError, TypeError):
            raise ValueError('Companion files must be inside the current project') from None
        path = _companion_path(relative)
        result.append({'path': relative, 'sha256': _file_hash(path)})
    return _validated_companions(result)


def _validated_companions(value):
    if not isinstance(value, list):
        raise ValueError('companions must be a list of relative file paths and hashes')
    result = []
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256'}
                or not isinstance(item['path'], str) or not item['path']
                or Path(item['path']).is_absolute() or '..' in Path(item['path']).parts
                or not isinstance(item['sha256'], str) or re.fullmatch(r'[a-f0-9]{64}', item['sha256']) is None):
            raise ValueError('Companion entries need project-relative path and SHA-256')
        validate_config(item)
        result.append(dict(item))
    return result


def validate_integration(value):
    """Validate the optional replayable native-input declarations."""
    options = settings_dict(validate_config(value), _INPUT_DEFAULTS)
    if type(options['allow_zero_volume']) is not bool:
        raise ValueError('allow_zero_volume must be a boolean')
    for field in ('required_columns', 'required_globals', 'allow_uninitialized_globals'):
        if (not isinstance(options[field], list) or any(not isinstance(name, str)
                or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) is None for name in options[field])):
            raise ValueError(f'{field} must contain simple identifiers')
    options['companions'] = _validated_companions(options['companions'])
    return options


def _check_companions(options):
    for item in options['companions']:
        if _file_hash(_companion_path(item['path'])) != item['sha256']:
            raise ValueError('Companion input changed; restore the declared file before replay')


def _source_provenance(strategy, reference=None):
    def source(obj):
        try:
            path = Path(inspect.getsourcefile(obj))
            return {'file': path.name, 'sha256': _file_hash(path)}
        except (TypeError, OSError, ValueError):
            return {'available': False}
    module = sys.modules.get(reference.split(':')[0]) if reference else None
    return {'strategy_source': source(strategy), 'adapter_source': source(module),
            'runtime_versions': {name: engine_version(name) for name in ('backtesting', 'pandas', 'numpy')},
            'source_scope': 'File hashes record provenance; strategy repairs remain allowed. Dependencies and side inputs are not bundled.'}


def _scenario(value):
    value = settings_dict(value, {'commission_bps': 0, 'spread_bps': 0, 'delay_bars': 0})
    for key in ('commission_bps', 'spread_bps'):
        value[key] = numeric_setting(value[key], key)
    if type(value['delay_bars']) is not int or value['delay_bars'] < 0:
        raise ValueError('delay_bars must be a nonnegative integer')
    return value


def _settings(value):
    options = settings_dict(validate_config(value), _DEFAULTS)
    options['cash'] = numeric_setting(options['cash'], 'cash', exclusive_minimum=True)
    options['spread'] = numeric_setting(options['spread'], 'spread', maximum=1)
    options['margin'] = numeric_setting(options['margin'], 'margin', maximum=1, exclusive_minimum=True)
    for key in ('exclusive_orders', 'trade_on_close'):
        if type(options[key]) is not bool:
            raise ValueError(f'{key} must be a boolean')
    commission = options['commission']
    if isinstance(commission, (tuple, list)):
        if len(commission) != 2:
            raise ValueError('commission must be a relative rate or [fixed, relative]')
        fixed = numeric_setting(commission[0], 'fixed commission')
        relative = numeric_setting(commission[1], 'relative commission', minimum=-.1)
        options['commission'] = [fixed, relative]
    else:
        options['commission'] = numeric_setting(commission, 'commission', minimum=-.1)
    relative = options['commission'][1] if isinstance(options['commission'], list) else options['commission']
    if relative >= .1:
        raise ValueError('native baseline commission must be in [-0.1, 0.1)')
    return options


def _delayed_broker_class(broker_class, delay):
    class DelayedOrders(list):
        """Hide immature markets only while native matching iterates this list.

        Membership/remove and strategy-facing iteration see all orders, so
        cancellation and exclusive-order rules still use the native queue.
        Trade.close inserts directly into this list and is tracked as well.
        """
        def __init__(self, broker):
            super().__init__()
            self.broker = broker
            self.matching = False
            self.created = {}
            self.due = {}

        def insert(self, index, order):
            protective = order.parent_trade is not None and (order.stop is not None or order.limit is not None)
            if not protective:
                if order.stop is not None or order.limit is not None:
                    raise ExecutionUnavailable('delayed standalone stop/limit orders are unsupported')
                if not hasattr(self.broker, '_i'):
                    raise ExecutionUnavailable('delayed orders created in Strategy.init are unsupported')
                created = self.broker._i
                self.created[order] = created
                self.due[order] = created + 1 + delay
            super().insert(index, order)

        def append(self, order):
            self.insert(len(self), order)

        def __iter__(self):
            orders = super().__iter__()
            if not self.matching:
                return orders
            return (order for order in orders if self.due.get(order, -1) <= self.broker._i)

    class DelayedBroker(broker_class):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.orders = DelayedOrders(self)

        def _process_orders(self):
            previous = self.orders.matching
            self.orders.matching = True
            try:
                return super()._process_orders()
            finally:
                self.orders.matching = previous

    return DelayedBroker


def _trade(trade, *, closed):
    result = {'entry_bar': int(trade.entry_bar), 'size': int(trade.size),
              'entry_price': float(trade.entry_price), 'pnl': float(trade.pl)}
    if closed:
        result.update(exit_bar=int(trade.exit_bar), exit_price=float(trade.exit_price),
                      commission=float(trade._commissions))
    else:
        # Native open PnL excludes entry fees. Native equity includes those
        # fees; do not invent a fixed-fee allocation after partial closes.
        result.update(sl=trade.sl, tp=trade.tp)
    return result


def make_backtesting_execution_runner(strategy_class, *, engine_settings=None, prepare=None, integration=None):
    """Return run(rows, config, seed, scenario) with fresh native engine state.

    Costs add to native relative rates (and retain any fixed commission).
    Extra delay postpones discretionary market entries and manual closes by
    delay_bars beyond normal next-open matching. SL/TP remain native. No terminal
    liquidation is added. prepare may add fields, retaining all original OHLCV.
    """
    options = _settings(engine_settings)
    inputs = validate_integration(integration) if integration is not None else None
    if prepare is not None and not callable(prepare):
        raise ValueError('prepare must be a callable or None')

    def preflight(rows, available_columns=None):
        if inputs is None:
            return {}
        from .integration import inspect_strategy
        _check_companions(inputs)
        return inspect_strategy(strategy_class, rows, available_columns=available_columns,
                                **{key: value for key, value in inputs.items() if key != 'companions'})

    def run(rows, config, seed, scenario):
        rows, config, scenario = validate_rows(rows), validate_config(config), _scenario(scenario)
        version = engine_version('backtesting')
        if version != _SUPPORTED_VERSION:
            raise ValueError(f'native execution requires tested Backtesting.py {_SUPPORTED_VERSION}; found {version}')
        try:
            from backtesting import Backtest, Strategy
            from backtesting.backtesting import _Broker
        except ImportError as exc:
            raise ImportError("native execution requires pip install 'backtesting==0.6.6'") from exc
        if not isinstance(strategy_class, type) or not issubclass(strategy_class, Strategy):
            raise ValueError('strategy_class must be a Backtesting.py Strategy subclass')
        effective = deepcopy(options)
        if isinstance(effective['commission'], list):
            effective['commission'][1] += scenario['commission_bps'] / 10000
            relative = effective['commission'][1]
        else:
            effective['commission'] += scenario['commission_bps'] / 10000
            relative = effective['commission']
        if not -.1 <= relative < .1:
            raise ValueError('effective native relative commission must be in [-0.1, 0.1)')
        effective['spread'] += scenario['spread_bps'] / 10000
        if effective['spread'] > 1:
            raise ValueError('effective native spread must not exceed 1')
        delay = scenario['delay_bars']
        if delay and effective['trade_on_close']:
            raise ExecutionUnavailable('delayed trade_on_close execution is unsupported')
        positions = [0] * len(rows)
        broker_holder = []
        native_created = {}
        last_strategy_bar = None

        class RecordingStrategy(strategy_class):
            def init(self):
                broker_holder.append(self._broker)
                super().init()
            def next(self):
                nonlocal last_strategy_bar
                super().next()
                index = len(self.data) - 1
                last_strategy_bar = index
                positions[index] = position_target(self.position.size)
                for order in self.orders:
                    native_created.setdefault(order, index)

        with seeded(seed), warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter('always', UserWarning)
            frame = frame_from_rows(rows)
            if prepare is not None:
                import pandas as pd
                original = frame.copy(deep=True)
                frame = prepare(frame)
                if not isinstance(frame, pd.DataFrame):
                    raise ValueError('prepare must return a DataFrame')
                if not frame.index.equals(original.index):
                    raise ValueError('prepare must preserve the complete original index')
                fields = original.columns.tolist()
                if (not frame.columns.is_unique or not set(fields) <= set(frame.columns)
                        or not frame[fields].equals(original)):
                    raise ValueError('prepare must preserve original OHLCV values and unique columns')
            checks = preflight(rows, frame.columns.tolist())
            run.input_checks = checks
            native_options = deepcopy(effective)
            if isinstance(native_options['commission'], list):
                native_options['commission'] = tuple(native_options['commission'])
            backtest = Backtest(frame, RecordingStrategy, **native_options, hedging=False, finalize_trades=False)
            if delay:
                # Preserve the native factory settings, changing only this
                # instance's broker class. No module-global monkeypatch is used.
                from functools import partial
                backtest._broker = partial(_delayed_broker_class(_Broker, delay), **backtest._broker.keywords)
            stats = backtest.run(**config)
        broker = broker_holder[0]
        halt_warnings = []
        processed_bar = getattr(broker, '_i', None)
        if processed_bar is not None and processed_bar != last_strategy_bar:
            # Backtest.run catches native insolvency before Strategy.next().
            # Observe the actual terminal broker position at that bar; the
            # untouched native broker can retain holdings during liquidation.
            # Later input rows never execute, so retain that terminal state
            # alongside the engine's own frozen equity curve.
            positions[processed_bar:] = [position_target(broker.position.size)] * (len(rows) - processed_bar)
            halt_warnings.append(f'Native engine halted at bar {processed_bar}; subsequent rows retain '
                                 'terminal position and frozen native equity.')
        pending = []
        for order in broker.orders:
            created = getattr(broker.orders, 'created', native_created).get(order)
            due = getattr(broker.orders, 'due', {}).get(order)
            if not delay and created is not None and not order.is_contingent and order.stop is None and order.limit is None:
                due = created + 1
            pending.append({'size': position_target(order.size), 'limit': order.limit, 'stop': order.stop,
                            'sl': order.sl, 'tp': order.tp, 'is_contingent': bool(order.is_contingent),
                            'parent_entry_bar': int(order.parent_trade.entry_bar) if order.parent_trade else None,
                            'created_bar': created, 'due_bar': due})
        result = {'engine': 'backtesting', 'engine_version': version, 'initial_cash': options['cash'],
                  'effective_settings': {**effective, 'hedging': False, 'finalize_trades': False},
                  'scenario': scenario,
                  'timing': ('Native next-open discretionary market execution plus ' + str(delay) +
                             ' extra bar(s); native protective SL/TP timing; no terminal liquidation.'
                             if not effective['trade_on_close'] else
                             'Native trade_on_close execution; native protective SL/TP timing; no terminal liquidation.'),
                  'warnings': ([str(item.message) for item in observed] + halt_warnings + checks.get('warnings', []) +
                               (['Open-trade P&L excludes entry fees; native equity includes charged entry fees.']
                                if broker.trades else [])),
                  'equity': [{'timestamp': row['timestamp'], 'position': positions[i], 'equity': float(value)}
                             for i, (row, value) in enumerate(zip(rows, stats['_equity_curve']['Equity']))],
                  'trades': [_trade(trade, closed=True) for trade in broker.closed_trades],
                  'open_trades': [_trade(trade, closed=False) for trade in broker.trades],
                  'pending_orders': pending}
        json.dumps(result, allow_nan=False)
        return result

    run.runner_spec = {'engine': 'backtesting', 'engine_settings': deepcopy(options)}
    if inputs is not None:
        run.runner_spec['integration'] = deepcopy(inputs)
    run.preflight = preflight
    run.source_provenance = _source_provenance(strategy_class)
    run.adapter_info = {'engine': 'backtesting', 'version': engine_version('backtesting'),
                        'engine_settings': deepcopy(options), 'execution': 'native',
                        'supported_version': _SUPPORTED_VERSION}
    return run


def resolve_execution_runner(reference, *, engine='backtesting', engine_settings=None, integration=None):
    """Resolve a native Strategy class or explicit four-argument callback."""
    if engine not in ('backtesting', 'callback'):
        raise ValueError(f'unsupported execution engine: {engine!r}')
    settings = validate_config(engine_settings)
    inputs = validate_integration(integration) if integration is not None else None
    if inputs is not None:
        _check_companions(inputs)
    fn = _import_callable(reference)
    if engine == 'backtesting':
        run = make_backtesting_execution_runner(fn, engine_settings=settings, integration=inputs)
        run.source_provenance = _source_provenance(fn, reference)
        return run
    settings_dict(settings, {})
    @wraps(fn)
    def run(rows, config, seed, scenario):
        if inputs is not None:
            _check_companions(inputs)
        return fn(rows, config, seed, scenario)
    if hasattr(fn, 'adapter_info'):
        run.adapter_info = deepcopy(fn.adapter_info)
    run.runner_spec = {'engine': 'callback', 'engine_settings': {}}
    if inputs is not None:
        run.runner_spec['integration'] = deepcopy(inputs)
    def preflight(rows):
        if inputs is not None:
            _check_companions(inputs)
            if inputs['required_globals'] or inputs['allow_uninitialized_globals']:
                raise ValueError('Global declarations require a native strategy class; validate callback state explicitly')
            # Callback wrappers own their input semantics; cover declarations
            # without pretending to inspect the wrapped trading implementation.
            from .integration import inspect_strategy
            placeholder = type('CallbackInputs', (), {})
            result = inspect_strategy(placeholder, rows,
                required_columns=inputs['required_columns'], allow_zero_volume=inputs['allow_zero_volume'])
        else:
            result = {'required_columns': [], 'required_globals': [], 'checks': {}, 'warnings': []}
        result['warnings'].append('Automatic strategy input inspection is unavailable for callbacks; validate wrapped strategy state explicitly.')
        return result
    run.preflight = preflight
    run.source_provenance = _source_provenance(fn, reference)
    return run
