"""Collect eligible outcome prices from an explicitly configured local CSV."""
from collections import Counter
from bisect import bisect_left, bisect_right
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile

from ..data import DataImportError, _instant, _session_time, _source_column, _zone
from ..privacy import reject_sensitive_data
from .contracts import (FeedbackError, ID_PATTERN, canonical_json, normalize_decimal,
                        parse_json, schema_for, utc_time, validate_payload)
from .store import FeedbackStore, _no_symlinks

CONFIG = 'price-source.json'
SCHEMA = 'tradeoff.price-source.v1'
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_ROWS = 100000
IDENTITY = ('symbol', 'currency', 'source', 'feed', 'price_kind')
OPTIONS = ('timestamp_column', 'price_column', 'available_at_column', 'timezone', 'session_close')


def _error(code, message):
    raise FeedbackError(code, message)


def _read_config(store):
    path = store.folder / CONFIG
    _no_symlinks(path)
    if not path.exists():
        _error('PRICE_SOURCE_NOT_CONFIGURED', 'Configure a local price source before collecting outcomes')
    try:
        if path.stat().st_size > 65536:
            raise ValueError('oversized')
        config = parse_json(path.read_bytes())
        expected = {'schema_version', 'data_file', *IDENTITY, *OPTIONS}
        if not isinstance(config, dict) or set(config) != expected or config['schema_version'] != SCHEMA:
            raise ValueError('schema')
        reject_sensitive_data(config)
        if not isinstance(config['data_file'], str) or not config['data_file'] or Path(config['data_file']).is_absolute():
            raise ValueError('path')
        for key in IDENTITY:
            if not isinstance(config[key], str) or not re.fullmatch(ID_PATTERN, config[key]):
                raise ValueError('identity')
        for key in OPTIONS:
            if config[key] is not None and (not isinstance(config[key], str) or len(config[key]) > 256):
                raise ValueError('option')
        if config['price_kind'] not in schema_for('mark')['properties']['price_kind']['enum']:
            raise ValueError('price kind')
        return config
    except (OSError, ValueError, TypeError, KeyError):
        _error('INVALID_PRICE_SOURCE', 'Price-source configuration is invalid; preserve it and configure a valid source')


def configure_source(store, arguments):
    args = dict(arguments)
    replace = args.pop('replace', False)
    try:
        _zone(args.get('timezone'))
        _session_time(args.get('session_close'))
    except DataImportError as exc:
        raise FeedbackError(exc.code, str(exc)) from None
    path = Path(args.pop('data_file'))
    if not path.is_absolute():
        path = store.project / path
    path = Path(os.path.abspath(path))
    _no_symlinks(path)
    if path.suffix.lower() != '.csv' or not path.is_file():
        _error('INVALID_PRICE_FILE', 'Select an existing local CSV price file; no directories or URLs are scanned')
    config = {key: args.get(key) for key in OPTIONS}
    config.update(timestamp_column=args.get('timestamp_column', 'timestamp'), price_column=args.get('price_column', 'price'))
    config.update({key:args[key] for key in IDENTITY}, schema_version=SCHEMA, data_file=os.path.relpath(path, store.project))
    target = store.folder / CONFIG
    _no_symlinks(target)
    if target.exists():
        current = _read_config(store)
        if current == config:
            return dict(status='SOURCE_CONFIGURED', storage='.tradeoff/feedback/' + CONFIG)
        if not replace:
            _error('PRICE_SOURCE_EXISTS', 'Existing price settings are preserved; use replace only after reviewing the new source')
    fd, name = tempfile.mkstemp(prefix='.price-source-', dir=store.folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(canonical_json(config) + '\n')
        Path(name).chmod(0o600)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return dict(status='SOURCE_CONFIGURED', storage='.tradeoff/feedback/' + CONFIG)


def _read_prices(config, project):
    path = Path(os.path.abspath(Path(project) / config['data_file']))
    _no_symlinks(path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            _error('PRICE_FILE_LIMIT', 'Price source must be a regular CSV file of at most 16 MiB')
        with path.open('rb') as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            _error('PRICE_FILE_LIMIT', 'Price source must be at most 16 MiB')
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
        headers = reader.fieldnames or []
        reject_sensitive_data(headers)
        if not headers or any(not h.strip() for h in headers) or len({h.casefold().strip() for h in headers}) != len(headers):
            _error('INVALID_PRICE_COLUMNS', 'CSV headers must be nonempty and unambiguous')
        time_key = _source_column(headers, config['timestamp_column'])
        price_key = _source_column(headers, config['price_column'])
        available_key = _source_column(headers, config['available_at_column']) if config['available_at_column'] else None
        identity_keys = {name:next((h for h in headers if h.strip().casefold() == name), None) for name in IDENTITY}
        zone, session = _zone(config['timezone']), _session_time(config['session_close'])
        observations = {}
        for index, row in enumerate(reader):
            if index >= MAX_ROWS:
                _error('PRICE_FILE_LIMIT', 'Price source must contain at most 100000 rows')
            if None in row or any(v is None for v in row.values()):
                _error('INVALID_PRICE_ROW', 'Every CSV row must match its header width')
            reject_sensitive_data(row)
            if any(header and row[header] != config[key] for key,header in identity_keys.items()):
                _error('PRICE_SOURCE_IDENTITY_CONFLICT', 'Embedded price identity must match the configured symbol, currency, source, feed and price kind')
            observed = _instant(row[time_key], zone, session)
            price = normalize_decimal(row[price_key])
            if Decimal(price) <= 0:
                _error('INVALID_PRICE', 'Observed prices must be positive finite decimal values')
            available = _instant(row[available_key], zone, session) if available_key else None
            if available is not None and available < observed:
                _error('INVALID_PRICE_TIME', 'A recorded price receipt cannot precede its observation')
            item = dict(observed_at=observed, price=price, available_at=available)
            if observed in observations and observations[observed] != item:
                _error('PRICE_OBSERVATION_CONFLICT', 'Conflicting prices or receipt times share one observation timestamp')
            observations[observed] = item
        if not observations:
            _error('EMPTY_PRICE_SOURCE', 'The configured CSV contains no observations')
        return sorted(observations.values(), key=lambda item:item['observed_at']), hashlib.sha256(raw).hexdigest()
    except FeedbackError:
        raise
    except DataImportError as exc:
        raise FeedbackError(exc.code, str(exc)) from None
    except (OSError, ValueError, UnicodeError, csv.Error):
        _error('INVALID_PRICE_FILE', 'The configured price CSV could not be read safely')


def collect(store, *, as_of=None):
    """Append only eligible imported marks; preserve unknown evidence and old heads."""
    config = _read_config(store)
    observations, digest = _read_prices(config, store.project)
    times = [item['observed_at'] for item in observations]
    received = utc_time(store.clock())  # Actual read time, never backdated to a bar.
    cutoff = utc_time(as_of) if as_of is not None else received
    if cutoff > received:
        _error('FUTURE_COLLECTION_CUTOFF', 'Collection cutoff cannot be later than the actual price-read time')
    with store.transaction():
        if _read_config(store) != config:
            _error('PRICE_SOURCE_CHANGED', 'Price-source settings changed during collection; retry with stable settings')
        before = store.snapshot()
        decisions = [e['payload'] for e in before['events'] if e['kind'] == 'decision' and e['payload']['decision_at'] <= cutoff]
        if len({d['decision_id'] for d in decisions}) != len(decisions):
            _error('AMBIGUOUS_DECISIONS', 'Resolve duplicate decision identities before collecting prices')
        existing = {}
        by_observation = {}
        for event in before['events']:
            if event['kind'] != 'mark':
                continue
            mark = event['payload']
            old = existing.get(mark['mark_id'])
            if old is not None and old != mark:
                _error('PRICE_OBSERVATION_CONFLICT', 'One stored mark identity has conflicting payloads; old evidence is preserved')
            existing[mark['mark_id']] = mark
            key = tuple(mark[name] for name in (*IDENTITY,'observed_at'))
            by_observation.setdefault(key, []).append(mark)
        # Check the entire selected source before choosing a newest candidate.
        # A later valid row must not hide a changed earlier stored observation.
        for observation in observations:
            key = tuple(config[name] for name in IDENTITY) + (observation['observed_at'],)
            matches = by_observation.get(key, [])
            if any(mark['price'] != observation['price'] or
                   (observation['available_at'] is not None and mark['available_at'] != observation['available_at'])
                   for mark in matches):
                _error('PRICE_OBSERVATION_CONFLICT', 'A stored observation or receipt differs from the source; old evidence is preserved')
        selected, unresolved = {}, Counter()
        for decision in decisions:
            if decision['horizon_end'] > cutoff:
                continue
            identity = {key:(decision[key] if key in {'symbol','currency'} else decision['reference'][key]) for key in IDENTITY}
            if any(identity[key] != config[key] for key in IDENTITY):
                unresolved['SOURCE_MISMATCH'] += 1
                continue
            candidates = []
            left, right = bisect_left(times, decision['decision_at']), bisect_right(times, decision['horizon_end'])
            for index in range(right-1, left-1, -1):
                observation = observations[index]
                age = (datetime.fromisoformat(decision['horizon_end'])-datetime.fromisoformat(observation['observed_at'])).total_seconds()
                if age > decision['reference']['max_age_seconds']:
                    break
                key = {**identity, 'observed_at':observation['observed_at']}
                mark_id = 'price-' + hashlib.sha256(canonical_json(key).encode()).hexdigest()
                matches = by_observation.get(tuple(key[name] for name in (*IDENTITY,'observed_at')), [])
                if any(mark['price'] != observation['price'] for mark in matches):
                    _error('PRICE_OBSERVATION_CONFLICT', 'An existing observation has a different price; old evidence is preserved')
                old = min(matches, key=lambda mark:mark['available_at'], default=None)
                available = observation['available_at'] or (old['available_at'] if old else received)
                if old is not None:
                    mark_id = old['mark_id']
                payload = validate_payload('mark', dict(key, mark_id=mark_id, price=observation['price'], available_at=available))
                if old is not None and old != payload:
                    _error('PRICE_OBSERVATION_CONFLICT', 'A previously collected observation changed; old evidence is preserved')
                if available <= cutoff:
                    candidates.append(payload)
                    break
            if candidates:
                item = max(candidates, key=lambda p:p['observed_at'])
                selected[item['mark_id']] = item
            else:
                unresolved['NO_ELIGIBLE_PRICE'] += 1
        records = [dict(event_id=key, kind='mark', payload=value, origin='imported',
                        environment=store.metadata.get('recording_environment','paper')) for key,value in selected.items() if key not in existing]
        store.append_batch(records)
        after = store.snapshot()
    return before, after, dict(new_marks=len(records), input_sha256=digest, rows_checked=len(observations),
        unresolved=[dict(code=key,count=value) for key,value in sorted(unresolved.items())]), cutoff
