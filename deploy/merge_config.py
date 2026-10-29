"""Deploy code defaults without undoing a user's live pause or budget limits."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
defaults=json.loads((root/'config.defaults.json').read_text())
path=root/'config.json'
if path.exists():
    current=json.loads(path.read_text())
    for key in ('emergency_pause','generation_enabled','publishing_enabled','require_approval','posts_per_day','slots','timezone'):
        if key in current:defaults[key]=current[key]
    for key in ('monthly_budget_usd','per_job_budget_usd','cf_daily_neuron_limit'):
        if key in current:defaults[key]=min(defaults[key],current[key])
path.write_text(json.dumps(defaults,indent=2)+'\n')
