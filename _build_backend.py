"""Setuptools backend with anonymous, reproducible source archive headers.

Only the sdist container metadata changes. Wheel and editable build hooks
delegate to setuptools, and archive contents, paths and modes are preserved.
"""

import gzip
import os
from pathlib import Path
import tarfile
import tempfile

from setuptools import build_meta as _setuptools


def __getattr__(name):
    return getattr(_setuptools, name)


def _normalize_sdist(archive_path: Path) -> None:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    private_fields = {"uid", "gid", "uname", "gname", "atime", "ctime", "mtime", "creationtime"}
    replacement = None
    try:
        with tempfile.NamedTemporaryFile(dir=archive_path.parent, delete=False) as temporary:
            replacement = Path(temporary.name)
            with tarfile.open(archive_path, "r:gz") as source:
                with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=epoch) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                        for member in source:
                            member.uid = member.gid = 0
                            member.uname = member.gname = ""
                            member.mtime = epoch
                            member.pax_headers = {
                                key: value for key, value in member.pax_headers.items()
                                if key.rsplit(".", 1)[-1] not in private_fields
                            }
                            content = source.extractfile(member) if member.isfile() else None
                            target.addfile(member, content)
        replacement.chmod(archive_path.stat().st_mode & 0o777)
        replacement.replace(archive_path)
    finally:
        if replacement is not None:
            replacement.unlink(missing_ok=True)


def build_sdist(sdist_directory, config_settings=None):
    filename = _setuptools.build_sdist(sdist_directory, config_settings)
    _normalize_sdist(Path(sdist_directory) / filename)
    return filename
