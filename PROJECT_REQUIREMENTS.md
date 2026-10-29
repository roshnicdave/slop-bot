# Persistent project requirements

User requirements, updated 2026-10-28. This file is the working contract for future sessions. Never store API tokens here.

- Build the autonomous system; Codex doing one-off daily research manually is not the intended product.
- Run continuously on the existing AWS Lightsail instance. Do not add paid compute or subscriptions silently. Existing AWS costs are separate from the new API allowance.
- A couple of dollars per month maximum in new API spending. Current chosen shared cap: $1.80 per rolling 31 days and $0.03 per job. Reserve before calls, count failures, avoid paid automatic retries, log request IDs, verify provider usage rather than presenting calculated prices as billed proof.
- Target 1–2 posts daily. Start at 1/day; compare 2/day with a baseline rather than claiming either ensures virality.
- Instagram target: @cybersec.peter, switched by owner to professional/Creator.
- Keep AI voice. Use AI for daily research/editorial choices and bounded creative assistance. Use generated imagery only where it genuinely explains the subject. Decorative cyber art is not a substitute for a useful visual.
- The first abstract-background trivia/CVE videos were rejected as poor quality. Do not publish them or reuse that format as the default.
- Visual reference supplied by user: a white/light quiz, large navy question header, visible PC–switch–PC topology, VLAN labels and green link lights, four large answer options. Watermark identifies Networking with Israr (@netwithisrar). Reference is inspiration, not permission to reuse its assets or proof of measured virality.
- Research public successful quiz content, inspect actual visual examples where accessible, record dates and visible metrics, and distinguish observations from speculation. Do not label search snippets as verified performance or a still image as a watched video.
- Use a consistent visual identity and rotate useful templates: diagnose a diagram, spot a configuration error, trace a packet/security decision. Test templates against the account's own comparable-age results.
- Questions should have an interesting, concrete puzzle and plausible distractors, with enough clues for one defensible answer. Do not pad novelty by renumbering IP addresses alone. Avoid obvious acronym recall, fake failure statistics, deliberate ambiguity, exploitative job promises and empty comment bait.
- Show the problem immediately. Include short, natural AI narration, a bounded thinking pause, an answer reveal and visual fix/explanation. Avoid long intros/outros and text-heavy CVE/date readings.
- Gather current primary sources daily, plus own post results and user suggestions. Propose ideas automatically, validate technical logic, retain sources and dates, deduplicate semantic concepts, and maintain an experiment/learning log. Trends are not automatically evidence of viral Instagram performance.
- Research caption hooks, CTAs and substantive comment/reply patterns. Draft useful replies; do not auto-message arbitrary Instagram users without explicit authorization.
- Engineer continuous operation: durable jobs and command inbox, idempotence, safe handling of unknown publish outcomes, bounded read retries, price checks/circuit breakers, expired credential detection, stale source handling, recovery, pause, and actionable alerts.
- Telegram bot: @peterslopbot. Bot token is stored only in the private credentials file. Authorized Telegram user IDs: 8010764520 and 8861370667. No other user or group may control it. Both share the same queue and spending cap.
- Telegram must stay responsive while research/rendering runs, provide status/budget/previews/pause/resume/idea input through normal chat, and notify both users who have started the bot after confirmed Instagram publication, including the post link when available. Do not claim publication on a mere upload or uncertain timeout.
- Consider Cloudflare Workers AI's free allowance where useful; use documented eligible models, no silent paid-plan upgrade or fallback. Its frontier DeepSeek models currently require paid billing; an eligible free small model could replace the tiny daily planning call, not the technical validator.
- Repository: Slop Bot is a separate project. Canonical working folder is /Users/rd/Documents/ChatGPT/insta. Its GitHub repository is roshnicdave/slop-bot. Do not modify or push other projects. This supersedes the earlier repository instruction, per the owner on 2026-10-28.

## Connection state

- Fal key works for inference and pricing, but its usage-report endpoint returns 403. Billed-cost proof still needs reporting access or dashboard reconciliation.
- Initial DeepSeek key became invalid. Owner supplied a replacement; read-only authentication and a complete AWS generation run succeeded. Never echo credentials.
- Meta developer registration completed by owner. Apps: Cyber Peter Quiz Engine (unused) and Cyber Peter Publisher (Business app, ID 2096661160971180). Both shown dashboards expose Facebook Login only; direct Instagram Login is documented but absent in this account's UI.
- Owner authorized creating the free Facebook Page Cybersec Peter. It exists (profile URL id 61596057808748; management asset id 1471076912747976). Page creation optional setup completed, Instagram profile website added. Linking to @cybersec.peter is complete. Official app authorization and the long-lived publishing token are still pending.
- HTTPS media host: https://quiz-44-243-81-67.sslip.io. Only intended MP4 media and a privacy/health endpoint are public.
- Existing Lightsail: btc15-bot, us-west-2, Amazon Linux 2023, ~419 MiB RAM. The new visual renderer completed a 16.5-second production test on AWS, including separate narration segments and MP4 decoding.
- Publishing remains blocked by the missing Instagram API token. Once connected, automatic quality gates replace routine human review.

## Later requirements and implementation update

- Prefer normal Telegram conversation through a free LLM; do not expose a large command menu as the main interface. Fast spend/status/pause paths remain available.
- Owner confirmed Workers Free and asked to use the existing Wrangler login. No new Cloudflare token prompt is needed. Protected Worker `peterslop-ai` is deployed with an AI binding.
- Standard inference and voice use eligible Cloudflare models only, with a shared 8,000-neuron UTC-day budget using measured usage where available and conservative reservations otherwise and no automatic paid fallback.
- Modern agent-engineering research is saved in `AGENT_ARCHITECTURE.md` and `research/agent-sources.json`; primary sources include Anthropic, LangGraph, Temporal, AWS Builders' Library and Cloudflare.
- The exact original @netwithisrar reference Reel was inspected: URL /netwithisrar/reel/De6FlZUMCTb/, ~10 seconds, immediate diagram/question/four options/countdown, short caption, and visible explanatory/ambiguity comments. The creator grid showed about 249K views; reach and watch-through were unavailable. Observation record saved separately.
- New AWS prototype a6a4c7f29a6b is 16.3 seconds, with Cloudflare AI voice and an animated packet/fix, and was sent to the registered owner Telegram chat. No new Fal/DeepSeek paid calls were used for it. It is superseded and not eligible for publishing.
- Current conversational bot is deployed; broader agent evaluations, memory, novel question coverage, visual watchlist automation and completed Instagram authorization remain work in progress. Do not claim all of this is finished or proven viral.


## Latest owner decisions — 2026-10-28

- This is an independent project: local folder /Users/rd/Documents/ChatGPT/insta, private GitHub repository roshnicdave/slop-bot.
- No routine approvals. Automatically publish only after quality gates and official account authorization.
- Remove generated video assets after confirmed publication; retain a compact audit trail.
- Telegram menu: budget only. Normal messages go to the LLM control plane; replies must be fast and concise.
- Voice and subtitles must align with actual scene timing.
- Study Reels hooks, pacing, voice and payoff in addition to post captions. User supplied three multilingual-caption examples, then noted the tactic may not apply to this niche. Treat it as a hypothesis, not a guaranteed growth mechanism.
- Source, capabilities, identity and operational settings should be configurable. Executable protocol checks remain deterministic; creative wording and scenario variants need not be fixed scripts.
