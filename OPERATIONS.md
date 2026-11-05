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

Tests cover source-proof binding, configurable lesson/identical-case spacing, blueprint parsing, safe documentation discovery, prepared-draft production during planner outages, background quota isolation, scheduling deadlines, budget races, experiment adoption requirements, private access, Telegram media deletion/resending, audio alignment and uncertain publication protection.

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

## Editorial recovery

Daily planning receives a bounded structured projection of research, with full evidence
retained separately. Confirmed completed planning results are reused after local parsing
fixes; pending or uncertain provider operations are never replayed. Local preflight
failures back off for 30 minutes and do not consume the generation allowance.
Only attempts that create production jobs count toward that allowance. A held quality
result is not a ready Reel. Detailed bounded errors are retained in incidents and the
readiness ledger for the Telegram agent to inspect.

## Owner health alerts

Enable cyberquiz-health.timer alongside the worker. It checks local queue, missed
posting windows, open incidents and service state every 30 minutes, independently
of the worker. Pipeline turns also check health on completion or failure. Alerts
track publishing, content preparation and chat separately. Short chat/refill
interruptions have a ten-minute grace period; a due post or stopped publishing
worker is urgent. A recovery is sent only if the corresponding failure was delivered.
All notification text is AI-written from current facts, including confirmed posts
and the ready queue. Publication notices retain their existing audience.

Notification lifecycle state is separate from delivery receipts. Resolved or
superseded operational notices stay in history without being sent. Only the latest
confirmed publication remains eligible for delayed delivery, for at most 24 hours,
with its actual publication time. Pending notices are checked again after AI
composition. Current, ongoing failures remain retryable across free-quota resets;
obsolete alerts and old recovery messages do not drain as a backlog. Unknown
Telegram send outcomes retain receipts and are never blindly resent.

Completed research output that cannot be parsed gets one durable JSON repair within
the shared free allowance. The original response and accounting remain unchanged;
unknown provider outcomes never qualify for repair. Confirmed research recovery
releases a refill's preflight backoff. Missed-post alerts include current failure
details. Notification narration uses plain text without an empty tool list; research
requests explicitly select JSON output.

A known, approved Meta container continues processing beyond its original posting
window. Its existing identity is reused; unknown submissions remain blocked.

Posting times are due times, not expiring windows. The scheduler counts confirmed
publications in the configured local day and catches up an unfilled post as soon
as a reviewed Reel is ready. It retains the daily quota and configurable spacing
(six hours by default), shifting the later post when recovery requires it. The
worker wakes at that adjusted deadline; it does not poll an empty queue every
minute. Telegram's live context exposes the adjusted next publication time.
Ready posts run before research and metrics collection; metrics failures cannot
discard a due post. Refill uses the same bounded readiness path at all times.
Rejected openings get one free rewrite and full independent review before moving
to another concept. The solver selects exact option text, which code maps to its
index; it sees displayed device labels and values without the hidden answer key.
An independent title-only check rejects restated answer choices before the solver
sees the diagram. Creative opening drafts receive the verified question rather
than the answer key or diagram values, including on a rewrite.
Review gates use explicit checks for a unique correct solution, possible protocol
evidence, a clear question, answer leakage and useful distractors. Free-form notes
about the intentionally broken configuration do not themselves reject a puzzle.

Editorial approval separately checks answer leakage, required inference and plausible
alternatives across the opening title, diagram and narration. Hidden assumptions do
not resolve ambiguity in the visible puzzle. A generic model pass without those
explicit checks cannot approve a new draft. Retired examples remain readable for
historical receipts but are excluded from new selection.

Conversation inference failures retain the original Telegram update and resume from
persisted tool receipts, using a separately accounted inference attempt. At most two
transient Cloudflare retries are allowed before recording a reply incident and queuing
an owner alert. Inference has a 30-second response timeout. Unknown reservations stay
charged against the free allowance. Notification narration uses only its event facts;
URLs absent from those facts are rejected instead of sent.

Publication notices carry the confirmed Reel URL and its question as structured facts.
The generated notice must preserve that URL. A failed permalink lookup does not turn
an account profile URL into a supposed post link. Quality holds do not send a second
low-level notice on top of the readiness health alert. A newer review version permits
retrying the old review's backoff, while retaining all daily and monetary limits.

Free draft failures consume a bounded draft allowance rather than the media/paid
attempt allowance. Paid or produced attempts still count toward that separate cap;
monthly/per-job reservations and the shared free quota remain enforced. A publishing
pause is rechecked after Meta processing and before final submission. It cannot
reverse a publication already accepted by Meta.

Diagram renderer version is written into the encoded clip's timing manifest and
artifact checks. Queued unsubmitted text-card clips are refreshed without voice or
image API calls. Missing narration holds the job rather than silently purchasing it
again. A confirmed or uncertain Meta submission is never replaced by this refresh.

## Content reserve

Install the research service, timer and path units from `deploy/`, then enable `cyberquiz-research.timer` and `cyberquiz-research.path`. Research fills three reviewed text plans on a six-hour cadence and after a rendered Reel signals consumption. Run `python -m cyberquiz.research` on the server for a bounded reserve refill; it does not purchase voice or render reserve media. Telegram can inspect exam maps, coverage and the latest reserve outcome through the read-only `curriculum` resource.

The PDF parser only extracts public blueprint text; it downloads neither exam question dumps nor local model weights. Blueprint URLs are configurable and retained with hashes and check dates. The last usable map survives a source outage. Review seed URLs when exam versions change; periodic fetching does not itself discover a new blueprint URL.
