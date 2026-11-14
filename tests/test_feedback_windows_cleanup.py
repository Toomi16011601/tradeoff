"""Windows probe cleanup must never execute a workspace-selected program."""
import ctypes
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("cleanup_failure", [False, True, "lookup"])
def test_windows_probe_cleanup_uses_system_tool_and_isolated_context(monkeypatch, cleanup_failure):
    from tradeoff.feedback import onboarding

    calls, killed = [], []
    trusted = r"C:\Windows\System32\taskkill.exe"

    class Process:
        pid = 4242
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def wait(self, timeout=None):
            if timeout is not None and not killed:
                raise subprocess.TimeoutExpired("synthetic-probe", timeout)
            return 0
        def kill(self): killed.append(self.pid)

    def cleanup(args, **kwargs):
        calls.append((args, kwargs))
        if cleanup_failure:
            raise subprocess.TimeoutExpired(args, 10)

    fake_os = SimpleNamespace(name="nt", path=os.path, fspath=os.fspath, access=os.access,
        X_OK=os.X_OK, environ={"PATH": "workspace-path", "SYSTEMROOT": r"C:\Windows",
                              "BROKER_API_TOKEN": "synthetic-do-not-forward"})
    monkeypatch.setattr(onboarding, "os", fake_os)
    def system_tool():
        if cleanup_failure == "lookup":
            raise OSError("synthetic system lookup failure")
        return trusted

    monkeypatch.setattr(onboarding, "_system_taskkill", system_tool, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(subprocess, "run", cleanup)
    result = onboarding.probe(sys.executable, timeout=0.01)
    assert result == {"status": "FAIL", "code": "PROBE_TIMEOUT"}
    assert killed == [4242]
    if cleanup_failure == "lookup":
        assert calls == []
        return
    args, options = calls[0]
    assert args == [trusted, "/PID", "4242", "/T", "/F"]
    assert PureWindowsPath(args[0]).is_absolute()
    assert Path(options["cwd"]).name.startswith("tradeoff-probe-")
    assert options["cwd"] != Path.cwd()
    assert options["env"] == {"PATH": "workspace-path", "SYSTEMROOT": r"C:\Windows"}
    assert options.get("shell", False) is False
    assert options["timeout"] == 10


@pytest.mark.parametrize("directory,reported_size", [
    (r"C:\Windows\System32", None), ("", 0), ("relative-system", None), ("unused", 32768),
])
def test_system_cleanup_path_comes_from_windows_api(monkeypatch, directory, reported_size):
    from tradeoff.feedback import onboarding

    class Lookup:
        def __call__(self, buffer, size):
            buffer.value = directory
            return len(directory) if reported_size is None else reported_size

    calls = []
    def load(name, **kwargs):
        calls.append((name, kwargs))
        return SimpleNamespace(GetSystemDirectoryW=Lookup())

    monkeypatch.setattr(ctypes, "WinDLL", load, raising=False)
    monkeypatch.setenv("SYSTEMROOT", "untrusted-workspace")
    if directory.startswith("C:") and reported_size is None:
        assert onboarding._system_taskkill() == r"C:\Windows\System32\taskkill.exe"
    else:
        with pytest.raises(OSError):
            onboarding._system_taskkill()
    assert calls == [("kernel32", {"use_last_error": True, "winmode": 0x800})]


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows process APIs")
def test_native_windows_system_cleanup_and_probe_timeout(tmp_path, monkeypatch):
    from tradeoff.feedback.onboarding import _system_taskkill, probe

    tool = Path(_system_taskkill())
    assert tool.is_absolute() and tool.name.lower() == "taskkill.exe" and tool.is_file()
    monkeypatch.chdir(tmp_path)
    # A project-local executable name must not be chosen during cleanup.
    (tmp_path / "taskkill.exe").write_bytes(b"not-an-executable")
    assert probe(sys.executable, timeout=0.001) == {"status": "FAIL", "code": "PROBE_TIMEOUT"}
