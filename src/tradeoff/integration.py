"""Conservative, non-executing checks for an already imported strategy.

This is not repository discovery or a sandbox. Only direct data references and
function-global loads in user-defined strategy methods are inspected. Helpers,
external initialization, and dynamic access require explicit input declarations.
No strategy methods, descriptors, or companion initialization are invoked.
"""
import ast
import dis
import inspect
import re
import sys
import textwrap
from types import CodeType, ModuleType


_CANONICAL = {name.lower(): name for name in ('Open', 'High', 'Low', 'Close', 'Volume')}
_METADATA = {'timestamp', 'symbol', 'available_at'}
_DATA_PROPERTIES = {'df', 'index', 'pip'}
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def _names(values, label):
    if not isinstance(values, (tuple, list, set, frozenset)):
        raise ValueError(f'{label} must be a list of simple identifiers')
    if any(not isinstance(name, str) or not _IDENTIFIER.fullmatch(name) for name in values):
        raise ValueError(f'{label} must contain only simple identifiers')
    return set(values)


def _column(name):
    return _CANONICAL.get(name.lower(), name)


def _methods(strategy_class):
    """Read function objects directly, without triggering strategy descriptors."""
    seen = set()
    seen_attributes = set()
    for parent in strategy_class.__mro__:
        if parent is object or parent.__module__.split('.')[0] == 'backtesting':
            continue
        for name, value in vars(parent).items():
            if name in seen_attributes:
                continue
            seen_attributes.add(name)
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            candidates = (value.fget, value.fset) if isinstance(value, property) else (value,)
            for function in candidates:
                if inspect.isfunction(function) and id(function) not in seen:
                    seen.add(id(function))
                    yield function


def _global_names(code, operation):
    found = {instruction.argval for instruction in dis.get_instructions(code)
             if instruction.opname == operation}
    for item in code.co_consts:
        if isinstance(item, CodeType):
            found.update(_global_names(item, operation))
    return found


def _builtin_names(function):
    namespace = function.__builtins__
    if isinstance(namespace, dict):
        return set(dict.keys(namespace))
    if isinstance(namespace, ModuleType):
        return set(vars(namespace))
    return set()


def _is_data(node, receiver):
    return (isinstance(node, ast.Attribute) and node.attr == 'data'
            and isinstance(node.value, ast.Name) and node.value.id == receiver)


def _data_reads(function):
    source = textwrap.dedent(inspect.getsource(function))
    tree = ast.parse(source)
    parameters = inspect.signature(function).parameters
    receiver = next(iter(parameters), 'self')
    columns = set()
    dynamic = False
    super_access = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and _is_data(node.value, receiver)):
            if node.attr not in _DATA_PROPERTIES and not node.attr.startswith('_'):
                if _IDENTIFIER.fullmatch(node.attr):
                    columns.add(node.attr)
                else:
                    dynamic = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == 'super':
                super_access = True
            if node.func.id == 'getattr' and node.args and _is_data(node.args[0], receiver):
                dynamic = True
        elif isinstance(node, ast.Subscript) and _is_data(node.value, receiver):
            # Bracket access is not guaranteed to be a column lookup for every
            # supported engine version; an explicit declaration can cover it.
            dynamic = True
        if isinstance(node, ast.Attribute) and _is_data(node.value, receiver) and node.attr == 'df':
            dynamic = True
    return columns, dynamic, super_access


def inspect_strategy(strategy_class, rows, *, required_columns=(), required_globals=(),
                     allow_zero_volume=False, allow_uninitialized_globals=(),
                     available_columns=None):
    """Return a JSON-safe bounded input manifest or raise before native reruns.

    Code references and declarations are case-sensitive native frame names.
    ``available_columns`` is for an already prepared frame and takes precedence
    over raw row keys for presence checks. Raw rows remain the volume-quality
    evidence. Declared required globals cannot be waived by optional-None
    acknowledgements. The caller remains responsible for valid bars and for
    supplying companion data/parameters faithfully to the strategy.
    """
    if not isinstance(strategy_class, type):
        raise ValueError('strategy_class must be a class')
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('rows must be a nonempty list of data objects')
    if type(allow_zero_volume) is not bool:
        raise ValueError('allow_zero_volume must be a boolean')
    columns = _names(required_columns, 'required_columns')
    declared_globals = _names(required_globals, 'required_globals')
    allowed_globals = _names(allow_uninitialized_globals, 'allow_uninitialized_globals')
    if available_columns is not None:
        if (not isinstance(available_columns, (tuple, list, set, frozenset))
                or any(not isinstance(name, str) for name in available_columns)):
            raise ValueError('available_columns must be a list of string column labels')
        # Ordinary CSV headers may contain spaces or punctuation. Only required
        # identifiers are returned; unused private headers are never echoed.
        available = set(available_columns)
    else:
        # A field must be supplied on every bar, not merely the first one.
        available = set.intersection(*(set(row) - _METADATA for row in rows))
        available = {_column(name) for name in available if isinstance(name, str)}
    warnings = []
    missing_source = 0
    inspected = 0
    dynamic = False
    super_access = False
    unset_globals = set()
    missing_globals = set()
    initialized_in_strategy = set()
    declared_states = {name: [] for name in declared_globals}
    methods = list(_methods(strategy_class))
    assignments = {}
    for function in methods:
        assignments.setdefault(id(function.__globals__), set()).update(
            _global_names(function.__code__, 'STORE_GLOBAL'))
    for function in methods:
        inspected += 1
        global_loads = _global_names(function.__code__, 'LOAD_GLOBAL')
        for name in declared_globals & global_loads:
            declared_states[name].append(name in function.__globals__
                                         and function.__globals__[name] is not None)
        builtins = _builtin_names(function)
        for name in global_loads:
            if not _IDENTIFIER.fullmatch(name):
                continue
            if name in function.__globals__:
                if function.__globals__[name] is not None:
                    continue
            elif name in builtins:
                continue
            if name in assignments[id(function.__globals__)]:
                initialized_in_strategy.add(name)
            elif name in function.__globals__:
                unset_globals.add(name)
            else:
                missing_globals.add(name)
        try:
            found, is_dynamic, uses_super = _data_reads(function)
        except (OSError, TypeError, SyntaxError, ValueError):
            missing_source += 1
        else:
            columns.update(found)
            dynamic = dynamic or is_dynamic
            super_access = super_access or uses_super
    missing = columns - available
    if missing:
        raise ValueError('Strategy is missing required data columns: ' + ', '.join(sorted(missing))
                         + '. Supply them in the data or prepare them before running.')
    module = sys.modules.get(strategy_class.__module__)
    namespace = vars(module) if module is not None else {}
    absent_globals = {name for name in declared_globals
                      if (not all(declared_states[name]) if declared_states[name]
                          else name not in namespace or namespace[name] is None)}
    if absent_globals:
        raise ValueError('Strategy required globals are missing or uninitialized: '
                         + ', '.join(sorted(absent_globals))
                         + '. Initialize companion data in an importable adapter before running.')
    if missing_globals:
        raise ValueError('Strategy has missing module globals: ' + ', '.join(sorted(missing_globals))
                         + '. Initialize companion data or import required names before running.')
    blocked_globals = unset_globals - allowed_globals
    if blocked_globals:
        raise ValueError('Strategy has uninitialized module globals: ' + ', '.join(sorted(blocked_globals))
                         + '. Initialize companion data in an importable adapter; intentionally optional '
                         'None globals need allow_uninitialized_globals acknowledgement.')
    if initialized_in_strategy:
        warnings.append('Potential strategy initialization of globals: '
                        + ', '.join(sorted(initialized_in_strategy))
                        + '; initialization order and coverage are not verified.')
    acknowledged = sorted(unset_globals & allowed_globals)
    if acknowledged:
        warnings.append('Uninitialized module globals acknowledged as intentional None: '
                        + ', '.join(acknowledged) + '; their meaning is not verified.')
    zero_volume = ('Volume' in columns and all(row.get('volume') == 0 for row in rows))
    if zero_volume:
        if not allow_zero_volume:
            raise ValueError('Strategy reads Volume but input volume is all zero. Use faithful volume '
                             'data or explicitly acknowledge partial validation with allow_zero_volume.')
        warnings.append('Input volume is all zero: volume filters may be ineffective; '
                        'this is partial strategy validation acknowledged with allow_zero_volume.')
    if missing_source or not inspected:
        warnings.append('Strategy source is unavailable for some methods; declare required columns '
                        'and globals explicitly. Static input inspection is incomplete.')
    if super_access:
        warnings.append('Strategy uses super(); overridden parent implementations were not inspected. '
                        'Static input inspection is incomplete: review and declare their required '
                        'columns and companion globals explicitly.')
    if dynamic:
        warnings.append('Strategy uses dynamic or unsupported data access; review required inputs explicitly. '
                        'Static input inspection covers direct simple-identifier attribute reads only.')
    return {'required_columns': sorted(columns),
            'required_globals': sorted(declared_globals | unset_globals | initialized_in_strategy),
            'warnings': warnings,
            'checks': {'source_available': bool(inspected) and not missing_source,
                       'inspected_methods': inspected,
                       'source_unavailable_methods': missing_source,
                       'dynamic_data_access': dynamic,
                       'super_method_access': super_access,
                       'strategy_initialized_globals': sorted(initialized_in_strategy),
                       'data_scope': 'direct strategy-method data attributes only',
                       'global_scope': 'direct strategy-method global loads only',
                       'acknowledged_uninitialized_globals': acknowledged,
                       'zero_volume_acknowledged': bool(zero_volume and allow_zero_volume)}}
