"""Local command-line workflows. No market-data or broker connection is needed."""
from __future__ import annotations

import argparse
import csv
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from . import __version__


def import_adapter(reference):
    from .adapters import resolve_runner
    return resolve_runner(reference)


def load_data(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for index, row in enumerate(rows):
            for key in ("open", "high", "low", "close", "volume"):
                try:
                    row[key] = float(row[key])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"CSV row {index + 2}: {key} must be numeric") from exc
        return rows
    if path.suffix.lower() == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
        return content.get("rows") if isinstance(content, dict) else content
    raise ValueError("Data must be a .csv or .json file")


def prepare_output(path):
    folder = Path(path).expanduser().resolve()
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise ValueError(f"Output must be a new or empty directory: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


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

    folder = prepare_output(args.output)
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
        reference = f"backtest_witness.demos:{callback.__name__}"
        result = save_audit(callback, rows, {}, scenario_folder, reference, args)
        entries.append({"name": name, "status": result["status"],
                        "path": f"{slug}/index.html", "description": description})
        print(f"{slug:8} {result['status']}")
    index = write_gallery(folder, entries)
    print(f"\nOpen: {index}\nPreview: backtest-witness serve --directory {folder}")
    return 0


def _audit(args):
    from .adapters import resolve_runner
    engine_settings = json.loads(args.engine_settings) if args.engine_settings else {}
    callback = resolve_runner(args.adapter, engine=args.engine, engine_settings=engine_settings)
    rows = load_data(args.data)
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    # Validate before creating output, so malformed data does not leave empty directories.
    from .validation import validate_rows, validate_config
    rows, config = validate_rows(rows), validate_config(config)
    folder = prepare_output(args.output)
    report = save_audit(callback, rows, config, folder, args.adapter, args)
    print(f"{report['status']}: {report['headline']}\nOpen: {folder / 'index.html'}")
    return {"FOUND": 1, "NO_DEPENDENCY_OBSERVED": 0, "INCONCLUSIVE": 2}[report["status"]]


def _cases(args):
    from .cases import CASES, get_case
    from .report import write_gallery, write_report
    from .reproduce import assert_future_invariance, load_fixture, InvarianceError, UnstableRunError

    folder = prepare_output(args.output)
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
    print(f"\nOpen: {index}\nPreview: backtest-witness serve --directory {folder}")
    return 0 if all(s["original_status"] == "FOUND" and s["fixed_status"] == "NO_DEPENDENCY_OBSERVED"
                    and s["repair_replay"] == "PASS" for s in summaries) else 2


def _reproduce(args):
    from .reproduce import load_fixture, assert_future_invariance, InvarianceError, UnstableRunError

    fixture = load_fixture(args.fixture)
    reference = args.adapter or fixture.get("strategy_ref")
    from .adapters import resolve_runner
    spec = fixture.get("runner_spec", {"engine": "callback", "engine_settings": {}})
    engine = args.engine or spec["engine"]
    engine_settings = (json.loads(args.engine_settings) if args.engine_settings is not None
                       else (spec["engine_settings"] if engine == spec["engine"] else {}))
    callback = resolve_runner(reference, engine=engine, engine_settings=engine_settings)
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
    parser = argparse.ArgumentParser(prog="backtest-witness", description="Find what breaks a strategy and keep a reproducible test.")
    parser.add_argument("--version", action="version", version=f"BacktestWitness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    from .failure_cli import add_failure_commands
    add_failure_commands(sub)
    demo = sub.add_parser("demo", help="Build three offline synthetic reports; no keys required")
    demo.add_argument("--output", default="demo-output")
    _audit_options(demo)
    demo.set_defaults(handler=_demo)
    cases = sub.add_parser("cases", help="Run pinned public strategies and verify their causal repairs; optional cases dependencies")
    cases.add_argument("--case", choices=["riskkit", "coinglass"], help="Run just one public case")
    cases.add_argument("--output", default="public-output")
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
    _audit_options(audit)
    audit.set_defaults(handler=_audit)
    reproduce = sub.add_parser("reproduce", help="Assert the saved future-invariance test against a callback")
    reproduce.add_argument("fixture")
    reproduce.add_argument("--adapter", help="Override the callback after fixing it")
    reproduce.add_argument("--engine", choices=["callback", "targets", "pandas", "backtrader", "backtesting"],
                           help="Override adapter type; defaults to the saved fixture")
    reproduce.add_argument("--engine-settings", help="Override saved engine options with a JSON object")
    reproduce.set_defaults(handler=_reproduce)
    serve = sub.add_parser("serve", help="Preview an existing report on localhost")
    serve.add_argument("--directory", default="demo-output")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(handler=_serve)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ValueError, OSError, TypeError, KeyError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
