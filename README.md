# Slop Bot

An AWS-hosted agent for cybersecurity and networking quiz Reels, controlled through Telegram. It researches primary sources, proposes new questions and technical diagrams, checks them, produces narration and video, publishes, and evaluates subsequent performance.

## Operating policy

- Two daily posting experiments; the agent proposes times from its own account history. Exact times are hypotheses until there is comparable evidence. The worker sleeps until a deadline or a Telegram wake signal.
- Routine factual, wording, layout, narration and media checks are automatic. Rejected candidates are skipped; unsupported claims never bypass a gate to fill a schedule.
- Telegram has one advertised command, `/budget`; all messages go directly to one agent with native function calling and generated replies. Previews and non-publication alerts go only to the owner. Confirmed publication notifications go to both authorized chats.
- Read live state in Telegram; deployment preserves operator controls and spending limits. The example configuration starts with publishing disabled.

## Content and learning

`discovery.py` creates new source-grounded diagnostic topics and typed technical diagrams from recent primary articles. It preserves the article snapshot, hash, supporting passage and separate factual review. These semantic checks have limits; they are not mathematical proof. The executable networking scenario library remains available for deterministic checks.

`novelty.py` maintains text history independently of video retention. Exact normalized claims are blocked across publication history; concept/overlap checks and a separate source reviewer compare proposals with the last 50 published Reels and pending production. Rewording or IP renumbering does not count as a new lesson. Semantic duplicate detection is fallible.

`experiments.py` lets an LLM propose a new pacing or hook hypothesis from feedback and results. One factor is tested at a time. Each Reel records its assignment. Adoption requires at least ten comparable posts per arm and a positive bootstrap interval on shares per reached audience at approximately 72 hours. Inconclusive results stay inconclusive. This updates a saved editorial policy; it does not train model weights or permit arbitrary code execution.

The technical diagram, dark palette, Inter typography, no-subheading rule, short hook and “Comment your answer” prompt are operator requirements. The agent can explore content choices within those requirements, not silently discard them.

## Storage and cost

SQLite stores jobs, source evidence, concept history, experiments, usage and Telegram file IDs. No additional database service or local inference model is needed. Media exists only while rendering/transmitting: private preview media is deleted after Telegram delivery; published media is deleted after a confirmed Instagram receipt. Telegram previews can be resent using file IDs. Pending publishing artifacts remain staged until their outcome is known.

Cloudflare Workers Free handles the LLM control/research plane under a shared 8,000-neuron daily reservation ceiling. Selected ElevenLabs Chris narration is metered at the verified Fal rate of $0.10/1,000 characters, with the shared $1.80 rolling monthly and $0.03 production-job caps enforced before submission. The six-cent preview experiment has its own ceiling. Other paid models and fallback providers remain disabled. Estimated usage is not an invoice reconciliation.

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

The worker maintains one ready Reel and refills after confirmed publication, subject to budget, novelty and quality checks. Publication notifications contain the post link and go to both authorized Telegram chats.
