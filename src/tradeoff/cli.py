"""Local command-line workflows. No market-data or broker connection is needed."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from . import __version__
from .data import load_data


DIAGNOSTICS_HINT = ('Rerun with --diagnostics <private-file-outside-output> for a private local traceback; '
                    'review that file before sharing.')


class _ArgumentError(ValueError):
    code = 'INVALID_ARGUMENTS'


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, json_errors=False, **kwargs):
        self.json_errors = json_errors
        super().__init__(*args, **kwargs)

    def error(self, message):
        if self.json_errors:
            raise _ArgumentError('Invalid command arguments; use the command help to check required arguments and options')
        super().error(message)


def import_adapter(reference):
    from .adapters import resolve_runner
    return resolve_runner(reference)


def validate_output(path):
    """Reject occupied outputs before importing or running strategy code."""
    selected = Path(path).expanduser()
    if selected.is_symlink():
        raise ValueError('Output must be a new or empty directory; symbolic links are not supported')
    folder = selected.resolve()
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise ValueError('Output must be a new or empty directory; choose a fresh output location')
    return folder


def prepare_output(path):
    folder = validate_output(path)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def data_options(args):
    """Translate explicit import options shared by audit and the failure lab."""
    mapping = json.loads(args.column_map) if getattr(args, 'column_map', None) else None
    return {**{name: getattr(args, name, None) for name in
               ('symbol', 'timezone', 'timestamp_column', 'bar_duration', 'session_close')},
            'timestamp_kind': getattr(args, 'timestamp_kind', 'close'), 'column_map': mapping}


def add_data_options(parser):
    parser.add_argument('--symbol', help='Explicit instrument when the data has no Symbol column')
    parser.add_argument('--timezone', help='IANA timezone for naive source timestamps, such as America/New_York')
    parser.add_argument('--timestamp-column', help='Source timestamp column when automatic detection is ambiguous')
    parser.add_argument('--timestamp-kind', choices=['close', 'open'], default='close',
                        help='Whether source timestamps label bar closes or opens')
    parser.add_argument('--bar-duration', help='Fixed duration for bar-open labels, such as 15m or 1h')
    parser.add_argument('--session-close', help='Local HH:MM closing time for date-only session labels')
    parser.add_argument('--column-map', help='JSON object mapping target columns to source columns; extra features are preserved')


def add_diagnostics_option(parser):
    parser.add_argument('--diagnostics', metavar='PRIVATE_FILE',
                        help='Opt in to raw local exception traces in a new file outside the report output; may contain private data')


def _diagnostics_context(args):
    from .diagnostics import local_diagnostics
    path = getattr(args, 'diagnostics', None)
    if path is None:
        return nullcontext()
    private = Path(path).expanduser().resolve()
    output = getattr(args, 'output', None)
    protected_folders = []
    if output is not None:
        protected_folders.append(Path(output).expanduser().resolve())
    if output is None and getattr(args, 'command', None) in {'reproduce', 'replay-failure'}:
        fixture = Path(args.fixture).expanduser()
        protected_folders.extend((fixture.parent.resolve(), fixture.resolve().parent))
    for folder in protected_folders:
        if private == folder or folder in private.parents:
            exc = ValueError('Private diagnostics must be outside the portable report output directory')
            exc.code = 'DIAGNOSTICS_LOCATION'
            raise exc
    return local_diagnostics(path)


def _command_error(exc, args, *, as_json=False):
    """Return useful trusted input errors without echoing arbitrary strategy text."""
    from .privacy import reject_sensitive_data
    phase = getattr(args, '_phase', 'arguments')
    safe_input = phase in {'arguments', 'diagnostics', 'output', 'data', 'config',
                          'requirements', 'scenarios', 'settings', 'integration', 'preflight'}
    code = getattr(exc, 'code', None) if safe_input else None
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', code):
        code = 'INVALID_JSON' if isinstance(exc, json.JSONDecodeError) else (
            'INVALID_INPUT' if isinstance(exc, (ValueError, OSError, TypeError, KeyError, ImportError))
            and safe_input else 'EXECUTION_ERROR')
    message = 'Command failed; exception details are omitted for privacy'
    if isinstance(exc, OSError):
        message = 'A local input or output file could not be accessed; check paths and permissions'
    elif safe_input and isinstance(exc, (ValueError, TypeError, KeyError, ImportError)):
        try:
            candidate = str(exc)
            reject_sensitive_data(candidate)
            message = candidate[:1000]
        except Exception:
            message = 'Input validation failed; sensitive diagnostic details are omitted'
    hint = DIAGNOSTICS_HINT if hasattr(args, 'diagnostics') else 'Use the command help to check inputs and options.'
    summary = {'status': 'ERROR', 'phase': phase,
               'error': {'code': code, 'type': type(exc).__name__, 'message': message,
                         'hint': hint}}
    if as_json:
        print(json.dumps(summary, allow_nan=False))
    else:
        print(f'Error: {message}\n{hint}', file=sys.stderr)
    return 2


def save_audit(callback, rows, config, folder, reference, args, *, provenance=None):
    from .audit import audit
    from .economics import compare_economics, project
    from .reproduce import export_reproducer
    from .report import write_report

    economic_settings = {name: getattr(args, name) for name in (
        "initial_cash", "fee_fixed", "fee_bps", "spread_bps", "slippage_bps", "fill_lag_bars",
        "max_leverage", "short_borrow_bps_annual")}
    project(rows[:1], [{"timestamp": rows[0]["timestamp"], "target": 0}], **economic_settings)
    trace_kind = args.trace_kind or getattr(callback, "trace_kind", "target_units")
    result = audit(callback, rows, config, seed=args.seed, min_history=args.min_history,
                   max_probes=args.max_probes, max_calls=args.max_calls,
                   strategy_ref=reference, trace_kind=trace_kind)
    if getattr(callback, "adapter_info", None):
        result["adapter_info"] = callback.adapter_info
    result["runner_spec"] = getattr(callback, "runner_spec", {"engine": "callback", "engine_settings": {}})
    if provenance is not None:
        result["provenance"] = provenance
    trace = result.get("baseline", {}).get("trace")
    result["economics"] = None
    if trace:
        changed = (result.get("witness") or {}).get("mutated_trace")
        try:
            result["economics"] = compare_economics(rows, trace, changed, **economic_settings)
        except ValueError as exc:
            result["economics_error"] = str(exc)
            result["coverage"]["notes"].append(f"Economic projection unavailable: {exc}")
        if result["economics"] and trace_kind == "observed_position":
            result["economics"]["explanation"] += (
                " This adapter records observed positions. The projection applies a new lag to "
                "those positions and is illustrative; it does not recalculate the engine ledger.")
    result["artifacts"] = {"json": "report.json"}
    if result.get("witness"):
        result["artifacts"].update(export_reproducer(result, folder, reference))
    write_report(result, folder)
    return result


def _demo(args):
    from . import demos
    from .report import write_gallery

    args._phase = 'output'
    folder = prepare_output(args.output)
    args._phase = 'settings'
    rows = demos.synthetic_rows()
    entries = []
    scenarios = [
        ("leaky", "Full-sample threshold", demos.leaky_run,
         "A planted dependency on future prices. Inspect the witness and export its test."),
        ("causal", "Trailing-window control", demos.causal_run,
         "A causal control. No dependency observed is a bounded result, not a certificate."),
        ("unstable", "Stateful callback", demos.unstable_run,
         "Identical inputs produce different targets. The audit explains why it is inconclusive."),
    ]
    for slug, name, callback, description in scenarios:
        scenario_folder = folder / slug
        scenario_folder.mkdir()
        reference = f"tradeoff.demos:{callback.__name__}"
        result = save_audit(callback, rows, {}, scenario_folder, reference, args)
        entries.append({"name": name, "status": result["status"],
                        "path": f"{slug}/index.html", "description": description})
        print(f"{slug:8} {result['status']}")
    index = write_gallery(folder, entries)
    print(f"\nOpen: {index}\nPreview: tradeoff serve --directory {folder}")
    return 0


def _audit(args):
    from .adapters import resolve_runner
    args._phase = 'output'
    validate_output(args.output)
    args._phase = 'settings'
    engine_settings = json.loads(args.engine_settings) if args.engine_settings else {}
    args._phase = 'data'
    rows = load_data(args.data, **data_options(args))
    args._phase = 'config'
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    # Validate before creating output, so malformed data does not leave empty directories.
    from .validation import validate_rows, validate_config
    rows, config = validate_rows(rows), validate_config(config)
    args._phase = 'strategy_import'
    callback = resolve_runner(args.adapter, engine=args.engine, engine_settings=engine_settings)
    args._phase = 'output'
    folder = prepare_output(args.output)
    args._phase = 'execution'
    report = save_audit(callback, rows, config, folder, args.adapter, args)
    if args.json:
        print(json.dumps({'status': report['status'], 'report_id': report['report_id'],
                          'report': str(folder / 'report.json'), 'interface': str(folder / 'index.html')}, allow_nan=False))
    else:
        print(f"{report['status']}: {report['headline']}\nOpen: {folder / 'index.html'}")
    return {"FOUND": 1, "NO_DEPENDENCY_OBSERVED": 0, "INCONCLUSIVE": 2}[report["status"]]


def _cases(args):
    from .cases import CASES, get_case
    from .report import write_gallery, write_report
    from .reproduce import assert_future_invariance, load_fixture, InvarianceError, UnstableRunError

    args._phase = 'output'
    folder = prepare_output(args.output)
    args._phase = 'execution'
    entries, summaries = [], []
    for name in ([args.case] if args.case else CASES):
        case = get_case(name)
        settings = dict(vars(args))
        for key, value in case["audit_settings"].items():
            if settings.get(key) is None:
                settings[key] = value
        selected_args = SimpleNamespace(**settings)
        rows = case["rows"]()
        reports = {}
        for variant in ("original", "fixed"):
            slug = f"{name}-{variant}"
            destination = folder / slug
            destination.mkdir()
            provenance = {**case["provenance"], "variant": variant}
            reports[variant] = save_audit(case[variant], rows, case["config"], destination,
                                          case[f"{variant}_ref"], selected_args, provenance=provenance)
            entries.append({"name": f"{name.title()} · {variant}", "status": reports[variant]["status"],
                            "path": f"{slug}/index.html", "description": case["description"] if variant == "original"
                            else "Causal repair. The original saved fixture is replayed against this variant."})
        replay = "NO_VERIFIED_WITNESS"
        replay_reason = None
        if reports["original"]["status"] == "FOUND":
            fixture = load_fixture(folder / f"{name}-original" / "reproducer.json")
            try:
                assert_future_invariance(case["fixed"], fixture)
            except (InvarianceError, UnstableRunError, ValueError) as exc:
                replay, replay_reason = "FAILED", str(exc)
            else:
                replay = "PASS"
            reports["original"]["repair_replay"] = {"status": replay, "reason": replay_reason,
                                                     "adapter": case["fixed_ref"]}
            write_report(reports["original"], folder / f"{name}-original")
        summaries.append({"case": name, "original_status": reports["original"]["status"],
                          "fixed_status": reports["fixed"]["status"], "repair_replay": replay,
                          "repair_reason": replay_reason,
                          "original_report_id": reports["original"]["report_id"],
                          "provenance": case["provenance"]})
        print(f"{name}: original {reports['original']['status']} / fixed {reports['fixed']['status']} / saved-fixture repair {replay}")
    (folder / "case-results.json").write_text(json.dumps({"schema_version": "edgelab.public-cases.v1",
        "cases": summaries}, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    index = write_gallery(folder, entries, collection="public")
    print(f"\nOpen: {index}\nPreview: tradeoff serve --directory {folder}")
    return 0 if all(s["original_status"] == "FOUND" and s["fixed_status"] == "NO_DEPENDENCY_OBSERVED"
                    and s["repair_replay"] == "PASS" for s in summaries) else 2


def _reproduce(args):
    from .reproduce import load_fixture, assert_future_invariance, InvarianceError, UnstableRunError

    args._phase = 'config'
    fixture = load_fixture(args.fixture)
    reference = args.adapter or fixture.get("strategy_ref")
    from .adapters import resolve_runner
    spec = fixture.get("runner_spec", {"engine": "callback", "engine_settings": {}})
    engine = args.engine or spec["engine"]
    engine_settings = (json.loads(args.engine_settings) if args.engine_settings is not None
                       else (spec["engine_settings"] if engine == spec["engine"] else {}))
    args._phase = 'strategy_import'
    callback = resolve_runner(reference, engine=engine, engine_settings=engine_settings)
    args._phase = 'execution'
    try:
        assert_future_invariance(callback, fixture)
    except UnstableRunError as exc:
        print(f"INCONCLUSIVE: {exc}", file=sys.stderr)
        return 2
    except InvarianceError as exc:
        print(f"DEPENDENCY REPRODUCED: {exc}")
        return 1
    print("PASS: this callback's tested past targets are invariant under the saved intervention.")
    return 0


def _serve(args):
    from .preview import PreviewHTTPRequestHandler, require_secure_preview_support

    args._phase = 'output'
    folder = Path(args.directory).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Report directory does not exist: {folder}")
    require_secure_preview_support()
    handler = partial(PreviewHTTPRequestHandler, directory=str(folder))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Serving {folder}\nhttp://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def _audit_options(parser):
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--min-history", type=int, default=3)
    parser.add_argument("--max-probes", type=int, default=12)
    parser.add_argument("--max-calls", type=int, default=96)
    parser.add_argument("--trace-kind", choices=["target_units", "observed_position"],
                        help="Trace semantics; defaults to adapter metadata or target_units")
    parser.add_argument("--initial-cash", type=float, default=1000)
    parser.add_argument("--fee-fixed", type=float, default=1)
    parser.add_argument("--fee-bps", type=float, default=0)
    parser.add_argument("--spread-bps", type=float, default=2)
    parser.add_argument("--slippage-bps", type=float, default=2)
    parser.add_argument("--fill-lag-bars", type=int, default=1)
    parser.add_argument("--max-leverage", type=float, default=1,
                        help="Projection gross-exposure/equity cap; independent of engine margin")
    parser.add_argument("--short-borrow-bps-annual", type=float, default=0,
                        help="Annual short borrowing cost in projection (365-day convention)")


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in arguments
    parser = _ArgumentParser(prog="tradeoff", description="Find what breaks a strategy and keep a reproducible test.",
                             json_errors=as_json)
    parser.add_argument("--version", action="version", version=f"Tradeoff {__version__}")
    sub = parser.add_subparsers(dest="command", required=True,
                               parser_class=partial(_ArgumentParser, json_errors=as_json))
    from .failure_cli import add_failure_commands
    add_failure_commands(sub)
    from .strategy_onboarding import add_onboarding_commands
    add_onboarding_commands(sub)
    demo = sub.add_parser("demo", help="Build three offline synthetic reports; no keys required")
    demo.add_argument("--output", default="demo-output")
    add_diagnostics_option(demo)
    _audit_options(demo)
    demo.set_defaults(handler=_demo)
    cases = sub.add_parser("cases", help="Run pinned public strategies and verify their causal repairs; optional cases dependencies")
    cases.add_argument("--case", choices=["riskkit", "coinglass"], help="Run just one public case")
    cases.add_argument("--output", default="public-output")
    add_diagnostics_option(cases)
    _audit_options(cases)
    cases.set_defaults(handler=_cases, min_history=None, max_probes=None, max_calls=None, initial_cash=100000)
    audit = sub.add_parser("audit", help="Audit a local callback on CSV or JSON bars")
    audit.add_argument("--adapter", required=True, help="Python module:callable, imported from the current project")
    audit.add_argument("--engine", choices=["callback", "targets", "pandas", "backtrader", "backtesting"],
                       default="callback", help="Load a callback, numeric signals, pandas signals, or an existing engine strategy class")
    audit.add_argument("--engine-settings", help='JSON engine options, for example: {"cash": 10000, "margin": 0.5}')
    audit.add_argument("--data", required=True)
    audit.add_argument("--config", help="JSON object passed to the callback")
    audit.add_argument("--output", default="audit-output")
    audit.add_argument('--json', action='store_true', help='Emit a structured command summary')
    add_data_options(audit)
    add_diagnostics_option(audit)
    _audit_options(audit)
    audit.set_defaults(handler=_audit)
    reproduce = sub.add_parser("reproduce", help="Assert the saved future-invariance test against a callback")
    reproduce.add_argument("fixture")
    reproduce.add_argument("--adapter", help="Override the callback after fixing it")
    reproduce.add_argument("--engine", choices=["callback", "targets", "pandas", "backtrader", "backtesting"],
                           help="Override adapter type; defaults to the saved fixture")
    reproduce.add_argument("--engine-settings", help="Override saved engine options with a JSON object")
    add_diagnostics_option(reproduce)
    reproduce.set_defaults(handler=_reproduce)
    serve = sub.add_parser("serve", help="Preview an existing report on localhost")
    serve.add_argument("--directory", default="demo-output")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(handler=_serve)
    args = SimpleNamespace(_phase='arguments')
    try:
        args = parser.parse_args(arguments)
        args._phase = 'diagnostics'
        with _diagnostics_context(args):
            try:
                args._phase = 'execution'
                return args.handler(args)
            except Exception as exc:
                from .diagnostics import record_exception
                record_exception(exc)
                raise
    except Exception as exc:
        return _command_error(exc, args, as_json=as_json)


if __name__ == "__main__":
    raise SystemExit(main())
