from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, BinaryIO

from app.core.config import get_settings, DATA_DIR
from app.db.session import engine, Base

logger = logging.getLogger("app.services.backup")


def _human_size(n: int) -> str:
    """Return a short human-readable size (e.g., 1.2 MB)."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for u in units:
        if size < 1024.0 or u == units[-1]:
            return f"{size:.1f} {u}" if u != "B" else f"{int(size)} {u}"
        size /= 1024.0


def backups_dir() -> Path:
    p = DATA_DIR / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    settings = get_settings()
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        marker = ":///"
        idx = url.find(marker)
        if idx != -1:
            return Path(url[idx + len(marker) :])
    # Fallback
    return DATA_DIR / "app.db"


def list_backups() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for f in sorted(backups_dir().glob("backup-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        out.append(
            {
                "name": f.name,
                "size": str(st.st_size),
                "size_hr": _human_size(st.st_size),
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return out


def create_backup() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups_dir() / f"backup-{ts}.tar.gz"

    db_file = db_path()
    avatars = DATA_DIR / "avatars"

    with tarfile.open(dest.as_posix(), "w:gz") as tar:
        if db_file.exists():
            tar.add(db_file.as_posix(), arcname="app.db")
        if avatars.exists():
            tar.add(avatars.as_posix(), arcname="avatars")
    logger.info("Created backup at %s", dest)
    return dest


def prune_backups(keep_latest: int | None = None) -> None:
    """Keep only the N most recent backup-*.tar.gz files. If keep_latest is None,
    use settings.BACKUPS_KEEP_LATEST; if 0 or negative, do nothing.
    """
    settings = get_settings()
    if keep_latest is None:
        keep_latest = int(getattr(settings, "BACKUPS_KEEP_LATEST", 0) or 0)
    if keep_latest <= 0:
        return
    files = sorted(backups_dir().glob("backup-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    to_delete = files[keep_latest:]
    for f in to_delete:
        try:
            f.unlink(missing_ok=True)  # type: ignore[call-arg]
            logger.info("Pruned old backup %s", f)
        except Exception:
            logger.exception("Failed to prune backup %s", f)


def _has_sqlite_header(chunk: bytes) -> bool:
    return b"SQLite format 3\x00" in chunk[:100]


def restore_sqlite_db_from_fileobj(fileobj: BinaryIO) -> Path:
    """Replace the current SQLite DB from a file-like object.
    Returns the path to the pre-restore copy if one was made.
    """
    # Dispose connections before replacing file
    try:
        engine.dispose()
    except Exception:
        logger.exception("Engine dispose failed before restore")

    # Validate header
    pos = fileobj.tell()
    head = fileobj.read(100)
    fileobj.seek(pos)
    if not _has_sqlite_header(head):
        raise ValueError("Invalid SQLite file header")

    target = db_path()
    bdir = backups_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prev_copy = bdir / f"pre-restore-{ts}.db"

    if target.exists():
        shutil.copy2(target.as_posix(), prev_copy.as_posix())

    with open(target.as_posix(), "wb") as out:
        shutil.copyfileobj(fileobj, out)

    logger.warning("Database restored from upload; previous copy saved at %s", prev_copy)
    return prev_copy


def _safe_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        if not str(member_path).startswith(str(dest)):
            raise ValueError("Unsafe path in archive")
    tar.extractall(path=dest.as_posix())


def restore_from_archive(fileobj: BinaryIO) -> Path:
    """Restore DB and avatars from a backup .tar.gz created by create_backup().
    Returns the path to the pre-restore DB copy.
    """
    # Write to a temp file first to let tarfile inspect it safely
    tmp_tar = None
    tmp_dir = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tf:
            tmp_tar = Path(tf.name)
            shutil.copyfileobj(fileobj, tf)

        # Extract into temp dir
        tmp_dir = Path(tempfile.mkdtemp(prefix="restore-"))
        with tarfile.open(tmp_tar.as_posix(), "r:gz") as tar:
            _safe_extract_tar(tar, tmp_dir)

        # Validate extracted DB
        extracted_db = tmp_dir / "app.db"
        if not extracted_db.exists():
            raise ValueError("Archive missing app.db")
        with open(extracted_db.as_posix(), "rb") as fh:
            head = fh.read(100)
            if not _has_sqlite_header(head):
                raise ValueError("Invalid SQLite file in archive")

        # Dispose connections before replacing
        try:
            engine.dispose()
        except Exception:
            logger.exception("Engine dispose failed before archive restore")

        # Backup current DB
        target = db_path()
        bdir = backups_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prev_copy = bdir / f"pre-restore-{ts}.db"
        if target.exists():
            shutil.copy2(target.as_posix(), prev_copy.as_posix())

        # Optionally back up current avatars as a tar.gz
        avatars_dir = DATA_DIR / "avatars"
        if avatars_dir.exists():
            prev_avatars = bdir / f"pre-restore-{ts}-avatars.tar.gz"
            with tarfile.open(prev_avatars.as_posix(), "w:gz") as tar:
                tar.add(avatars_dir.as_posix(), arcname="avatars")

        # Replace DB
        with open(target.as_posix(), "wb") as out:
            with open(extracted_db.as_posix(), "rb") as src:
                shutil.copyfileobj(src, out)

        # Replace avatars if present in archive
        extracted_avatars = tmp_dir / "avatars"
        if extracted_avatars.exists() and extracted_avatars.is_dir():
            # Remove existing avatars dir then move extracted
            if avatars_dir.exists():
                shutil.rmtree(avatars_dir.as_posix())
            shutil.move(extracted_avatars.as_posix(), avatars_dir.as_posix())

        logger.warning("Database and avatars restored from archive; previous DB saved at %s", prev_copy)
        return prev_copy
    finally:
        # Cleanup
        try:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir.as_posix(), ignore_errors=True)
        except Exception:
            logger.exception("Failed cleaning up temp restore dir: %s", tmp_dir)
        try:
            if tmp_tar and tmp_tar.exists():
                os.unlink(tmp_tar.as_posix())
        except Exception:
            logger.exception("Failed removing temp tar: %s", tmp_tar)


def clear_database() -> None:
    try:
        engine.dispose()
    except Exception:
        logger.exception("Engine dispose failed before clear")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    logger.warning("Database cleared (all tables dropped and recreated)")
