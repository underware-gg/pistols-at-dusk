from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


ARCHIVE_SUFFIX_RE = re.compile(r"^(?P<base>.+)-(?P<num>\d{4})$")


def archive_dir_for(output_path: Path) -> Path:
    return output_path.parent / "archive"


def _numbered_archive_path(output_path: Path, archive_dir: Path, number: int) -> Path:
    return archive_dir / f"{output_path.stem}-{number:04d}{output_path.suffix}"


def _next_archive_number(output_path: Path, archive_dir: Path) -> int:
    next_number = 1
    for candidate in archive_dir.glob(f"{output_path.stem}-*{output_path.suffix}"):
        match = ARCHIVE_SUFFIX_RE.match(candidate.stem)
        if match:
            next_number = max(next_number, int(match.group("num")) + 1)
    return next_number


def _files_match(left: Path, right: Path, *, chunk_size: int = 1024 * 1024) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False

    with left.open("rb") as left_file, right.open("rb") as right_file:
        while True:
            left_chunk = left_file.read(chunk_size)
            right_chunk = right_file.read(chunk_size)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def archive_existing_output(output_path: Path) -> Path | None:
    if not output_path.exists():
        return None

    archive_dir = archive_dir_for(output_path)
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = _numbered_archive_path(output_path, archive_dir, _next_archive_number(output_path, archive_dir))
    output_path.rename(target)
    return target


def create_staging_output_path(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{output_path.stem}-",
        suffix=output_path.suffix,
        dir=output_path.parent,
    )
    os.close(fd)
    return Path(raw_path)


def publish_staged_output(output_path: Path, staged_path: Path) -> Path:
    if output_path.exists() and _files_match(output_path, staged_path):
        staged_path.unlink()
        return output_path

    archive_existing_output(output_path)
    staged_path.replace(output_path)
    return output_path
