"""Use comparable 72-hour posts; never equate a lucky view spike with proof."""
import json
import random
import statistics


def metric(payload,name):
    data=payload.get(name,{})
    try:
        item=data['data'][0]
        value=item.get('total_value',{}).get('value')
        if value is None:value=item['values'][0]['value']
        return float(value)
    except (KeyError,IndexError,TypeError,ValueError):return None


def analyze(db):
    groups={};posts=[]
    for job in db.execute('SELECT media_id,plan FROM jobs WHERE status="published"'):
        # One snapshot per post at a comparable age. Do not compare 1h to 7d.
        row=db.execute('SELECT payload,age_hours FROM metrics WHERE media_id=? AND age_hours BETWEEN 60 AND 84 ORDER BY ABS(age_hours-72) LIMIT 1',(job['media_id'],)).fetchone()
        if not row:continue
        payload=json.loads(row['payload']);reach=metric(payload,'reach')
        if reach is None or reach<100:continue
        follows=metric(payload,'follows');shares=metric(payload,'shares');saved=metric(payload,'saved')
        if shares is None:continue
        p=json.loads(job['plan']);score=1000*shares/reach
        entry={'media_id':job['media_id'],'format':p['format'],'family':p['family'],
            'reach':reach,'follows_per_1000':None if follows is None else 1000*follows/reach,'shares_per_1000':1000*shares/reach,
            'saves_per_1000':None if saved is None else 1000*saved/reach,'score':score}
        posts.append(entry);groups.setdefault(p['format'],[]).append(score)
    eligible={k:statistics.median(v) for k,v in groups.items() if len(v)>=5}
    winner=max(eligible,key=eligible.get) if len(eligible)>=2 else None
    return {'comparable_posts':len(posts),'formats':{k:{'posts':len(v),'median_shares_per_1000':statistics.median(v)} for k,v in groups.items()},
      'objective':'shares per 1000 reached; follows and saves are separate outcomes',
      'preferred_format':winner,'experiment_share':0.25,'posts':posts,
      'cadence_recommendation':'Start at 1/day. Test 2/day for 14 days after 14 days at 1/day. Compare total daily follows and median follows/shares per reach; cadence is not a virality guarantee.'}


def select_format(db,job):
    result=analyze(db);rng=random.Random(job)
    if result['preferred_format'] and rng.random()>=0.25:return result['preferred_format']
    return rng.choice(['quiz','challenge'])


def experiment(db,p,job):
    """One-factor pacing test within a stable template; 25% exploration."""
    template='config' if p['diagram']['kind']=='config' else 'topology'
    result=analyze(db);rng=random.Random(job);scores={}
    for seconds in (4,5):
        key=template+'-pause-'+str(seconds)
        group=result['formats'].get(key,{})
        if group.get('posts',0)>=5:scores[seconds]=group['median_shares_per_1000']
    seconds=rng.choice([4,5])
    if len(scores)==2 and rng.random()>=.25:seconds=max(scores,key=scores.get)
    cta='Which clue gave it away?'
    return {'format':template+'-pause-'+str(seconds),'decision_seconds':seconds,
        'experiment':{'factor':'decision_seconds','arm':seconds,'template':template,
            'policy':'5 comparable posts per arm before exploitation; retain 25% exploration'},
        'closing_prompt':cta}
