"""Private append-only SQLite evidence, retry receipts and consistent snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import uuid

from ..privacy import reject_sensitive_data
from .contracts import FeedbackError, ID_PATTERN, canonical_json, parse_json, utc_time, validate_payload

ZERO = "0" * 64
PROJECT_SCHEMA = "tradeoff.feedback-project.v1"


def _fail(code="INVALID_PROJECT"):
    raise FeedbackError(code, "Feedback project or evidence is invalid; use a separate valid local project")


def _no_symlinks(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        _fail("UNSAFE_PATH")


class FeedbackStore:
    def __init__(self, project: Path, *, create=False, clock=None, environment=None, readonly=False):
        if readonly and create:
            _fail("READ_ONLY")
        self.readonly = readonly
        self.project = Path(project).absolute()
        _no_symlinks(self.project)
        self.folder = self.project / ".tradeoff" / "feedback"
        _no_symlinks(self.folder)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if environment is not None and environment not in {"paper", "simulated", "live_import"}:
            _fail("INVALID_ENVIRONMENT")
        self.environment = environment or "paper"
        if not self.folder.exists():
            if not create:
                raise FeedbackError("PROJECT_NOT_INITIALIZED", "Run tradeoff feedback init for this workspace first")
            self._initialize()
        try:
            for name in ("project.json", "events.sqlite3", "private.key"):
                path = self.folder / name
                _no_symlinks(path)
                if not path.is_file():
                    _fail()
            self.metadata = parse_json((self.folder / "project.json").read_bytes())
            if self.metadata.get("schema_version") != PROJECT_SCHEMA:
                _fail("UNSUPPORTED_SCHEMA")
            if environment is not None and self.metadata.get("recording_environment", "paper") != environment:
                _fail("ENVIRONMENT_CONFLICT")
            self.key = (self.folder / "private.key").read_bytes()
            if len(self.key) != 32:
                _fail()
            database = self.folder / "events.sqlite3"
            if readonly:
                # mode=ro can create/update WAL sidecars. immutable=1 would
                # instead ignore active WAL evidence. Refuse both hazards.
                with database.open("rb") as stream:
                    header = stream.read(20)
                if header[18:20] != b"\x01\x01":
                    _fail("READ_ONLY_STORAGE_MODE")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro" if readonly else database,
                                      uri=readonly, timeout=5, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            if readonly:
                self.db.execute("PRAGMA query_only=ON")
            self.db.execute("PRAGMA busy_timeout=5000")
        except FeedbackError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            _fail()

    def _initialize(self):
        parent = self.folder.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = Path(tempfile.mkdtemp(prefix=".feedback-init-", dir=parent))
        try:
            (staging / "project.json").write_text(canonical_json({"schema_version": PROJECT_SCHEMA,
                "project_id": uuid.uuid4().hex, "recording_environment": self.environment}))
            (staging / "private.key").write_bytes(secrets.token_bytes(32))
            (staging / ".gitignore").write_text("*\n")
            # The connection's transaction context does not close its file.
            # Windows requires that handle released before directory rename.
            with closing(sqlite3.connect(staging / "events.sqlite3")) as db, db:
                db.executescript("""
                    CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, origin TEXT NOT NULL, environment TEXT NOT NULL,
                    source_event_id TEXT UNIQUE, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
                    CREATE TABLE state (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
                """)
            for path in staging.iterdir():
                path.chmod(0o600)
            staging.rename(self.folder)
        except OSError:
            _fail()
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.db.close()

    @staticmethod
    def _event(row):
        item = dict(row)
        item["payload"] = parse_json(item.pop("payload_json"))
        return item

    @staticmethod
    def _receipt(event):
        return {k: event[k] for k in ("event_id", "seq", "recorded_at", "event_hash")}

    @staticmethod
    def _hash(event):
        return hashlib.sha256(canonical_json({k: v for k, v in event.items() if k != "event_hash"}).encode()).hexdigest()

    def fingerprint(self, source_identity: str) -> str:
        return hmac.new(self.key, source_identity.encode(), hashlib.sha256).hexdigest()

    def register_source(self, source_alias, fingerprint):
        if not re.fullmatch(ID_PATTERN, source_alias) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            _fail()
        with self.transaction():
            previous = self._state()[0].get(source_alias)
            if previous is not None and previous != fingerprint:
                _fail("SOURCE_CHANGED")
            payload = {"source_alias": source_alias, "fingerprint": fingerprint}
            self._insert(self._meta_record("source", payload))

    def _meta_record(self, kind, payload):
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        return dict(event_id=f"_meta:{kind}:{digest}", kind="_" + kind, payload=payload,
                    origin="captured", environment="paper", source_event_id=None)

    def append(self, event_id, kind, payload, *, origin="captured", environment="paper", source_event_id=None):
        return self.append_batch([dict(event_id=event_id, kind=kind, payload=payload, origin=origin,
                                      environment=environment, source_event_id=source_event_id)])[0]

    @contextmanager
    def transaction(self):
        """Serialize read-then-append constraints; nested store calls share it."""
        if self.readonly:
            _fail("READ_ONLY")
        own = not self.db.in_transaction
        try:
            if own:
                self.db.execute("BEGIN IMMEDIATE")
            yield
            if own:
                self.db.execute("COMMIT")
        except Exception:
            if own and self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def append_batch(self, records, *, checkpoint=None):
        if not isinstance(records, list) or len(records) > 10000:
            _fail("INVALID_BATCH")
        prepared = []
        for raw in records:
            if not isinstance(raw, dict) or set(raw) - {"event_id", "kind", "payload", "origin", "environment", "source_event_id"}:
                _fail("INVALID_BATCH")
            record = {"origin": "captured", "environment": "paper", "source_event_id": None, **raw}
            try:
                reject_sensitive_data(record)
            except ValueError:
                raise FeedbackError("SENSITIVE_DATA", "Remove private fields and recognized sensitive data") from None
            if not isinstance(record.get("event_id"), str) or not re.fullmatch(ID_PATTERN, record["event_id"]) or record["event_id"].startswith("_meta:"):
                _fail("INVALID_EVENT_ID")
            if record["origin"] not in {"captured", "imported", "broker"} or record["environment"] not in {"paper", "simulated", "live_import"}:
                _fail("INVALID_PROVENANCE")
            if record["source_event_id"] is not None and (not isinstance(record["source_event_id"], str) or len(record["source_event_id"]) > 384):
                _fail("INVALID_EVENT_ID")
            record["payload"] = validate_payload(record.get("kind"), record.get("payload"))
            prepared.append(record)
        if checkpoint is not None:
            canonical_json(checkpoint)
            if not isinstance(checkpoint, dict) or not re.fullmatch(ID_PATTERN, checkpoint.get("source_alias", "")):
                _fail("INVALID_CHECKPOINT")
        with self.transaction():
            self.verify_chain()
            receipts = [self._receipt(self._insert(record)) for record in prepared]
            if checkpoint is not None:
                self._insert(self._meta_record("checkpoint", checkpoint))
            return receipts

    def _insert(self, record):
        existing = self.db.execute("SELECT * FROM events WHERE event_id=? OR (source_event_id IS NOT NULL AND source_event_id=?)",
                                   (record["event_id"], record["source_event_id"])).fetchall()
        if existing:
            if len(existing) != 1:
                _fail("EVENT_CONFLICT")
            event = self._event(existing[0])
            if any(event[k] != record[k] for k in ("kind", "payload", "origin", "environment", "source_event_id")):
                _fail("EVENT_CONFLICT")
            return event
        last = self.db.execute("SELECT seq,event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        event = {**record, "seq": last["seq"] + 1 if last else 1,
                 "recorded_at": utc_time(self.clock()), "previous_hash": last["event_hash"] if last else ZERO}
        event["event_hash"] = self._hash(event)
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", (
            event["seq"], event["event_id"], event["kind"], canonical_json(event["payload"]),
            event["recorded_at"], event["origin"], event["environment"], event["source_event_id"],
            event["previous_hash"], event["event_hash"]))
        return event

    def verify_chain(self):
        previous, seq = ZERO, 0
        try:
            for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
                event = self._event(row)
                if event["seq"] != seq + 1 or event["previous_hash"] != previous or event["event_hash"] != self._hash(event):
                    _fail("INTEGRITY_ERROR")
                previous, seq = event["event_hash"], event["seq"]
        except (sqlite3.Error, ValueError, KeyError):
            _fail("INTEGRITY_ERROR")
        return {"status": "VERIFIED", "as_of_seq": seq, "head_hash": previous}

    def _state(self, events=None):
        source, sync = {}, {}
        if events is None:
            events = [self._event(r) for r in self.db.execute("SELECT * FROM events WHERE kind IN ('_source','_checkpoint') ORDER BY seq")]
        for e in events:
            p = e["payload"]
            if e["kind"] == "_source":
                source[p["source_alias"]] = p["fingerprint"]
            elif e["kind"] == "_checkpoint":
                sync[p["source_alias"]] = p
        return source, sync

    def snapshot(self, *, as_of_seq=None):
        own = not self.db.in_transaction
        try:
            if own:
                self.db.execute("BEGIN")
            integrity = self.verify_chain()
            seq = integrity["as_of_seq"] if as_of_seq is None else as_of_seq
            if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq <= integrity["as_of_seq"]:
                _fail("INVALID_SEQUENCE")
            events = [self._event(r) for r in self.db.execute("SELECT * FROM events WHERE seq<=? ORDER BY seq", (seq,))]
            source, sync = self._state(events)
            return {"schema_version": "tradeoff.feedback-snapshot.v1", "project_id": self.metadata["project_id"],
                "as_of_seq": seq, "head_hash": events[-1]["event_hash"] if events else ZERO,
                "events": events, "source_state": source, "sync_state": sync}
        finally:
            if own and self.db.in_transaction:
                self.db.execute("ROLLBACK")
