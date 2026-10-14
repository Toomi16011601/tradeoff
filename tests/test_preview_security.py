"""Preview boundary checks using real handlers and synthetic in-memory HTTP."""
import base64
import hashlib
from http.client import HTTPResponse
from io import BytesIO
import os
from types import SimpleNamespace

import pytest

from backtest_witness import cli


class MemoryConnection:
    def __init__(self, request):
        self.request = BytesIO(request)
        self.response = BytesIO()

    def makefile(self, *_args, **_kwargs):
        return self.request

    def sendall(self, data):
        self.response.write(data)


def request_preview(monkeypatch, folder, path="/", *, method="GET", headers=None,
                    address="127.0.0.1", peer="127.0.0.1", port=8765,
                    requested_port=None, before_request=None):
    requested_port = port if requested_port is None else requested_port
    headers = [("Host", f"127.0.0.1:{port}")] if headers is None else headers
    raw = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers) + "\r\n"
    connection = MemoryConnection(raw.encode("ascii"))

    class MemoryServer:
        def __init__(self, binding, handler):
            assert binding == ("127.0.0.1", requested_port)
            self.server_address = (address, port)
            self.server_port = port
            self.handler = handler

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def serve_forever(self):
            if before_request:
                before_request()
            self.handler(connection, (peer, 12345), self)

    monkeypatch.setattr(cli, "ThreadingHTTPServer", MemoryServer)
    assert cli._serve(SimpleNamespace(directory=str(folder), port=requested_port)) == 0
    response = HTTPResponse(MemoryConnection(connection.response.getvalue()), method=method)
    response.begin()
    return response, response.read()


@pytest.fixture
def report_root(tmp_path):
    root = tmp_path / "report"
    root.mkdir()
    (root / "index.html").write_text("<h1>SYNTHETIC_REPORT</h1>")
    (root / "report.json").write_text('{"synthetic": true}')
    return root


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_preview_refuses_symlinks(monkeypatch, report_root, tmp_path, method, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.json").write_text("SYNTHETIC_OUTSIDE_SECRET")
    if kind == "file":
        (report_root / "receipt.json").symlink_to(outside / "report.json")
        path = "/receipt.json"
    else:
        (report_root / "case").symlink_to(outside, target_is_directory=True)
        path = "/case/report.json"
    response, body = request_preview(monkeypatch, report_root, path, method=method)
    assert response.status == 404
    assert b"SYNTHETIC_OUTSIDE_SECRET" not in body


@pytest.mark.parametrize("headers", [
    [], [("Host", "attacker.invalid")], [("Host", "localhost:8765")],
    [("Host", "127.0.0.1:9999")], [("Host", "127.0.0.1:8765"), ("Host", "attacker.invalid")],
    [("Host", "127.0.0.1:8765"), ("Origin", "https://attacker.invalid")],
    [("Host", "127.0.0.1:8765"), ("Origin", "null")],
    [("Host", "127.0.0.1:8765"), ("Origin", "http://127.0.0.1:9999")],
    [("Host", "127.0.0.1:8765"), ("Origin", "http://127.0.0.1:8765"), ("Origin", "http://127.0.0.1:8765")],
])
def test_preview_refuses_unexpected_host_or_origin(monkeypatch, report_root, headers):
    response, body = request_preview(monkeypatch, report_root, headers=headers)
    assert response.status == 403
    assert b"SYNTHETIC_REPORT" not in body


@pytest.mark.parametrize("address,peer", [("0.0.0.0", "127.0.0.1"), ("192.0.2.1", "127.0.0.1"), ("127.0.0.1", "192.0.2.1")])
def test_preview_refuses_nonlocal_server_or_peer(monkeypatch, report_root, address, peer):
    response, _body = request_preview(monkeypatch, report_root, address=address, peer=peer)
    assert response.status == 403


@pytest.mark.parametrize("path", [
    "/notes.txt", "/.env", "/.hidden/report.json", "/case/../report.json",
    "/%2e%2e/report.json", "/case/%2e%2e/report.json", "/%252e%252e/report.json",
    "/case%5creport.json", "/%00report.json", "/case//report.json",
    "http://attacker.invalid/report.json",
])
def test_preview_refuses_nonartifacts_and_traversal(monkeypatch, report_root, path):
    (report_root / "notes.txt").write_text("SYNTHETIC_PRIVATE_NOTES")
    (report_root / ".env").write_text("SYNTHETIC_PRIVATE_NOTES")
    hidden = report_root / ".hidden"
    hidden.mkdir()
    (hidden / "report.json").write_text("SYNTHETIC_PRIVATE_NOTES")
    response, body = request_preview(monkeypatch, report_root, path)
    assert response.status == 404
    assert b"SYNTHETIC_PRIVATE_NOTES" not in body


def test_preview_never_lists_directories(monkeypatch, report_root):
    case = report_root / "case"
    case.mkdir()
    (case / "report.json").write_text("{}")
    response, body = request_preview(monkeypatch, report_root, "/case/")
    assert response.status == 404
    assert b"Directory listing" not in body


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_preview_serves_report_with_security_headers(monkeypatch, report_root, method):
    response, body = request_preview(monkeypatch, report_root, method=method,
        headers=[("Host", "127.0.0.1:8765"), ("Origin", "http://127.0.0.1:8765")])
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("Referrer-Policy") == "no-referrer"
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Access-Control-Allow-Origin") is None
    policy = response.getheader("Content-Security-Policy")
    assert "default-src 'none'" in policy
    assert "connect-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "'unsafe-inline'" not in policy
    assert body == (b"<h1>SYNTHETIC_REPORT</h1>" if method == "GET" else b"")


def test_preview_uses_actual_port_and_serves_case_download(monkeypatch, report_root):
    case = report_root / "synthetic-case"
    case.mkdir()
    (case / "test_failure_resilience.py").write_text("# SYNTHETIC_TEST")
    response, body = request_preview(monkeypatch, report_root,
        "/synthetic-case/test_failure_resilience.py", port=54321, requested_port=0)
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/plain; charset=utf-8"
    assert body == b"# SYNTHETIC_TEST"


def test_preview_csp_allows_only_packaged_inline_assets(monkeypatch, report_root):
    from importlib.resources import files
    response, _body = request_preview(monkeypatch, report_root)
    policy = response.getheader("Content-Security-Policy")
    assert policy is not None
    for name in ("report.js", "failure.js", "report.css", "failure.css"):
        content = files("backtest_witness.report").joinpath("assets", name).read_text(encoding="utf-8")
        digest = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in policy


def test_preview_errors_have_security_headers_without_local_paths(monkeypatch, report_root):
    response, body = request_preview(monkeypatch, report_root, "/missing.json")
    assert response.status == 404
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert str(report_root).encode() not in body


def test_preview_refuses_named_pipes_without_waiting(monkeypatch, report_root):
    os.mkfifo(report_root / "receipt.json")
    response, _body = request_preview(monkeypatch, report_root, "/receipt.json")
    assert response.status == 404


def test_preview_refuses_root_replaced_with_symlink(monkeypatch, report_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.json").write_text("SYNTHETIC_OUTSIDE_SECRET")

    def replace_root():
        report_root.rename(tmp_path / "saved-report")
        report_root.symlink_to(outside, target_is_directory=True)

    response, body = request_preview(monkeypatch, report_root, "/report.json", before_request=replace_root)
    assert response.status == 404
    assert b"SYNTHETIC_OUTSIDE_SECRET" not in body


def test_preview_refuses_root_ancestor_replaced_with_symlink(monkeypatch, tmp_path):
    parent = tmp_path / "parent"
    root = parent / "report"
    root.mkdir(parents=True)
    (root / "report.json").write_text("SYNTHETIC_REPORT")
    outside = tmp_path / "outside"
    (outside / "report").mkdir(parents=True)
    (outside / "report" / "report.json").write_text("SYNTHETIC_OUTSIDE_SECRET")

    def replace_ancestor():
        parent.rename(tmp_path / "saved-parent")
        parent.symlink_to(outside, target_is_directory=True)

    response, body = request_preview(monkeypatch, root, "/report.json", before_request=replace_ancestor)
    assert response.status == 404
    assert b"SYNTHETIC_OUTSIDE_SECRET" not in body


def test_preview_fails_closed_without_secure_open_support(monkeypatch, report_root):
    monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(ValueError, match="Secure preview requires.*macOS.*Linux"):
        request_preview(monkeypatch, report_root)


@pytest.mark.parametrize("artifact", [
    "index.html", "report.json", "receipt.json", "reproducer.json",
    "test_future_invariance.py", "failure-fixture.json", "failure-receipt.json",
    "test_failure_resilience.py", "case-results.json",
])
def test_preview_serves_supported_artifacts(monkeypatch, report_root, artifact):
    (report_root / artifact).write_text("SYNTHETIC_ARTIFACT")
    response, body = request_preview(monkeypatch, report_root, "/" + artifact)
    assert response.status == 200
    assert body == b"SYNTHETIC_ARTIFACT"
