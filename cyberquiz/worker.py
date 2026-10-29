"""Durable production inbox. Telegram/chat stay in separate processes."""
import datetime as dt
import fcntl
import json
import time

from .store import ROOT,connect,config,transaction,now,worker_lock
from .telegram import tables,send,video,notify


def run(db,row):
    ident=row['id'];user=row['user_id'];command=row['command'];parts=command.split(maxsplit=1)
    try:
        if parts[0]=='/next':
            from .production import make
            # An update ID is a stable idempotency key, not a new job on retry.
            slot='telegram:'+str(ident)
            existing=db.execute('SELECT id,status FROM jobs WHERE slot=?',(slot,)).fetchone()
            if existing:
                send(user,'That request already has job '+existing['id']+' ('+existing['status']+'). No second generation was submitted.')
            else:
                try:scene_key=json.loads(row['result'] or '{}').get('scene_key')
                except ValueError:scene_key=None
                job=make(db,slot=slot,scene_key=scene_key)
                if db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()[0]=='rendered':video(user,job)
        elif parts[0]=='/preview':
            job=parts[1].strip() if len(parts)>1 else ''
            if not job:
                latest=db.execute('SELECT id FROM jobs WHERE status="rendered" ORDER BY created DESC LIMIT 1').fetchone();job=latest[0] if latest else ''
            if job:video(user,job)
            else:send(user,'No reviewed-format video is ready yet. I can make the first visual one when you ask.')
        elif parts[0]=='/research':
            from .scout import daily
            result=daily(db)
            send(user,'Today’s editorial research:\n'+'\n'.join(i['key']+': '+i['hook_reason'] for i in result['ideas'])+
                '\n\nNext experiment: '+result.get('next_experiment','')+'\n\nEvidence: '+str(len(result['evidence']['records']))+' source records; competitor performance is not a connected feed.')
        db.execute('UPDATE telegram_updates SET status="done" WHERE id=?',(ident,));db.commit()
    except Exception as exc:
        db.execute('UPDATE telegram_updates SET status="failed",result=? WHERE id=?',(type(exc).__name__,ident));db.commit()
        send(user,'The job stopped ('+type(exc).__name__+'). State and reservations are saved. I did not switch to a paid fallback. Ask for status to inspect what completed.')


def main():
    db=connect();tables(db)
    # A restart must not replay uncertain generation/side effects as a new task.
    db.execute('UPDATE telegram_updates SET status="interrupted" WHERE status="running"');db.commit()
    last_tick=0
    while True:
        try:
            with transaction(db):
                row=db.execute('SELECT * FROM telegram_updates WHERE status="queued" ORDER BY id LIMIT 1').fetchone()
                if row:db.execute('UPDATE telegram_updates SET status="running" WHERE id=?',(row['id'],))
            if row:
                with worker_lock():run(db,row)
            elif time.monotonic()-last_tick>60:
                from .__main__ import tick
                tick(db);last_tick=time.monotonic()
        except Exception as exc:
            try:notify(db,'worker-error:'+dt.datetime.now(dt.timezone.utc).date().isoformat()+':'+type(exc).__name__,
                'Pipeline needs attention: '+type(exc).__name__+'. No paid fallback. Ask what is blocked or use /status.')
            except Exception:pass
            time.sleep(5)
        time.sleep(1)

if __name__=='__main__':main()
