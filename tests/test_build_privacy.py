"""Source distributions must not disclose the local build account."""

import gzip
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile

import pytest


def _build_sdist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, epoch: int | None) -> Path:
    """Build the configured project in a disposable copy, with no network access."""
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "MANIFEST.in", "_build_backend.py", "LICENSE", "README.md"):
        source = root / name
        if source.exists():
            shutil.copy2(source, project / name)
    shutil.copytree(root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    if epoch is None:
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    else:
        monkeypatch.setenv("SOURCE_DATE_EPOCH", str(epoch))
    output = tmp_path / "artifacts"
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--sdist", "--outdir", str(output), str(project)],
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "The configured sdist backend failed to build"
    artifacts = list(output.glob("*.tar.gz"))
    assert len(artifacts) == 1
    return artifacts[0]


@pytest.mark.parametrize("epoch", [None, 946684800])
def test_configured_sdist_has_anonymous_owner_and_stable_timestamps(tmp_path, monkeypatch, epoch):
    # Bypassing normalization must fail even if the local account has UID zero.
    artifact = _build_sdist(tmp_path, monkeypatch, epoch)
    header = artifact.read_bytes()[:10]
    assert header[:3] == b"\x1f\x8b\x08"
    assert header[3] & 0x08 == 0, "The gzip header includes a source filename"
    assert struct.unpack("<I", header[4:8])[0] == (epoch or 0), "The gzip timestamp is not stable"
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
        assert members
        assert all(member.uid == member.gid == 0 for member in members), "The archive includes local account IDs"
        assert all(member.uname == member.gname == "" for member in members), "The archive includes local account names"
        assert all(member.mtime == (epoch or 0) for member in members), "The archive includes local file timestamps"
        assert all(
            not {"uid", "gid", "uname", "gname", "atime", "ctime"}.intersection(member.pax_headers)
            for member in members
        ), "The archive includes personal PAX metadata"
        license_member = next(member for member in members if member.name.endswith("/LICENSE"))
        assert archive.extractfile(license_member).read() == (Path(__file__).resolve().parents[1] / "LICENSE").read_bytes()
    with gzip.open(artifact, "rb") as compressed:
        assert compressed.read(512), "The source archive is empty"


def test_archive_normalization_preserves_payload_modes_and_links(tmp_path, monkeypatch):
    """Characterize the tar boundary so privacy filtering cannot damage payloads."""
    from _build_backend import _normalize_sdist

    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    artifact = tmp_path / "source.tar.gz"
    long_path = "source/" + "nested/" * 20 + "fixture.py"
    with tarfile.open(artifact, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        directory = tarfile.TarInfo("source")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        member = tarfile.TarInfo(long_path)
        member.uid, member.gid = 123, 456
        member.uname, member.gname = "synthetic-user", "synthetic-group"
        member.mode = 0o751
        member.mtime = 123456789
        member.pax_headers = {
            "uid": "123", "gid": "456", "uname": "synthetic-user", "gname": "synthetic-group",
            "atime": "123456789", "ctime": "123456789", "mtime": "123456789",
            "SCHILY.uid": "123", "SCHILY.gid": "456", "SCHILY.uname": "synthetic-user",
            "SCHILY.gname": "synthetic-group", "LIBARCHIVE.creationtime": "123456789",
        }
        payload = b"print('synthetic fixture')\n"
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
        link = tarfile.TarInfo("source/fixture-link")
        link.type = tarfile.SYMTYPE
        link.linkname = long_path.removeprefix("source/")
        archive.addfile(link)

    _normalize_sdist(artifact)

    with tarfile.open(artifact, "r:gz") as archive:
        assert archive.getnames() == ["source", long_path, "source/fixture-link"]
        assert archive.extractfile(long_path).read() == b"print('synthetic fixture')\n"
        assert archive.getmember(long_path).mode == 0o751
        assert archive.getmember("source").mode == 0o755
        assert archive.getmember("source/fixture-link").issym()
        assert archive.getmember("source/fixture-link").linkname == long_path.removeprefix("source/")
        assert all(member.uid == member.gid == 0 for member in archive), "Synthetic ownership survived normalization"
        assert all(member.uname == member.gname == "" for member in archive), "Synthetic owner names survived normalization"
        assert not {
            "uid", "gid", "uname", "gname", "atime", "ctime", "mtime",
            "SCHILY.uid", "SCHILY.gid", "SCHILY.uname", "SCHILY.gname", "LIBARCHIVE.creationtime",
        }.intersection(archive.getmember(long_path).pax_headers), "Private PAX metadata survived normalization"


def test_normalized_sdist_can_build_a_wheel_in_a_clean_directory(tmp_path, monkeypatch):
    artifact = _build_sdist(tmp_path, monkeypatch, None)
    extracted = tmp_path / "extracted"
    with tarfile.open(artifact, "r:gz") as archive:
        # Test input is produced by the configured local backend, not an untrusted archive.
        archive.extractall(extracted, filter="data")
    project = next(extracted.iterdir())
    wheel_output = tmp_path / "wheels"
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(wheel_output), str(project)],
        cwd=extracted,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "The normalized sdist cannot build a wheel independently"
    wheels = list(wheel_output.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "tradeoff/__init__.py" in archive.namelist()
        assert any(name.endswith("/licenses/LICENSE") for name in archive.namelist())
