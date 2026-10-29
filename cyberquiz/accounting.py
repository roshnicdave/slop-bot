"""Explicitly distinguish invoices, balances, token measurements and ceilings."""
import datetime as dt
import json
from .store import ROOT,now


def report(db):
    day=dt.datetime.now(dt.timezone.utc).date().isoformat()
    paid=[dict(x) for x in db.execute('SELECT kind,reserved,actual,status FROM charges')]
    result={'checked_at':now(),'paid_reserved_usd':sum(x['reserved'] for x in paid)/1e6,
       'paid_usage_rated_usd':sum(x['actual'] or 0 for x in paid)/1e6,
       'paid_usage_rated_caveat':'Token counts priced at conservative peak rates; missing actuals excluded. Not a reconciled invoice.',
       'default_paid_fallback':False,'cloudflare_free_monetary_charge_usd':0,
       'cloudflare_charge_basis':'Owner-confirmed Workers Free, eligible models only, no paid upgrade. Account-wide invoice not retrieved.',
       'neurons_reserved_today':0,'token_usage':[],'provider_reported_neurons_today':0}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='cf_calls'").fetchone():
        result['neurons_reserved_today']=db.execute('SELECT COALESCE(SUM(neurons),0) FROM cf_calls WHERE day=?',(day,)).fetchone()[0]
        cols={x[1] for x in db.execute('PRAGMA table_info(cf_calls)')}
        if 'accounted_neurons' in cols:result['neurons_budgeted_today']=db.execute('SELECT COALESCE(SUM(COALESCE(accounted_neurons,neurons)),0) FROM cf_calls WHERE day=?',(day,)).fetchone()[0]
        if 'usage' in cols:
            for row in db.execute('SELECT operation,kind,usage FROM cf_calls WHERE day=? AND usage IS NOT NULL',(day,)):
                try:usage=json.loads(row['usage'])
                except ValueError:continue
                if isinstance(usage,dict) and isinstance(usage.get('neurons'),(int,float)):result['provider_reported_neurons_today']+=usage['neurons']
                if isinstance(usage,dict):result['token_usage'].append({'operation':row['operation'],'kind':row['kind'],'provider_usage':usage})
    result['neurons_caveat']='Conservative local reservations include failed/unknown calls. Not Cloudflare account-wide measured neurons.'
    audit=ROOT/'data'/'latest-usage.json'
    if audit.exists():
        a=json.loads(audit.read_text());result['provider_audit_checked_at']=a.get('checked_at')
        result['fal_usage_available']=not a.get('fal',{}).get('unavailable',True)
        result['deepseek_balance']=a.get('deepseek',{}).get('balance_infos',[])
    return result

if __name__=='__main__':
    from .store import connect
    print(json.dumps(report(connect()),indent=2))
