# Agent architecture

The system combines a bounded editorial agent with deterministic execution and persistent evidence. It runs on the existing small Lightsail instance without a multi-agent framework or a continuously thinking model.

## Decision cycle

1. Collect dated primary articles, authorized Instagram observations, comparable-age own-account results and durable operator feedback.
2. Propose fresh diagnostic topics, inspect bounded primary-source text, construct a typed technical diagram and draft a short question.
3. Check literal supporting evidence, factual consistency, ambiguity, previous learning objectives, layout and spoken claims. A separate review can reject a draft. Executable scenes retain their mathematical validators; new source-grounded topics use source/semantic checks and retain that distinction in their provenance.
4. Generate concise speech, measure each clip, render the timeline and check the decoded audio/video. Production reserves the entire narration estimate before purchasing its first segment.
5. Publish through the official API. Persist uncertain side effects and stop duplicate submission. Notify after a confirmed post, then erase staging media.
6. Observe results, evaluate the active experiment, adopt supported changes and propose the next hypothesis. Keep every decision, assignment, rejection and outcome as text.

## Learned policy and fixed boundaries

The agent proposes topics, wording strategies, new numerical pacing values and posting windows. SQLite records the evolving policy and its evidence. One active content experiment at a time helps interpret results. At least ten comparable samples per arm and a bootstrap interval are required for adoption; small or missing data cannot be called success. User feedback is durable input to drafting and future experiments.

Spending ceilings, private Telegram access, supported rendering primitives, source trust boundaries, technical validation, the operator's visual requirements and duplicate-publication protections are enforced in code. A generated policy cannot grant itself shell access, rewrite validators, change credentials, spend beyond limits or promote an unsupported technical claim.

## Long-running operation

A durable SQLite inbox survives process restarts. An authenticated local Unix datagram wakes the worker for Telegram work/configuration changes. Otherwise it sleeps until the next posting deadline, daily planning boundary or six-hour housekeeping deadline. Systemd restarts the independent ingress, conversation and production services. A global worker lease serializes production/publishing while chat remains responsive.

Sources and daily decisions are cached. New source attempts, external request IDs and paid reservations have stable identities. There are at most two new-source attempts per research day across both posts and restarts. Uncertain inference is not submitted again under a fresh identity. Daily Meta credential checks alert before data-access expiry and pause posting after revocation.

The text ledger outlives disposable videos. Telegram file IDs support resending without local video retention. SQLite backups rotate across seven days. Whole-server loss still requires an off-host backup strategy; local backups are not disaster recovery.

## Known limits

No system can promise unlimited interesting, true questions or virality. New topics can continue beyond the original scenario bank, but a day with no qualifying source/question is skipped. Source entailment and semantic novelty reviews can miss errors. Public competitor counts do not reveal retention or reach. Complete automatic reconciliation of unknown Instagram publishing outcomes, automated factual-correction handling and off-host disaster recovery remain unfinished. These states require an actionable owner alert, not fabricated success.

## Research informing this design

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents): simple patterns, clear tool interfaces and evaluator feedback.
- [Anthropic: Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents): relevant durable memory and bounded context.
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents): traces, multiple checks and regression evaluation.
- [AWS: Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/): persisted operation identity and uncertain outcomes.

These sources support engineering practices, not claims that a particular hook, color or posting time causes reach.

## Telegram as the operating interface

Ordinary messages become typed intents against the same SQLite jobs and configuration used by autonomous scheduling. The conversational process acknowledges durable work quickly; production and publishing run in the separate worker. There is no second chatbot-owned queue. Status reads actual job state, queue readiness, active requests and unresolved publication outcomes.

An explicit “post the next Reel now” request binds its Telegram update ID to a job in `operator_requests`. It selects the oldest eligible queued job, or generates one under a stable request slot when the queue is empty. It can bypass the scheduled clock/temporary scheduling hold for that request only. It cannot override pause, authorization, automatic quality gates, spending limits or unknown publication outcomes. The resulting post counts in the scheduler’s existing daily count and spacing checks. Redelivery does not create another post. No new Telegram menu command is advertised.

This is a bounded autonomous workflow with model-driven editorial choices and conversational intent routing, not unrestricted self-modifying code. New operational capabilities still require implementation and tests; the bot must not claim actions outside its executor.

## Readiness buffer

The autonomous worker keeps one approved, rendered Reel staged when generation is enabled. Scheduled posting consumes that queue before creating more work; a confirmed publication wakes the worker to refill. Readiness attempts are durable, capped at daily cadence plus one, and back off after failure. Pause and unresolved production/publication states suppress refill. Budget and novelty/quality gates remain authoritative; readiness is not guaranteed during provider outages or exhausted quotas. Media is temporary staging until publication, not an archive.

## Operational retrieval and conversational grounding

Every Telegram turn receives a fresh operational snapshot: global ready count, recent job stages, active requests, refill attempts and persisted preferences. It does not infer global queue emptiness from the last few jobs. The control model can request bounded, read-only retrieval from six named resources: queue, preferences, activity, research, experiments and budget. These queries use fixed SQL and approved metadata files; no credentials, arbitrary SQL, shell or filesystem access is exposed. At most three reads are permitted per turn. Earlier assistant prose is excluded from authoritative state to avoid repeating stale claims; recent user messages and retrievable action outcomes preserve follow-up context.

The eligible Cloudflare Mistral model now handles conversational orchestration as well as editorial work. Chat remains in its own protected quota category with conservative reservations and provider-reported neuron reconciliation; no paid fallback. Its answers remain fallible, so the executor still validates permissions, typed arguments, budgets and publication state. Follow-up questions cannot write preferences merely because the model emitted a feedback field; preference writes require the idea action. The real model was tested with the operator's advice-storage and queue-readiness follow-ups without executing actions or sending Telegram messages.
