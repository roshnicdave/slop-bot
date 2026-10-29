# Slop Bot

Autonomous visual networking and cybersecurity quizzes for Instagram Reels. AWS runs the scheduler, renderer and Telegram bot. A protected Cloudflare Worker provides free LLM inference and voice.

## Status

- Independent repository: https://github.com/roshnicdave/slop-bot
- Runtime: existing Lightsail server; four services including HTTPS media hosting.
- Telegram: ordinary messages go to the control plane. `/budget` is the only advertised command. Two private users are configured in `config.json`; each must start the bot.
- Generation is enabled. Routine approval is automatic after technical, editorial, layout and media checks.
- Instagram publication is blocked until the official API token is connected. No post has been published by this system yet.
- Current question coverage: 16 verified mechanisms, including procedural route, ACL, trunk, subnet and MTU variants. New mechanisms need executable verification; the model cannot invent arbitrary technical facts.

## Daily run

1. Gather dated primary sources, available reference-account observations, recent concepts, preferences and comparable-age performance.
2. A bounded free LLM selects ideas and may request two additional source reads. Cached decisions survive restarts.
3. Compile a verified scenario. Draft a fresh hook and caption; reject misleading or ambiguous wording. At most two candidates per run.
4. Generate separate question, reveal and fix audio. Scene transitions and subtitles follow actual audio durations.
5. Render native diagrams or configuration cards. Check readability, answer alignment, timing and MP4 decoding.
6. Publish eligible videos in the configured window. Persist request/container IDs and hold uncertain outcomes rather than reposting.
7. Notify registered Telegram users after confirmed publication. Gather metrics at bounded comparable ages and preserve exploration when choosing pacing.
8. Delete generated media one hour after confirmed publication. Keep plans, quality reports, receipts and usage records. Keep seven local database backups.

## Costs

Default paid inference is disabled at the provider boundary. No paid fallback or automatic upgrade.

Cloudflare Workers Free provides 10,000 neurons/day account-wide. The local reservation ceiling is 8,000: chat 4,000, voice 3,000, research 1,000. Narration is limited to 600 characters per video across all clips. Two maximum-length videos reserve about 2,110 neurons including headroom. Other account usage can exhaust Free; requests then stop.

The existing Lightsail bundle is $5/month. This project adds no server. Historical paid prototype reservations total about $0.0200; Fal invoice reconciliation is unavailable with the current reporting permissions. Reservations, provider-reported usage and invoices are distinct.

## Run and verify

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m cyberquiz doctor
```

`ffmpeg` and fonts are required for rendering. Credentials live outside the repository in `~/.config/cyber-quiz/credentials.json` with mode 600. Never paste them into issues or commit them.

Deployment: `python3 deploy/upload.py`. It preserves the production database, live pause state and lowered budget limits. Use the service units in `deploy/` for the AWS processes.

## Limits still being evaluated

Virality is an optimization objective, not a guarantee. Public likes and comments do not establish reach or causation. Current live routing evaluation is small; review `data/routing-evaluation.json` on the server. Automatic competitor video/audio inspection, account-wide Cloudflare billing reconciliation, and full publication recovery need further integration. See [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) and [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md).
