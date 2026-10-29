# Operations

The source is independent of other projects. Runtime files stay in `~/cyber-quiz` on the existing AWS server; credentials remain outside both the local and remote source trees.

## Processes

- `cyberquiz-telegram`: allowlisted Telegram ingress and `/budget`.
- `cyberquiz-conversation`: ordered per-user chat, bounded LLM proposals, typed execution.
- `cyberquiz-worker`: daily research, production, publishing and metrics.
- `cyberquiz-media`: HTTPS media serving with an exact file allowlist.

Normal Telegram text goes into the supervisor inbox. A render does not block chat. `/start` is only the Telegram onboarding handshake; the published command menu contains only `/budget`. Plain-language pause is still available.

## Deployment

Run `python3 deploy/upload.py`. Stop the three Python services for the source swap, then restart them after server checks. The uploader preserves the production SQLite ledger, live pause/publication state, and lowered budget ceilings. Existing server credentials are preserved unless `--sync-secrets` is explicitly supplied. Never replace production state with a laptop snapshot.

Run `python3 deploy/aws_access.py 'systemctl is-active cyberquiz-telegram cyberquiz-conversation cyberquiz-worker cyberquiz-media'` to check service state. The helper obtains temporary AWS SSH credentials without printing them.

## Cost controls

Reservations precede external inference. Successful text calls may report measured neurons: account those with 10% headroom plus one neuron, retaining the original reservation for audit. Unknown calls and audio without reported measurements retain their full reservation. The shared cap and category caps apply transactionally to the resulting conservative totals. No paid provider can be used without a separate explicit configuration change.

The worst-case voice calculation is `ceil(600 * 1.36364 * 1.25) + 3*10`, about 1,053 neurons/video. Two videos fit the 3,000 voice allocation. The provider's account-wide Free limit can still be consumed by unrelated applications; this system cannot promise remaining capacity it cannot observe. Free exhaustion stops inference.

`data/latest-usage.json` holds the last provider audit. Fal reporting is currently unauthorized, so the old approximately $0.02 cannot be presented as an invoice-verified total. DeepSeek balance reads do not spend inference credits. The existing Lightsail bundle is $5/month; account-wide AWS charges have not been reconciled.

## Holds and recovery

No routine video approval is needed. Unsupported facts, ambiguous questions, layout overflow, invalid media or exhausted quota hold the job. Automatic editorial retries are bounded to one alternative candidate. A saved completed voice file is reused. An uncertain inference or publishing call is not blindly resubmitted.

Published media is removed only after a confirmed media ID and publication timestamp plus one hour. Keep receipts, plans and quality reports. A media container alone is insufficient for deletion.

## Current blockers

Official Instagram API authorization is still missing. Linking the Facebook Page was completed, but is separate from granting the app publishing access. The permission review must be completed in Meta and the token saved via the hidden connector prompt. Do not put tokens in Telegram or GitHub.

Business Discovery and own post metrics become available only after the relevant API scopes are connected. Competitor captions/counts are observable; competitor reach/watch time and automatic video/audio inspection are not currently connected. The small routing evaluation is not proof of broad model reliability. Local backups do not protect against loss of the entire server.
