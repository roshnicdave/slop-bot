"""Fast allowlisted control process. Expensive work is durably queued elsewhere."""
import datetime as dt
import json
import os
import random
import sqlite3
import tempfile
import time
from pathlib import Path

import requests

from .store import ROOT,connect,config,now
from .providers import secrets
from .network import http


def tables(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS telegram_updates(id INTEGER PRIMARY KEY, user_id INTEGER, command TEXT, status TEXT, result TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS telegram_chats(user_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS notices(event TEXT, chat_id INTEGER, status TEXT, PRIMARY KEY(event,chat_id));
    CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS telegram_latency(update_id INTEGER PRIMARY KEY,received REAL,replied REAL,seconds REAL);
    ''');db.commit()


def api(method,payload=None,files=None,timeout=35):
    token=secrets()['TELEGRAM_BOT_TOKEN']
    # Never include the token-bearing URL in errors or logs.
    try:
        r=http().post('https://api.telegram.org/bot'+token+'/'+method,data=payload or {},files=files,timeout=timeout)
        data=r.json()
    except Exception:raise RuntimeError('Telegram transport failed') from None
    if not r.ok or not data.get('ok'):raise RuntimeError('Telegram request failed (HTTP '+str(r.status_code)+')')
    return data['result']


def send(chat,text):
    return api('sendMessage',{'chat_id':chat,'text':text[:4000],'disable_web_page_preview':'true'},timeout=(3,6))


def video(chat,job):
    import re
    if not re.fullmatch('[a-f0-9]{12}',job):return send(chat,'No video found.')
    path=ROOT/'out'/job/'reel.mp4'
    if not path.exists():return send(chat,'Video is not ready. Check /status.')
    with path.open('rb') as handle:
        result=api('sendVideo',{'chat_id':chat,'caption':json.loads((ROOT/'out'/job/'plan.json').read_text()).get('question','New quiz').replace('\n',' '),
                  'supports_streaming':'true'},files={'video':handle},timeout=90)
    db=connect();tables(db)
    db.execute('INSERT OR REPLACE INTO control VALUES(?,?)',('last_preview:'+str(chat),job));db.commit();db.close()
    return result


def notify(db,event,message):
    tables(db)
    for row in db.execute('SELECT chat_id FROM telegram_chats').fetchall():
        chat=row[0]
        try:
            db.execute('INSERT INTO notices VALUES(?,?,?)',(event,chat,'sending'));db.commit()
        except sqlite3.IntegrityError:continue
        try:
            send(chat,message)
            db.execute('UPDATE notices SET status="sent" WHERE event=? AND chat_id=?',(event,chat));db.commit()
        except RuntimeError:
            # Unknown send outcomes are recorded; do not create a message storm.
            db.execute('UPDATE notices SET status="uncertain" WHERE event=? AND chat_id=?',(event,chat));db.commit()


def update_config(values):
    import fcntl
    with (ROOT/'data'/'config.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        cfg=config();cfg.update(values)
        fd,temp=tempfile.mkstemp(dir=ROOT,prefix='.config-')
        with os.fdopen(fd,'w') as handle:json.dump(cfg,handle,indent=2)
        os.replace(temp,ROOT/'config.json')


HELP="Ask me about the system, suggest a topic, or tell me to pause. /budget shows spending."


def status_text(db,budget_only=False):
    from .__main__ import report
    r=report(db);c=config()
    from .accounting import report as accounting
    usage=accounting(db);free=usage.get('neurons_budgeted_today',usage['neurons_reserved_today'])
    if budget_only:
        return (f"AI: Cloudflare Free; paid calls disabled.\n"
          f"Free quota (UTC day): {free:,}/{c.get('cf_daily_neuron_limit',8000):,} neurons budgeted (measured when available).\n"
          f"Old paid tests: ${r['reserved_31_days_usd']:.4f} reserved; invoice not reconciled.\n"
          f"Existing AWS server: $5/month. No new server added.")
    generation='paused' if c.get('emergency_pause') or not c.get('generation_enabled') else 'scheduled'
    connected=bool(secrets().get('IG_ACCESS_TOKEN'))
    publication='enabled' if c['publishing_enabled'] else ('paused' if connected else 'blocked: Meta authorization missing')
    latest=db.execute('SELECT id,status FROM jobs ORDER BY created DESC LIMIT 1').fetchone()
    return f"Generation: {generation}. Posting: {publication}."+(f"\nLatest video: {latest['id']} ({latest['status']})." if latest else '')


def handle(db,update):
    msg=update.get('message',{});user=msg.get('from',{}).get('id');chat=msg.get('chat',{})
    if user not in config().get('telegram_allowed_user_ids',[]) or chat.get('type')!='private' or chat.get('id')!=user:
        return
    text=msg.get('text','').strip()[:1500]
    if not text:return
    db.execute('INSERT OR REPLACE INTO telegram_chats VALUES(?,?)',(user,chat['id']));db.commit()
    if db.execute('SELECT 1 FROM telegram_updates WHERE id=?',(update['update_id'],)).fetchone():return
    db.execute('INSERT OR IGNORE INTO telegram_latency(update_id,received) VALUES(?,?)',(update['update_id'],time.time()));db.commit()
    import re
    credential=re.search(r'\bsk-[A-Za-z0-9_-]{20,}|\b\d{7,}:[A-Za-z0-9_-]{25,}|\bEAA[A-Za-z0-9]{40,}|\bIGQ[A-Za-z0-9_-]{40,}|(?i:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*[A-Za-z0-9_:-]{20,}',text)
    if credential:
        send(user,'Keep tokens out of chat. Use the hidden connection prompt.');return
    command=text.split(maxsplit=1)[0].split('@')[0].lower()
    db.execute('INSERT INTO telegram_updates VALUES(?,?,?,?,?,?)',(update['update_id'],user,text,'received',None,now()));db.commit()
    if command=='/start':
        send(user,'Ready. '+HELP)
    elif command=='/budget':
        send(user,status_text(db,True))
    else:
        # Every ordinary message goes to the supervisor. Legacy slash commands
        # are not a second control API; remove only the slash for plain chat.
        if command.startswith('/'):
            text=text[1:]
            db.execute('UPDATE telegram_updates SET command=? WHERE id=?',(text,update['update_id']))
        db.execute('UPDATE telegram_updates SET status="queuedchat" WHERE id=?',(update['update_id'],));db.commit();return
    mark_replied(db,update['update_id'])
    db.execute('UPDATE telegram_updates SET status="done",result="replied" WHERE id=?',(update['update_id'],));db.commit()


def mark_replied(db,ident):
    replied=time.time()
    db.execute('UPDATE telegram_latency SET replied=?,seconds=?-received WHERE update_id=?',(replied,replied,ident));db.commit()


def main():
    db=connect();tables(db);delay=2
    while True:
        row=db.execute('SELECT value FROM control WHERE key="telegram_offset"').fetchone();offset=int(row[0]) if row else 0
        try:
            updates=api('getUpdates',{'offset':offset,'timeout':25,'allowed_updates':json.dumps(['message'])},timeout=32)
            for item in updates:
                handle(db,item)
                db.execute('INSERT OR REPLACE INTO control VALUES(?,?)',('telegram_offset',str(item['update_id']+1)));db.commit()
            db.execute('INSERT OR REPLACE INTO control VALUES(?,?)',('telegram_last_poll',now()));db.commit()
            delay=2
        except Exception as exc:
            db.execute('INSERT OR REPLACE INTO control VALUES(?,?)',('telegram_poll_error',type(exc).__name__+':'+now()));db.commit()
            # Never log token-bearing exception text. Telegram READ retry is safe.
            time.sleep(delay+random.random());delay=min(delay*2,60)

if __name__=='__main__':main()
