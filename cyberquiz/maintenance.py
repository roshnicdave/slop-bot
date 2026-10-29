"""Bounded local retention and crash-safe database backups; no inference."""
import datetime as dt
import json
import shutil
from .store import ROOT,now,config


def cleanup(db):
    stamp=dt.datetime.now(dt.timezone.utc);removed=[]
    # Confirmed receipt is mandatory: container creation/upload alone is not
    # publication. Keep a short grace period for remote media fetch completion.
    for row in db.execute('SELECT id,media_id,published_at FROM jobs WHERE status="published" AND media_id IS NOT NULL AND published_at IS NOT NULL'):
        if (stamp-dt.datetime.fromisoformat(row['published_at'])).total_seconds()<3600:continue
        if len(row['id'])!=12 or any(c not in '0123456789abcdef' for c in row['id']):continue
        folder=ROOT/'out'/row['id']
        if not folder.is_dir():continue
        for item in folder.iterdir():
            if item.name in ('plan.json','timing.json','caption.txt','quality.json','receipt.json'):continue
            if item.is_dir():shutil.rmtree(item)
            else:item.unlink()
            removed.append(str(item.relative_to(ROOT)))
        (folder/'receipt.json').write_text(json.dumps({'media_id':row['media_id'],'published_at':row['published_at'],'media_cleaned_at':now()}))
    # Disposable frame sequences from failed/held jobs must not fill 20GB disk.
    # Keep voice + plan to recover without paying/inferencing twice.
    for folder in (ROOT/'out').glob('*/frames'):
        if stamp.timestamp()-folder.stat().st_mtime>86400:shutil.rmtree(folder)
    return removed


def backup(db):
    import sqlite3
    folder=ROOT/'data'/'backups';folder.mkdir(exist_ok=True)
    day=dt.datetime.now(dt.timezone.utc).date().isoformat();path=folder/(day+'.sqlite')
    if not path.exists():
        temp=path.with_suffix('.tmp')
        with sqlite3.connect(temp) as target:db.backup(target)
        temp.replace(path)
    for old in sorted(folder.glob('*.sqlite'))[:-7]:old.unlink()
    return path
