# Operations

## Runtime

The four long-running services are `cyberquiz-telegram`, `cyberquiz-conversation`, `cyberquiz-worker` and `cyberquiz-media`. A separate daily `cyberquiz-research.timer` runs bounded topic-wide discovery. Telegram is the operational interface. Only `/budget` appears in its command menu. Natural-language requests cover status, pause/resume, publishing, schedule overrides, lower budgets, research, ideas and previews.

During refinement, scheduled generation/publication stay paused. A `publishing_not_before` timestamp additionally prevents premature posting. A fixed schedule entered through Telegram disables adaptive posting times. Never clear an operator pause during deployment.

## Deployment and verification

Run `python3 deploy/upload.py`. Stop the three Python services for the source swap and restart them after checks. The uploader preserves production SQLite, existing credentials, pause state and lowered monetary ceilings. It never uploads laptop-generated media or replaces production data. Use `--sync-secrets` only for an intentional credential update.

`deploy/aws_access.py` obtains short-lived SSH access without printing the private key. Check service state with:

```sh
python3 deploy/aws_access.py 'systemctl is-active cyberquiz-telegram cyberquiz-conversation cyberquiz-worker cyberquiz-media'
```

Tests cover source-proof binding, 50-Reel history, numerical disguises of duplicate claims, scheduling deadlines, budget races, experiment adoption requirements, private access, Telegram media deletion/resending, audio alignment and uncertain publication protection.

## Costs and failure handling

Cloudflare uses a shared 10,000-neuron UTC-day ceiling; chat is protected from research consumption. Eligible inference stops when Free is exhausted. The selected premium voice has its own pricing check plus shared rolling monthly/per-job reservations; it is an explicit voice choice, never a model fallback. The private preview experiment is capped at six cents. Fal invoice reporting remains unavailable, so report reservations separately from reconciled billing.

Source attempts and failed drafts are bounded. Unsupported facts, ambiguous answers, duplicates and media failures hold production. Unknown provider results retain their reservation and request identity. Instagram unknown publish results block reposting; inspect saved container/request/account state before any recovery. Never reset such a job to a fresh submission merely because a timeout occurred.

After confirmed Telegram preview delivery, retain the file ID and erase local media. After confirmed Instagram publication, retain the receipt and erase staging media. Keep media temporarily only for active production or unresolved publication. Keep source evidence, plans, checks and financial records as text. No D1 or additional server is required for the current metadata volume.

## Credentials and notifications

Credentials remain outside Git in a private file. Meta's Page token currently has no scheduled token expiry, but its data-access deadline and revocation still matter; the service checks them daily. Reauthorization may require the owner. Do not transmit Instagram credentials to an AI provider.

Only confirmed-publication notifications go to both registered authorized chats. Previews, failures and unsolicited updates go to the owner. Ordinary interactive replies stay with the chat that requested them.

Use normal Telegram messages such as “post the next reel now”, “show the latest preview”, “pause”, “resume”, and “what’s happening?”. Immediate publication selects a ready job or makes one if needed, without changing the recurring schedule. It overrides the scheduled time only; all other publication and budget checks still apply. Hypothetical discussion does not authorize publication. An interrupted/unknown publication is retained for reconciliation rather than automatically resubmitted.

## Topic-wide discovery

`cyberquiz-research.timer` starts the isolated research oneshot daily at 03:17 UTC and
after boot. It observes top/recent Reel samples across hashtag searches rather than only
following a competitor watchlist. Install the matching service/timer from `deploy/`, run
`systemctl daemon-reload`, and enable the timer. The selected Workers AI vision model
requires its documented one-time license agreement before use. Research uses the same
free shared neuron ledger, with no paid fallback. The service has separate CPU/memory
limits and cannot publish or send Telegram messages. Disable it with the timer or the
`trend_discovery_enabled` runtime setting. `discovery_hashtags` seeds discovery; validated
research suggestions extend the topic frontier automatically. Use the research capability
to inspect dated findings and availability limitations. Discovery API outages must not
block the ready publication queue.
