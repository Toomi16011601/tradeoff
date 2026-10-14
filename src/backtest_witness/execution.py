"""Fresh native Backtesting.py execution under explicit cost/delay assumptions.

Optional engine imports are lazy. The delay hook is local to one broker and
strictly gated to the tested Backtesting.py version; native accounting, order
matching, protections and sizing remain the engine's responsibility.
"""
from copy import deepcopy
from functools import wraps
import json
import warnings

from .adapters import _import_callable
from .adapters._shared import (engine_version, frame_from_rows, numeric_setting,
                              position_target, seeded, settings_dict)
from .validation import validate_config, validate_rows
from .privacy import ExecutionUnavailable


_SUPPORTED_VERSION = '0.6.6'
_DEFAULTS = {'cash': 10000, 'commission': 0, 'spread': 0, 'margin': 1,
             'trade_on_close': False, 'exclusive_orders': False}


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


def make_backtesting_execution_runner(strategy_class, *, engine_settings=None, prepare=None):
    """Return run(rows, config, seed, scenario) with fresh native engine state.

    Costs add to native relative rates (and retain any fixed commission).
    Extra delay postpones discretionary market entries and manual closes by
    delay_bars beyond normal next-open matching. SL/TP remain native. No terminal
    liquidation is added. prepare may add fields, retaining all original OHLCV.
    """
    options = _settings(engine_settings)
    if prepare is not None and not callable(prepare):
        raise ValueError('prepare must be a callable or None')

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
                  'warnings': ([str(item.message) for item in observed] + halt_warnings +
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
    run.adapter_info = {'engine': 'backtesting', 'version': engine_version('backtesting'),
                        'engine_settings': deepcopy(options), 'execution': 'native',
                        'supported_version': _SUPPORTED_VERSION}
    return run


def resolve_execution_runner(reference, *, engine='backtesting', engine_settings=None):
    """Resolve a native Strategy class or explicit four-argument callback."""
    if engine not in ('backtesting', 'callback'):
        raise ValueError(f'unsupported execution engine: {engine!r}')
    settings = validate_config(engine_settings)
    fn = _import_callable(reference)
    if engine == 'backtesting':
        return make_backtesting_execution_runner(fn, engine_settings=settings)
    settings_dict(settings, {})
    @wraps(fn)
    def run(rows, config, seed, scenario):
        return fn(rows, config, seed, scenario)
    if hasattr(fn, 'adapter_info'):
        run.adapter_info = deepcopy(fn.adapter_info)
    run.runner_spec = {'engine': 'callback', 'engine_settings': {}}
    return run
