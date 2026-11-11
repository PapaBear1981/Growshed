"""Backups of everything that cannot be recreated: the database, config.yaml and photos.

Two kinds:
- A nightly snapshot of the database and config into the backup folder (the last 14 are
  kept). On the same disk this protects against mistakes and corruption, not a dead disk.
- A full export (one zip, photos included) to download from the GUI and keep somewhere
  else. That is the one that survives the Pi's SSD failing.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

KEEP = 14


def _snapshot(conn: sqlite3.Connection, target: Path) -> None:
    """A consistent copy of the live database (SQLite's own online backup)."""
    copy = sqlite3.connect(str(target))
    try:
        conn.backup(copy)
    finally:
        copy.close()


def run_backup(conn: sqlite3.Connection, backup_dir: Path, config_path: Path, now: float) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    target = backup_dir / f"growshed-{stamp}.db"
    _snapshot(conn, target)
    if config_path.is_file():
        shutil.copy2(config_path, backup_dir / f"config-{stamp}.yaml")
    for pattern in ("growshed-*.db", "config-*.yaml"):
        for old in sorted(backup_dir.glob(pattern))[:-KEEP]:
            old.unlink(missing_ok=True)
    return target


def list_backups(backup_dir: Path) -> list[dict]:
    if not backup_dir.is_dir():
        return []
    files = sorted(backup_dir.glob("growshed-*.db"), reverse=True)
    return [{"name": f.name, "size": f.stat().st_size, "ts": int(f.stat().st_mtime)} for f in files]


def export_zip(conn: sqlite3.Connection, config_path: Path, photos_dir: Path) -> Path:
    """Build one zip with the database, config.yaml and every photo. Caller deletes it."""
    folder = Path(tempfile.mkdtemp(prefix="growshed-export-"))
    snapshot = folder / "growshed.db"
    _snapshot(conn, snapshot)
    archive = folder / "growshed-backup.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snapshot, "growshed.db")
        if config_path.is_file():
            zf.write(config_path, "config.yaml")
        if photos_dir.is_dir():
            for photo in sorted(photos_dir.iterdir()):
                if photo.is_file():
                    zf.write(photo, f"photos/{photo.name}")
    snapshot.unlink()
    return archive
