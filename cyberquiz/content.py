"""Facts are computed or copied from primary sources; AI handles presentation."""
import datetime as dt
import hashlib
import ipaddress
import json
import random
import re

import requests

from .store import ROOT, now

KEV = 'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'
RFC = 'https://www.rfc-editor.org/rfc/rfc1878.txt'


def fingerprint(question):
    return hashlib.sha256(re.sub(r'\W+', '', question.lower()).encode()).hexdigest()[:24]


def evergreen():
    result = []
    # Restrict to conventional IPv4 LANs: no /31 or /32 exceptions.
    for prefix in range(24, 31):
        hosts = 2 ** (32-prefix) - 2
        result.append({'question':f'On a conventional IPv4 /{prefix} LAN, how many usable host addresses are there?',
            'answer': str(hosts), 'distractors': [str(hosts+2), str(hosts+1)],
            'explanation': f'A /{prefix} has {hosts+2} addresses. Subtract the network and broadcast addresses: {hosts} usable hosts.',
            'source_url':RFC, 'source_label':'RFC 1878', 'family':'subnet-hosts'})
        for block in range(1, 65):
            network = ipaddress.ip_network(f'192.168.{block}.0/{prefix}')
            addr = str(network.broadcast_address)
            result.append({'question':f'What is the broadcast address of {network}?',
                'answer':addr, 'distractors':[str(network.network_address+1),str(network.broadcast_address-1)],
                'explanation':f'The block runs from {network.network_address} to {addr}. The last address is the broadcast address.',
                'source_url':RFC, 'source_label':'RFC 1878 + Python ipaddress', 'family':'subnet-broadcast'})
    for prefix in range(24,31):
        n=ipaddress.ip_network(f'10.20.30.0/{prefix}')
        result.append({'question':f'Which subnet mask corresponds to an IPv4 /{prefix} prefix?',
          'answer':str(n.netmask),'distractors':[str(ipaddress.ip_network(f'10.0.0.0/{prefix-1}').netmask),str(ipaddress.ip_network(f'10.0.0.0/{prefix+1}').netmask)],
          'explanation':f'A /{prefix} prefix has {prefix} network bits. Its dotted-decimal subnet mask is {n.netmask}.',
          'source_url':RFC,'source_label':'RFC 1878','family':'subnet-mask'})
        for block in range(1,17):
            network=ipaddress.ip_network(f'10.20.{block}.0/{prefix}')
            result.append({'question':f'For a conventional IPv4 LAN, what is the first usable host in {network}?',
              'answer':str(network.network_address+1),'distractors':[str(network.network_address),str(network.broadcast_address)],
              'explanation':f'{network.network_address} is the network address. Add one for the first usable host: {network.network_address+1}.',
              'source_url':RFC,'source_label':'RFC 1878 + Python ipaddress','family':'subnet-firsthost'})
    facts = [
      ('HTTPS means a website is trustworthy. True or false?', 'False', ['True', 'Only on Wi-Fi'],
       'HTTPS protects the connection. A phishing site can still use HTTPS.',
       'https://www.cisa.gov/secure-our-world/recognize-and-report-phishing', 'CISA', 'phishing'),
      ('Which protocol maps an IPv4 address to a local Ethernet address?', 'ARP', ['DNS','DHCP'],
       'ARP resolves a protocol address to a hardware address on the local network.',
       'https://www.rfc-editor.org/rfc/rfc826.txt', 'RFC 826', 'protocols'),
      ('Which DNS record contains an IPv6 address?', 'AAAA', ['A','MX'],
       'AAAA records contain IPv6 addresses. A records contain IPv4 addresses.',
       'https://www.rfc-editor.org/rfc/rfc3596.txt','RFC 3596','dns'),
      ('Which transport does a standard TCP connection use for reliable ordered delivery?', 'TCP', ['UDP','ARP'],
       'TCP provides a reliable, in-order byte stream. ARP is not a transport protocol.',
       'https://www.rfc-editor.org/rfc/rfc9293.txt','RFC 9293','tcp'),
      ('A switch learns a dynamic MAC table entry from which frame field?', 'Source MAC', ['Destination MAC','Source IP'],
       'A learning bridge associates the source MAC address with the ingress port.',
       'https://www.cisco.com/c/en/us/support/docs/lan-switching/ethernet/10561-3.html','Cisco','switching')]
    facts=[x for x in facts if x[-1] not in ('tcp','phishing','switching')]
    for q,a,d,e,u,s,f in facts:
        result.append(dict(question=q, answer=a, distractors=d, explanation=e, source_url=u, source_label=s, family=f))
    return result


def refresh_sources(db):
    r = requests.get(KEV, timeout=45)
    r.raise_for_status()
    data = r.json()
    for item in data['vulnerabilities']:
        db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?)',
          (item['cveID'], now(), item['dateAdded'], KEV, json.dumps(item)))
    db.commit()
    (ROOT/'data'/'kev-snapshot.json').write_text(json.dumps(data))
    return len(data['vulnerabilities'])


def candidates(db, recent=False, max_age=14):
    if not recent:
        return evergreen()
    cutoff = (dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=max_age)).isoformat()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    # Require recently fetched catalogue AND a recent dateAdded. Never fake recency.
    fetched_cutoff = (dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=24)).isoformat()
    rows = db.execute('SELECT payload FROM sources WHERE published>=? AND published<=? AND fetched>=? ORDER BY published DESC',
                      (cutoff,today,fetched_cutoff)).fetchall()
    result=[]
    all_products = sorted({json.loads(r[0])['product'] for r in rows})
    for row in rows:
        v = json.loads(row[0]); product=v['product']
        others=[p for p in all_products if p!=product and len(p)<45]
        if len(others)<2 or len(product)>45:
            continue
        result.append({'question':f'CISA added {v["cveID"]} on {v["dateAdded"]}. Which product is listed?',
            'answer':product,'distractors':others[:2],
            'explanation':f'CISA lists {product} by {v["vendorProject"]}. Check the vendor guidance for affected versions and fixes.',
            'source_url':KEV, 'source_label':f'CISA KEV | added {v["dateAdded"]}',
            'family':'recent-kev', 'published':v['dateAdded'], 'cve':v['cveID']})
    labels={
      'CWE-778':('Insufficient logging','Security-relevant events may not be recorded adequately.'),
      'CWE-456':('Missing variable initialization','A variable is used without the necessary initialization.'),
      'CWE-434':('Dangerous file upload','Dangerous file types may be uploaded without sufficient restriction.'),
      'CWE-89':('SQL injection','Untrusted input can change the structure of an SQL command.'),
      'CWE-79':('Cross-site scripting','Untrusted input can become executable content in a web page.'),
      'CWE-22':('Path traversal','Improper path restrictions can allow access outside an intended directory.'),
      'CWE-78':('OS command injection','Untrusted input can change an operating-system command.'),
      'CWE-287':('Improper authentication','The product does not adequately prove the claimed identity.'),
      'CWE-862':('Missing authorization','An operation is performed without the required authorization check.'),
      'CWE-416':('Use after free','Software uses memory after that memory has been freed.')}
    practical=[]
    for row in rows:
        v=json.loads(row[0])
        for cwe in v.get('cwes',[]):
            if cwe not in labels:continue
            answer,explain=labels[cwe]
            q=f'CISA added {v["cveID"]} on {v["dateAdded"]}. What does its {cwe} weakness mean?'
            practical.append({'question':q,'answer':answer,
              'distractors':[a for a,e in labels.values() if a!=answer][:2],
              'explanation':explain+' Check vendor guidance for affected versions and fixes.',
              'source_url':KEV,'source_label':f'CISA KEV + MITRE {cwe}',
              'reference_url':f'https://cwe.mitre.org/data/definitions/{cwe.split("-")[1]}.html',
              'family':'recent-kev','published':v['dateAdded'],'cve':v['cveID'],'cwe':cwe})
            break
    return practical or result


def choose(db, recent=False):
    cfg = __import__('cyberquiz.store', fromlist=['config']).config()
    used = {r[0] for r in db.execute('SELECT topic FROM jobs')}
    options = [c for c in candidates(db,recent,cfg['source_max_age_days']) if fingerprint(c['question']) not in used]
    if not options and recent:
        return choose(db,False)
    if not options:
        raise ValueError('Verified question bank exhausted. Expand reviewed sources; no repeats generated.')
    # Avoid the same topic family on consecutive runs where possible.
    last = db.execute('SELECT plan FROM jobs WHERE plan IS NOT NULL ORDER BY created DESC LIMIT 1').fetchone()
    last_family = json.loads(last[0]).get('family') if last else None
    varied=[x for x in options if x['family']!=last_family]
    return random.SystemRandom().choice(varied or options)


def validate(fact):
    assert len(fact['distractors'])==2
    assert len(set([fact['answer'],*fact['distractors']]))==3
    assert len(fact['question'])<=150
    assert len(fact['explanation'])<=200
    assert fact['source_url'].startswith('https://')
    if fact['family']=='subnet-hosts':
        prefix=int(re.search(r'/(\d+)',fact['question'])[1])
        assert int(fact['answer'])==2**(32-prefix)-2
    if fact['family']=='subnet-broadcast':
        network=ipaddress.ip_network(fact['question'].split()[-1].rstrip('?'))
        assert fact['answer']==str(network.broadcast_address)
    if fact['family']=='recent-kev':
        assert fact['cve'] in fact['question']
        assert (dt.datetime.now(dt.timezone.utc).date()-dt.date.fromisoformat(fact['published'])).days<=14
    return fact


def source_evidence(fact):
    r=requests.get(fact['source_url'],timeout=45)
    r.raise_for_status()
    if fact['family']=='recent-kev':
        matches=[v for v in r.json()['vulnerabilities'] if v['cveID']==fact['cve']]
        if len(matches)!=1 or matches[0]['dateAdded']!=fact['published'] or (fact.get('cwe') not in matches[0].get('cwes',[]) if fact.get('cwe') else matches[0]['product']!=fact['answer']):
            raise ValueError('Current source no longer agrees with quiz')
    if fact.get('reference_url'):
        reference=requests.get(fact['reference_url'],timeout=30)
        reference.raise_for_status()
        if fact['cwe'] not in reference.text:
            raise ValueError('Weakness reference not confirmed')
    return {'url':fact['source_url'],'retrieved_at':now(),'sha256':hashlib.sha256(r.content).hexdigest(),
            'excerpt':r.text[:2000] if fact['family']!='recent-kev' else matches[0]}


def plan(fact, creative, job):
    validate(fact)
    options=[fact['answer'],*fact['distractors']]
    random.Random(job).shuffle(options)
    correct=options.index(fact['answer'])
    letters='ABC'
    intro=fact['question']+' '+'. '.join(f'{letters[i]}. {v}' for i,v in enumerate(options))+'.'
    outro=f'The answer is {letters[correct]}. '+fact['explanation']
    intro=intro.encode('ascii','ignore').decode();outro=outro.encode('ascii','ignore').decode()
    if len(intro)+len(outro)>600:
        raise ValueError('Narration exceeds 600-character total cap')
    hook=creative.get('hook','Your daily network check')
    if len(hook)>45 or not hook.isascii():
        hook='Your daily network check'
    return {**fact,'id':job,'options':options,'correct':correct,'intro':intro,'outro':outro,
            'hook':hook,'image_prompt':str(creative['image_prompt'])[:900],
            'caption': f'{fact["question"]}\n\nAnswer: {letters[correct]}. {fact["explanation"]}\n\nSource: {fact["source_label"]}\n{fact["source_url"]}\n{fact.get("reference_url", "")}\n\nFollow @cybersec.peter for practical networking and security questions.\n#networking #cybersecurity #networkengineer',
            'format':creative.get('format','quiz') if creative.get('format') in ['quiz','challenge'] else 'quiz',
            'decision_seconds':3 if creative.get('format')=='challenge' else 5}
