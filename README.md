# Slop Bot

An AWS-hosted agent for cybersecurity and networking quiz Reels, controlled through Telegram. It researches primary sources, proposes new questions and technical diagrams, checks them, produces narration and video, publishes, and evaluates subsequent performance.

## Operating policy

- Two daily posting experiments; the agent proposes times from its own account history. Exact times are hypotheses until there is comparable evidence. The worker sleeps until a deadline or a Telegram wake signal.
- Routine factual, wording, layout, narration and media checks are automatic. Rejected candidates are skipped; unsupported claims never bypass a gate to fill a schedule.
- Telegram has one advertised command, `/budget`; all messages go directly to one agent with native function calling and generated replies. Previews and non-publication alerts go only to the owner. Confirmed publication notifications go to both authorized chats.
- Read live state in Telegram; deployment preserves operator controls and spending limits. The example configuration starts with publishing disabled.

## Content and learning

`curriculum.py` reads public CCNA, Network+ and Security+ topic blueprints and tracks coverage by exam objective. `knowledge.py` walks bounded primary-documentation indexes across networking, web security and infrastructure. `discovery.py` creates diagnostic cases and typed technical diagrams from those documents and recent primary articles. It preserves the article snapshot, hash, supporting passage and separate factual review. These semantic checks have limits; they are not mathematical proof. The executable networking scenario library remains available for deterministic checks.

`novelty.py` maintains text history independently of video retention. Useful lessons can return as spaced practice: the default lesson gap is eight published Reels, with a separate 50-Reel window for an identical practice case. Both are configurable. Changed wording alone does not bypass the short lesson gap, and pending work is checked too. Primary-source review and coverage ranking encourage breadth; semantic duplicate detection remains fallible.

Current-source selection receives publication dates and source types, so evergreen documentation is distinct from dated news. A relevant industry case can remain untagged when no exam objective fits; certification labels and hashtags require the exam path. Both paths retain the same source, diagram, unique-answer and blind-solver gates. See [the curriculum review](CONTENT_RESEARCH.md) for topic scope and the announced CCNA transition.

`experiments.py` lets an LLM propose a new pacing or hook hypothesis from feedback and results. One factor is tested at a time. Each Reel records its assignment. Adoption requires at least ten comparable posts per arm and a positive bootstrap interval on shares per reached audience at approximately 72 hours. Inconclusive results stay inconclusive. This updates a saved editorial policy; it does not train model weights or permit arbitrary code execution.

The technical diagram, dark palette, Inter typography, no-subheading rule, short hook and “Comment your answer” prompt are operator requirements. The agent can explore content choices within those requirements, not silently discard them.

An optional Telugu audio-mix overlay (`telugu_mix_enabled`, default off) adds short Telugu narration for the configured segments — intro greeting and closing explanation by default. Technical terms (TTL, DHCP, Layer 2, IP addresses, port numbers) stay in English inside the Telugu lines so pronunciation is correct. Each translation goes through an independent review gate matching the existing source-review pattern; a rejected translation falls back to English-only without blocking the Reel. The technical reveal remains English. The added Telugu characters count against the per-job narration cap, so enabling this feature requires raising `per_job_budget_usd` beyond the default $0.03; the preflight will reject the whole narration rather than silently exceed the budget.

## Storage and cost

SQLite stores jobs, source evidence, concept history, experiments, usage and Telegram file IDs. No additional database service or local inference model is needed. Media exists only while rendering/transmitting: private preview media is deleted after Telegram delivery; published media is deleted after a confirmed Instagram receipt. Telegram previews can be resent using file IDs. Pending publishing artifacts remain staged until their outcome is known.

Cloudflare Workers Free handles the LLM control/research plane under a shared 10,000-neuron daily reservation ceiling. Source drafting uses the selected GPT-OSS 120B profile; concise control and independent review use smaller profiles. Each has conservative reservations under the same shared ceiling; there is no paid model fallback. See [Cloudflare model rates](https://developers.cloudflare.com/workers-ai/platform/pricing/). Selected ElevenLabs Chris narration is metered at the verified Fal rate of $0.10/1,000 characters, with the shared $1.80 rolling monthly and $0.03 production-job caps enforced before submission. The six-cent preview experiment has its own ceiling. Other paid models and fallback providers remain disabled. Estimated usage is not an invoice reconciliation.

At about 200–250 spoken characters per Reel, 60 Reels cost approximately $1.20–$1.50 in narration before retries or tests; caps can stop production. Hosting costs are separate and depend on the deployment. No new server, paid Cloudflare plan or D1 service was added.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m cyberquiz doctor
```

FFmpeg and system fonts are required. Inter is bundled with its OFL license. Credentials stay outside the repository in `~/.config/cyber-quiz/credentials.json` with mode 600. See [OPERATIONS.md](OPERATIONS.md) and [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md).

Local setup: copy `config.example.json` to `config.json`, `cloudflare/wrangler.example.jsonc` to `cloudflare/wrangler.jsonc`, and `deploy/aws.example.json` to `deploy/aws.local.json`. Fill in account, recipients, endpoint and deployment identity locally. These mutable files are ignored by Git; examples contain no account-specific IDs. Generation and publishing start disabled.
The live `deploy/Caddyfile` is ignored too; copy `deploy/Caddyfile.example` and set your hostname/contact before deploying the media host.

The worker maintains one ready Reel and refills after confirmed publication. A separate process maintains three fully reviewed text drafts, waking after staging and every six hours. It does not buy narration or render reserve videos. Citation IDs bind to actual source passages; an independent source audit, title check and blind quiz solver must pass before a draft becomes ready. Background drafting has its own free quota cap, preserving capacity for publication checks. Optional trend/planning outages do not prevent production from using reviewed work. All work remains subject to budgets, quality and repetition spacing. Publication notifications contain the post link and go to both authorized Telegram chats.

Daily niche research searches Instagram hashtag top/recent feeds across accounts and
expands through discovered public creator mentions. It selects examples for relevance
and presentation, inspects one accessible clip through sampled frames/transcribed audio,
and feeds dated text observations into editorial planning. The independent research
oneshot preserves publishing responsiveness, shares the free AI ledger, and keeps no
research media. Counts and sampled observations are evidence for experiments, not proof
of virality. New explainer/animation production formats require renderer support; finding
them during research does not automatically make them available for publishing.
