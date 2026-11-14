"""Atomic project publication must not retain a staging SQLite handle."""
from pathlib import Path
import sqlite3


def test_initialization_closes_database_before_publishing_project(monkeypatch, tmp_path):
    from tradeoff.feedback.store import FeedbackStore

    connections = []
    connect, rename = sqlite3.connect, Path.rename

    def track_connection(database, *args, **kwargs):
        connection = connect(database, *args, **kwargs)
        if Path(database).parent.name.startswith('.feedback-init-'):
            connections.append(connection)
        return connection

    def publish(source, target):
        if source.name.startswith('.feedback-init-'):
            assert len(connections) == 1
            for connection in connections:
                try:
                    connection.execute('SELECT 1')
                except sqlite3.ProgrammingError:
                    continue
                # Windows refuses to rename the directory while its SQLite
                # file is open. Enforce that OS boundary on every test host.
                raise PermissionError('Staging SQLite connection is still open')
        return rename(source, target)

    monkeypatch.setattr(sqlite3, 'connect', track_connection)
    monkeypatch.setattr(Path, 'rename', publish)
    with FeedbackStore(tmp_path, create=True) as store:
        assert store.snapshot()['events'] == []
    assert (tmp_path / '.tradeoff/feedback/events.sqlite3').is_file()
