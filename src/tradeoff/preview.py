"""Loopback-only preview of known report artifacts, without directory listing."""
from __future__ import annotations

import base64
import errno
import hashlib
from http.server import SimpleHTTPRequestHandler
from importlib.resources import files
from ipaddress import ip_address
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


REPORT_ARTIFACTS = frozenset({
    "index.html", "report.json", "receipt.json", "reproducer.json",
    "test_future_invariance.py", "failure-fixture.json", "failure-receipt.json",
    "test_failure_resilience.py", "case-results.json",
})


def require_secure_preview_support():
    if (os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NONBLOCK")):
        raise ValueError("Secure preview requires no-follow directory opening, supported on macOS and Linux")


def preview_content_security_policy():
    """Authorize the packaged inline assets, never scripts from report contents."""
    assets = files("tradeoff.report").joinpath("assets")

    def hashes(names):
        return " ".join("'sha256-" + base64.b64encode(hashlib.sha256(
            assets.joinpath(name).read_text(encoding="utf-8").encode("utf-8")
        ).digest()).decode("ascii") + "'" for name in names)

    return ("default-src 'none'; script-src " + hashes(("report.js", "failure.js"))
            + "; style-src " + hashes(("report.css", "failure.css"))
            + "; connect-src 'none'; img-src 'none'; object-src 'none'; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class PreviewHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serve only regular report artifacts beneath a selected report root.

    Directory descriptors and O_NOFOLLOW protect every absolute-root ancestor,
    case directory and file even if an entry changes during opening.
    Platforms without these secure-open primitives fail closed.
    """

    server_version = "TradeoffPreview"
    sys_version = ""

    def __init__(self, *args, directory, **kwargs):
        # The CLI resolves the selected root once. Resolving it again here would
        # follow a symlink substituted after startup and bypass O_NOFOLLOW.
        self.report_root = Path(directory).absolute()
        self.content_security_policy = preview_content_security_policy()
        super().__init__(*args, directory=str(self.report_root), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", self.content_security_policy)
        super().end_headers()

    def _local_request(self):
        try:
            host, port = self.server.server_address[:2]
            if host != "127.0.0.1" or not ip_address(self.client_address[0]).is_loopback:
                return False
            authority = f"127.0.0.1:{port}"
            hosts = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            return (hosts == [authority]
                    and (not origins or origins == [f"http://{authority}"]))
        except (AttributeError, TypeError, ValueError):
            return False

    def _artifact_parts(self):
        try:
            target = urlsplit(self.path)
            if target.scheme or target.netloc or target.fragment:
                return None
            path = unquote(target.path, encoding="utf-8", errors="strict")
        except (UnicodeError, ValueError):
            return None
        if not path.startswith("/"):
            return None
        if path.endswith("/"):
            path += "index.html"
        parts = path[1:].split("/")
        if (not parts or parts[-1] not in REPORT_ARTIFACTS
                or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part)
                       or part in {".", ".."} for part in parts)):
            return None
        return parts

    def _open_artifact(self, parts):
        require_secure_preview_support()
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors = []
        try:
            # An absolute pathname open would follow symlinks in its ancestors.
            # Start at the filesystem root and open every component no-follow.
            descriptors.append(os.open(self.report_root.anchor, directory_flags))
            for part in (*self.report_root.parts[1:], *parts[:-1]):
                descriptors.append(os.open(part, directory_flags, dir_fd=descriptors[-1]))
            # O_NONBLOCK avoids waiting forever on a named pipe with an artifact name.
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=descriptors[-1])
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OSError(errno.EACCES, "Not a regular report artifact")
                stream = os.fdopen(descriptor, "rb")
            except BaseException:
                os.close(descriptor)
                raise
            return stream
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def send_head(self):
        if not self._local_request():
            self.send_error(403, "Local preview request required")
            return None
        parts = self._artifact_parts()
        if parts is None:
            self.send_error(404, "Report artifact not found")
            return None
        try:
            stream = self._open_artifact(parts)
            size = os.fstat(stream.fileno()).st_size
        except (OSError, ValueError):
            self.send_error(404, "Report artifact not found")
            return None
        content_type = ("text/html; charset=utf-8" if parts[-1] == "index.html" else
                        "application/json; charset=utf-8" if parts[-1].endswith(".json") else
                        "text/plain; charset=utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        return stream
