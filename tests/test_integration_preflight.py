"""Bounded static checks catch missing inputs before expensive native reruns."""
import json

import pytest


SPY_OK = None
OPTIONAL_FILTER = None
READY_FILTER = [True, False]


def rows(**extras):
    return [dict(timestamp='2026-01-01T00:00:00Z', symbol='SYNTH', open=10,
                 high=11, low=9, close=10, volume=100, **extras)]


class DirectInputs:
    def next(self):
        return self.data.Close[-1] + self.data.signal[-1]


# Dropping static field detection would allow an absent indicator into native runs.
def test_missing_direct_column_is_actionable_before_strategy_execution():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'required data columns.*signal'):
        inspect_strategy(DirectInputs, rows())


# Canonical OHLCV normalization must not lowercase case-sensitive indicator names.
def test_input_manifest_preserves_extra_column_case_and_is_json_safe():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(DirectInputs, rows(signal=2), required_columns=['signal'])
    assert result['required_columns'] == ['Close', 'signal']
    assert result['required_globals'] == []
    assert result['checks']['source_available'] is True
    json.dumps(result, allow_nan=False)
    with pytest.raises(ValueError, match=r'required data columns.*Signal'):
        inspect_strategy(DirectInputs, rows(signal=2), required_columns=['Signal'])


class CompanionInput:
    def next(self):
        return SPY_OK[-1]


# A None companion filter previously crashed inside engine execution.
def test_uninitialized_direct_global_requires_initialization():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'uninitialized.*SPY_OK'):
        inspect_strategy(CompanionInput, rows())


# Optional None configuration must be a deliberate and visible acknowledgement.
def test_optional_none_global_can_be_acknowledged_without_claiming_initialized():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(CompanionInput, rows(), allow_uninitialized_globals=['SPY_OK'])
    assert result['required_globals'] == ['SPY_OK']
    assert any('SPY_OK' in warning and 'acknowledged' in warning for warning in result['warnings'])
    assert result['checks']['acknowledged_uninitialized_globals'] == ['SPY_OK']


# Explicit requirements must not be bypassed by the optional-state escape hatch.
@pytest.mark.parametrize('name', ['SPY_OK', 'MISSING_FILTER'])
def test_explicit_companion_requirement_must_exist_and_be_initialized(name):
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'required globals.*' + name):
        inspect_strategy(DirectInputs, rows(signal=1), required_globals=[name],
                         allow_uninitialized_globals=[name])


class LocalNames:
    def next(self, OPTIONAL_FILTER=None):
        SPY_OK = None
        self.local_filter = SPY_OK
        return self.data.Close[-1] if OPTIONAL_FILTER is None else READY_FILTER[-1]


# Matching AST names without lexical scope would mistake locals for globals.
def test_locals_and_parameters_do_not_become_uninitialized_module_globals():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(LocalNames, rows(), required_globals=['READY_FILTER'])
    assert result['required_globals'] == ['READY_FILTER']
    assert result['warnings'] == []


class VolumeStrategy:
    def next(self):
        return self.data.Volume[-1] > 0


# Zero-volume replacement data silently disabled a public strategy's volume filter.
def test_all_zero_volume_blocks_a_strategy_that_reads_volume():
    from backtest_witness.integration import inspect_strategy
    data = rows()
    data[0]['volume'] = 0
    with pytest.raises(ValueError, match=r'all zero.*allow_zero_volume'):
        inspect_strategy(VolumeStrategy, data)
    result = inspect_strategy(VolumeStrategy, data, allow_zero_volume=True)
    assert any('all zero' in warning and 'ineffective' in warning for warning in result['warnings'])


# Strategies that ignore volume should not need an unnecessary override.
def test_zero_volume_does_not_block_price_only_strategy():
    from backtest_witness.integration import inspect_strategy
    data = rows(signal=1)
    data[0]['volume'] = 0
    result = inspect_strategy(DirectInputs, data)
    assert result['warnings'] == []


class Adapter(DirectInputs):
    pass


# Wrapper subclasses must retain upstream requirements without invoking init/next.
def test_inherited_strategy_methods_are_inspected_without_execution():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'required data columns.*signal'):
        inspect_strategy(Adapter, rows())


class DynamicInputs:
    field = 'Close'
    def next(self):
        return getattr(self.data, self.field)[-1]


# Dynamic access cannot be declared verified by a direct-attribute inspector.
def test_dynamic_access_is_visible_as_incomplete_static_coverage():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(DynamicInputs, rows())
    assert result['checks']['dynamic_data_access'] is True
    assert any('dynamic' in warning for warning in result['warnings'])


# Generated methods have no retrievable source, which must remain visible.
def test_source_unavailable_is_not_reported_as_complete():
    from backtest_witness.integration import inspect_strategy
    namespace = {}
    exec('def next(self):\n    return self.data.Close[-1]', namespace)
    generated = type('Generated', (), {'next': namespace['next']})
    result = inspect_strategy(generated, rows())
    assert result['checks']['source_available'] is False
    assert any('source' in warning and 'unavailable' in warning for warning in result['warnings'])


# Prepared indicators must be checked against the actual prepared frame columns.
def test_prepared_frame_column_manifest_overrides_raw_available_columns():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(DirectInputs, rows(), available_columns=['Open', 'High', 'Low', 'Close', 'Volume', 'signal'])
    assert result['required_columns'] == ['Close', 'signal']
    with pytest.raises(ValueError, match=r'required data columns.*signal'):
        inspect_strategy(DirectInputs, rows(signal=1), available_columns=['Close'])


# User-controlled labels must not leak paths, arbitrary values, or multiline text.
@pytest.mark.parametrize('option', ['required_columns', 'required_globals', 'allow_uninitialized_globals'])
def test_declared_identifiers_are_validated_without_echoing_private_values(option):
    from backtest_witness.integration import inspect_strategy
    secret = '/private/person/credential\nsecret'
    with pytest.raises(ValueError) as error:
        inspect_strategy(DirectInputs, rows(signal=1), **{option: [secret]})
    assert secret not in str(error.value)
    assert '/private' not in str(error.value)


class ColumnWriter:
    def init(self):
        self.data.signal = [1]


# A write creates a column; it is not evidence that the column must already exist.
def test_column_writes_are_not_treated_as_required_data_reads():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(ColumnWriter, rows())
    assert result['required_columns'] == []


# Wrappers must validate the namespace the inherited method really reads.
def test_declared_companion_global_resolves_in_inherited_method_namespace(monkeypatch):
    from backtest_witness.integration import inspect_strategy
    class ExternalAdapter(CompanionInput):
        pass
    ExternalAdapter.__module__ = 'unregistered_wrapper_module'
    monkeypatch.setitem(globals(), 'SPY_OK', [True])
    result = inspect_strategy(ExternalAdapter, rows(), required_globals=['SPY_OK'])
    assert result['required_globals'] == ['SPY_OK']
    assert result['warnings'] == []


# Preserved CSV extras may have spaces even when the strategy never reads them.
def test_available_columns_accept_unused_non_identifier_headers():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(DirectInputs, rows(signal=1),
                              available_columns=['Open', 'High', 'Low', 'Close', 'Volume',
                                                 'signal', 'Adj Close', 'private/path/header'])
    assert result['required_columns'] == ['Close', 'signal']
    assert 'private/path/header' not in json.dumps(result)


# Invalid DataFrame column types must fail safely without rendering their values.
def test_available_columns_reject_non_string_labels_without_echoing_them():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match='available_columns.*string') as error:
        inspect_strategy(DirectInputs, rows(signal=1), available_columns=['Close', 'signal', 91827364])
    assert '91827364' not in str(error.value)


class NonIdentifierInput:
    def next(self):
        return self.data.信号[-1]


# Non-ASCII source labels remain outside the safe returned identifier contract.
def test_non_simple_source_field_is_visible_as_unverified_without_echoing_label():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(NonIdentifierInput, rows(), available_columns=['信号'])
    assert result['required_columns'] == []
    assert result['checks']['dynamic_data_access'] is True
    assert '信号' not in json.dumps(result, ensure_ascii=False)


class UnreachableInputs:
    def init(self):
        return self.data.UpstreamInit[-1]
    def next(self):
        return self.data.UpstreamOnly[-1]
    @property
    def filter_value(self):
        return self.data.UpstreamProperty[-1]


class ShadowedInputs(UnreachableInputs):
    filter_value = 1
    def init(self):
        pass
    def next(self):
        return self.data.Close[-1]


# A resolved override removes unreachable base requirements from first-use checks.
def test_shadowed_methods_and_properties_do_not_require_base_class_inputs():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(ShadowedInputs, rows())
    assert result['required_columns'] == ['Close']
    assert result['warnings'] == []


class ExplicitSuper(UnreachableInputs):
    filter_value = 1
    def init(self):
        return super().init()
    def next(self):
        return self.data.Close[-1]


# Ignoring the superclass implementation must not imply it was checked.
def test_explicit_super_access_warns_that_parent_inputs_need_review():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(ExplicitSuper, rows())
    assert result['checks']['super_method_access'] is True
    assert any('super()' in warning and 'incomplete' in warning for warning in result['warnings'])


class WrongCaseInput:
    def next(self):
        return self.data.close[-1]


# Native data attributes are case-sensitive; Close does not satisfy close.
def test_source_column_case_must_match_the_actual_native_frame():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'required data columns.*close'):
        inspect_strategy(WrongCaseInput, rows())


# Explicit declarations use native frame spelling, not CSV aliases.
def test_declared_column_case_is_not_reinterpreted_as_canonical_ohlcv():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'required data columns.*close'):
        inspect_strategy(LocalNames, rows(), required_columns=['close'])


# A prepared frame may intentionally contain a distinct lower-case custom field.
def test_prepared_column_names_are_used_exactly_without_alias_normalization():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(WrongCaseInput, rows(), available_columns=['close'])
    assert result['required_columns'] == ['close']


class AbsentGlobal:
    def next(self):
        return NEVER_INITIALIZED[-1]


# An absent module global fails just as surely as a None companion input.
def test_absent_global_reference_is_reported_before_native_execution():
    from backtest_witness.integration import inspect_strategy
    with pytest.raises(ValueError, match=r'missing.*NEVER_INITIALIZED'):
        inspect_strategy(AbsentGlobal, rows())


class InitializedDuringStrategy:
    def init(self):
        global CREATED_BY_STRATEGY
        CREATED_BY_STRATEGY = [True]
    def next(self):
        return CREATED_BY_STRATEGY[-1]


# Static checks must neither execute init nor reject a potential strategy initializer.
def test_missing_global_with_strategy_assignment_is_unverified_instead_of_blocked():
    from backtest_witness.integration import inspect_strategy
    assert 'CREATED_BY_STRATEGY' not in globals()
    result = inspect_strategy(InitializedDuringStrategy, rows())
    assert 'CREATED_BY_STRATEGY' not in globals()
    assert result['checks']['strategy_initialized_globals'] == ['CREATED_BY_STRATEGY']
    assert any('initialization' in warning and 'not verified' in warning for warning in result['warnings'])


INITIALIZED_BY_INIT = None


class NoneDuringImport:
    def init(self):
        global INITIALIZED_BY_INIT
        INITIALIZED_BY_INIT = [True]
    def next(self):
        return INITIALIZED_BY_INIT[-1]


# None globals intentionally populated by init need the same bounded treatment.
def test_none_global_with_strategy_assignment_warns_without_executing_initializer():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(NoneDuringImport, rows())
    assert INITIALIZED_BY_INIT is None
    assert result['checks']['strategy_initialized_globals'] == ['INITIALIZED_BY_INIT']
    with pytest.raises(ValueError, match=r'required globals.*INITIALIZED_BY_INIT'):
        inspect_strategy(NoneDuringImport, rows(), required_globals=['INITIALIZED_BY_INIT'])


class BuiltinReader:
    def next(self):
        return len(self.data.Close)


# Builtin resolution must use the function's actual builtins and must not invoke them.
def test_builtin_global_loads_are_not_classified_as_missing_companion_inputs():
    from backtest_witness.integration import inspect_strategy
    result = inspect_strategy(BuiltinReader, rows())
    assert result['warnings'] == []
    namespace = {'__builtins__': {'project_builtin': [True]}}
    exec('def next(self):\n    return project_builtin[-1]', namespace)
    strategy = type('CustomBuiltins', (), {'next': namespace['next']})
    result = inspect_strategy(strategy, rows())
    assert not any('project_builtin' in warning for warning in result['warnings'])
