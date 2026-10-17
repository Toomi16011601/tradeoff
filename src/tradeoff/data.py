"""Explicit, standard-library-only imports of local historical market bars.

No provider, timezone, symbol, exchange calendar or missing observation is
inferred. Imported timestamps label bar closes; source labels are preserved
under their original noncanonical column name for strategy-specific use.
"""
from __future__ import annotations

import csv
from datetime import datetime, time, timedelta, timezone as utc_timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .privacy import SensitiveDataError, reject_sensitive_data
from .validation import parse_timestamp, validate_rows


class DataImportError(ValueError):
    """A safe, actionable input error with machine-readable classification."""

    def __init__(self, code, message, *, columns=()):
        super().__init__(message)
        self.code = code
        self.columns = list(columns)


_FIELDS = ("open", "high", "low", "close", "volume")
_CANONICAL = frozenset((*_FIELDS, "timestamp", "symbol", "available_at"))
_TIME_ALIASES = frozenset(("timestamp", "datetime", "date", "time"))


def _fail(code, message, *, columns=()):
    raise DataImportError(code, message, columns=columns)


def _column_key(value):
    return value.strip().casefold()


def _source_column(headers, requested):
    if not isinstance(requested, str):
        _fail("COLUMN_MAP_INVALID", "Column names must be strings")
    matches = [header for header in headers if _column_key(header) == _column_key(requested)]
    if len(matches) != 1:
        _fail("MISSING_COLUMNS", "A selected source column is missing; check timestamp_column and column_map")
    return matches[0]


def _bindings(headers, timestamp_column, column_map):
    reject_sensitive_data(headers, label="column names")
    if any(not isinstance(header, str) or not header.strip() for header in headers):
        _fail("INVALID_COLUMNS", "Input column names must be nonempty strings")
    keys = [_column_key(header) for header in headers]
    if len(keys) != len(set(keys)):
        _fail("DUPLICATE_COLUMNS", "Duplicate input columns are ambiguous; provide one column per field")
    sources = {name: headers[keys.index(name)] for name in _CANONICAL - {"timestamp"} if name in keys}
    if timestamp_column is not None:
        sources["timestamp"] = _source_column(headers, timestamp_column)
    else:
        candidates = [header for header in headers if _column_key(header) in _TIME_ALIASES]
        if len(candidates) > 1:
            _fail("AMBIGUOUS_TIMESTAMP", "Multiple time columns found; choose one with timestamp_column")
        if candidates:
            sources["timestamp"] = candidates[0]
    if column_map is None:
        column_map = {}
    if not isinstance(column_map, dict):
        _fail("COLUMN_MAP_INVALID", "column_map must be an object mapping target columns to source columns")
    reject_sensitive_data(column_map, label="column_map")
    mapped = {}
    for target, source in column_map.items():
        if not isinstance(target, str) or not target.strip():
            _fail("COLUMN_MAP_INVALID", "Mapped column names must be nonempty strings")
        source = _source_column(headers, source)
        target_key = _column_key(target)
        if target_key in _CANONICAL:
            if target_key in sources and sources[target_key] != source:
                _fail("COLUMN_MAP_CONFLICT", "column_map cannot replace a detected canonical market column")
            sources[target_key] = source
        else:
            if target_key in keys and headers[keys.index(target_key)] != source:
                _fail("COLUMN_MAP_CONFLICT", "column_map cannot overwrite an existing extra column")
            if target_key in {_column_key(name) for name in mapped}:
                _fail("COLUMN_MAP_CONFLICT", "Mapped extra columns must have unique names")
            mapped[target] = source
    missing = [field for field in (*_FIELDS, "timestamp") if field not in sources]
    if missing:
        _fail("MISSING_COLUMNS", "Required market columns are missing; supply timestamp and Open/High/Low/Close/Volume or column_map", columns=missing)
    return sources, mapped


def _zone(name):
    if name is None:
        return None
    if not isinstance(name, str):
        _fail("INVALID_TIMEZONE", "timezone must be an IANA name such as UTC or America/New_York")
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        _fail("INVALID_TIMEZONE", "Unknown timezone; use an installed IANA name such as UTC or America/New_York")


def _duration(value):
    match = re.fullmatch(r"([1-9][0-9]*)(s|m|h|d)", value) if isinstance(value, str) else None
    if match is None:
        _fail("BAR_DURATION_REQUIRED", "Bar-open labels require a positive fixed bar_duration such as 15m or 1h")
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
    try:
        return timedelta(seconds=int(match[1]) * scale)
    except OverflowError:
        _fail("BAR_DURATION_REQUIRED", "bar_duration exceeds the supported fixed duration range")


def _session_time(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        _fail("INVALID_SESSION_CLOSE", "session_close must be a local HH:MM time, for example 16:00")
    return time.fromisoformat(value)


def _instant(value, zone, session, *, timestamp_kind="close", duration=None):
    if not isinstance(value, str):
        _fail("INVALID_TIMESTAMP", "Timestamps must be ISO-8601 strings", columns=["timestamp"])
    text = value.strip()
    date_only = re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text) is not None
    if not date_only and not re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}", text):
        _fail("INVALID_TIMESTAMP", "Use extended ISO-8601 dates (YYYY-MM-DD) or datetimes", columns=["timestamp"])
    if date_only:
        if timestamp_kind == "open":
            _fail("TIMESTAMP_OPTIONS_CONFLICT", "Date-only session labels require timestamp_kind='close'; use session_close for their closing time")
        if session is None:
            _fail("SESSION_CLOSE_REQUIRED", "Date-only labels require an explicit session_close (HH:MM); no exchange calendar is inferred")
        text += "T" + session.isoformat()
    try:
        instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("INVALID_TIMESTAMP", "Timestamps must be ISO-8601 dates or datetimes", columns=["timestamp"])
    if instant.tzinfo is None or instant.utcoffset() is None:
        if zone is None:
            _fail("TIMEZONE_REQUIRED", "Naive dates and times require an explicit timezone (IANA name)", columns=["timestamp"])
        # Reject both missing spring times and repeated fall times rather than
        # choosing a DST fold or silently shifting a nonexistent observation.
        candidates = [instant.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
        try:
            valid = [candidate for candidate in candidates
                     if candidate.astimezone(utc_timezone.utc).astimezone(zone).replace(tzinfo=None) == instant]
        except OverflowError:
            _fail("INVALID_TIMESTAMP", "Timezone conversion is outside the supported date range", columns=["timestamp"])
        if not valid or len({candidate.utcoffset() for candidate in valid}) > 1:
            _fail("AMBIGUOUS_LOCAL_TIME", "Local time is ambiguous or nonexistent at a clock change; supply timezone-aware ISO-8601 timestamps", columns=["timestamp"])
        instant = valid[0]
    try:
        instant = instant.astimezone(utc_timezone.utc)
    except OverflowError:
        _fail("INVALID_TIMESTAMP", "Timezone conversion is outside the supported date range", columns=["timestamp"])
    if timestamp_kind == "open":
        try:
            instant += duration
        except OverflowError:
            _fail("INVALID_TIMESTAMP", "The shifted bar-close timestamp is outside the supported date range", columns=["timestamp"])
    return instant.isoformat()


def _csv_scalar(value):
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    # CSV extras remain scalars. Do not invent nested feature structures.
    return parsed if parsed is None or type(parsed) in (str, bool, int, float) else value


def load_data(path, *, symbol=None, timezone=None, timestamp_column=None,
              timestamp_kind="close", bar_duration=None, session_close=None,
              column_map=None):
    """Load CSV/JSON bars with explicit labeling, mapping and market metadata.

    ``column_map`` maps target names to source names. Existing canonical fields
    cannot be silently replaced. Fixed durations accept positive integer s/m/h/d
    units. Date-only labels use a declared regular session close, not a calendar.
    """
    if timestamp_kind not in ("close", "open"):
        _fail("INVALID_TIMESTAMP_KIND", "timestamp_kind must be 'close' or 'open'")
    duration = _duration(bar_duration) if timestamp_kind == "open" else None
    if timestamp_kind == "close" and bar_duration is not None:
        _fail("TIMESTAMP_OPTIONS_CONFLICT", "bar_duration applies only to timestamp_kind='open'")
    zone = _zone(timezone)
    session = _session_time(session_close)
    if symbol is not None:
        reject_sensitive_data(symbol, label="symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            _fail("INVALID_SYMBOL", "symbol must be a nonempty string")
    path = Path(path)
    is_csv = path.suffix.lower() == ".csv"
    if is_csv:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            # Validate before DictReader can discard duplicate values.
            sources, mapped = _bindings(headers, timestamp_column, column_map)
            raw = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in raw):
            _fail("ROW_WIDTH_MISMATCH", "CSV rows must have exactly the same number of cells as the header")
    elif path.suffix.lower() == ".json":
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            _fail("INVALID_JSON", "Data JSON could not be parsed; provide an array of rows or an object containing rows")
        raw = content.get("rows") if isinstance(content, dict) else content
        if not isinstance(raw, list) or not raw or any(not isinstance(row, dict) for row in raw):
            _fail("INVALID_DATA", "rows must be a nonempty list of JSON objects")
        headers = list(dict.fromkeys(key for row in raw for key in row))
        sources, mapped = _bindings(headers, timestamp_column, column_map)
    else:
        _fail("UNSUPPORTED_DATA_FORMAT", "Data must be a .csv or .json file")
    if not raw:
        _fail("INVALID_DATA", "Data must contain at least one market bar")
    if "symbol" not in sources and symbol is None:
        _fail("SYMBOL_REQUIRED", "No symbol column found; supply an explicit symbol (filenames are not used)", columns=["symbol"])
    reject_sensitive_data(raw, label="rows")
    result = []
    reserved_sources = {source for field, source in sources.items() if field != "timestamp"}
    for index, original in enumerate(raw):
        row = {key: (_csv_scalar(value) if is_csv else value) for key, value in original.items()
               if key not in reserved_sources and _column_key(key) not in _CANONICAL}
        time_source = sources["timestamp"]
        if time_source != "timestamp" and time_source in original:
            row[time_source] = original[time_source]
        for target, source in mapped.items():
            if source not in original:
                _fail("MISSING_COLUMNS", f"Input row {index + 1} is missing a mapped feature column")
            row[target] = _csv_scalar(original[source]) if is_csv else original[source]
        for field in _FIELDS:
            if sources[field] not in original:
                _fail("MISSING_COLUMNS", f"Input row {index + 1} is missing a required market column", columns=[field])
            value = original[sources[field]]
            if is_csv:
                try:
                    value = float(value)
                except (TypeError, ValueError, OverflowError):
                    _fail("NONNUMERIC_OHLCV", f"Input row {index + 1}: market prices and volume must be numeric", columns=[field])
            row[field] = value
        value = original.get(sources.get("symbol")) if "symbol" in sources else symbol
        if symbol is not None and value != symbol:
            _fail("SYMBOL_CONFLICT", "Explicit symbol differs from an embedded symbol; select one instrument before import", columns=["symbol"])
        row["symbol"] = value
        row["timestamp"] = _instant(original.get(sources["timestamp"]), zone, session,
                                      timestamp_kind=timestamp_kind, duration=duration)
        if "available_at" in sources:
            row["available_at"] = _instant(original.get(sources["available_at"]), zone, session)
        result.append(row)
    try:
        return validate_rows(result)
    except SensitiveDataError:
        raise
    except ValueError as exc:
        raise DataImportError("INVALID_DATA", str(exc)) from None


def inspect_data(rows):
    """Return bounded data-quality warnings without changing or filling the tape."""
    rows = validate_rows(rows)
    warnings = []
    if all(row["volume"] == 0 for row in rows):
        warnings.append({"code": "ZERO_VOLUME", "columns": ["volume"],
                         "message": "Volume is zero for every bar; volume-dependent conditions may be ineffective. Use a suitable feed or explicitly assess this limitation."})
    if len(rows) > 2:
        instants = [parse_timestamp(row["timestamp"]) for row in rows]
        intervals = {right - left for left, right in zip(instants, instants[1:])}
        if len(intervals) > 1:
            warnings.append({"code": "IRREGULAR_INTERVALS", "columns": ["timestamp"],
                             "message": "Observed bar spacing varies; delays count observed bars, not elapsed time. Market closures or missing observations may explain gaps; no bars were filled."})
    return warnings
