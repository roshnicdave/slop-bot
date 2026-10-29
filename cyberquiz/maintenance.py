"""Bounded local retention and crash-safe database backups; no inference."""

import datetime as dt
import json
import shutil
from .store import ROOT, now


def erase_media(folder):
    """Keep text audit files; media is only a staging artifact."""
    removed = []
    if not folder.is_dir():
        return removed
    for item in folder.iterdir():
        if item.suffix.lower() in (".json", ".txt", ".srt"):
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removed.append(str(item.relative_to(ROOT)))
    return removed


def cleanup(db):
    stamp = dt.datetime.now(dt.timezone.utc)
    removed = []
    # Confirmed publication means Meta has finished consuming the media.
    for row in db.execute(
        'SELECT id,media_id,published_at FROM jobs WHERE status="published" AND media_id IS NOT NULL AND published_at IS NOT NULL'
    ):
        if len(row["id"]) != 12 or any(c not in "0123456789abcdef" for c in row["id"]):
            continue
        folder = ROOT / "out" / row["id"]
        if not folder.is_dir():
            continue
        removed.extend(erase_media(folder))
        (folder / "receipt.json").write_text(
            json.dumps(
                {
                    "media_id": row["media_id"],
                    "published_at": row["published_at"],
                    "media_cleaned_at": now(),
                }
            )
        )
    for row in db.execute(
        'SELECT id FROM jobs WHERE status IN ("rejected","held_quality","held_provider","failed")'
    ):
        removed.extend(erase_media(ROOT / "out" / row["id"]))
    # Disposable frame sequences from failed/held jobs must not fill 20GB disk.
    # Keep voice + plan to recover without paying/inferencing twice.
    for folder in (ROOT / "out").glob("*/frames"):
        if stamp.timestamp() - folder.stat().st_mtime > 86400:
            shutil.rmtree(folder)
    return removed


def backup(db):
    import sqlite3

    folder = ROOT / "data" / "backups"
    folder.mkdir(exist_ok=True)
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    path = folder / (day + ".sqlite")
    if not path.exists():
        temp = path.with_suffix(".tmp")
        with sqlite3.connect(temp) as target:
            db.backup(target)
        temp.replace(path)
    for old in sorted(folder.glob("*.sqlite"))[:-7]:
        old.unlink()
    return path
