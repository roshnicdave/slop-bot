# Agent engineering decision record

Status: researched architecture and partial implementation, 2026-10-28. This document does not claim the full autonomous loop is already deployed. The current implementation is being migrated from a basic scripted generator to this design.

## What the engineering evidence says

Anthropic distinguishes fixed workflows from agents that choose their process and tools based on observations. Its practical advice is to start with simple composable patterns, add autonomy where a task needs it, and set stopping conditions. For this project, source discovery and editorial selection need bounded flexibility; rendering and publication need predictable execution.
Source: https://www.anthropic.com/research/building-effective-agents

Anthropic's context-engineering guidance emphasizes selective, high-signal context and persistent notes for long tasks. We should retrieve the relevant preferences, recent concepts, source evidence and measured results for each decision, rather than replaying the entire Telegram history or placing all documents in every prompt.
Source: https://www.anthropic.com/research/effective-context-engineering-for-ai-agents

Anthropic's research-system account describes persistent plans, evaluation, recovery, and explicit effort allocation. Its reported multi-agent token consumption was far higher than chat in that particular system. That is not a universal price multiplier, but it is a reason to measure added value before introducing a swarm into a sub-$2 monthly pipeline.
Source: https://www.anthropic.com/research/multi-agent-research-system

LangGraph separates thread checkpoints from longer-lived stores. A live conversation, an interrupted render and a long-term topic preference are different kinds of state. We need those distinctions even if SQLite and ordinary Python implement them, rather than importing a large framework into a 512 MB server.
Source: https://docs.langchain.com/oss/python/langgraph/persistence

Temporal's AI cookbook demonstrates durable agent loops, tool activities, human approval signals and hard-rule overrides. The pattern applies here: each external side effect must have a durable record and a clear recovery policy. We do not need to run a Temporal server on this tiny VPS to apply the principle.
Source: https://docs.temporal.io/ai/cookbook

Cloudflare documents routing, orchestrator/worker and evaluator/optimizer patterns. Wrangler is already authenticated with AI access, so a small protected Worker can expose eligible Workers AI models while AWS retains orchestration. We should not migrate durable business state merely to adopt an agent SDK.
Source: https://developers.cloudflare.com/agents/concepts/agentic-patterns/

## Architecture selected

1. **Conversational supervisor.** A small free Cloudflare LLM translates ordinary Telegram language into a typed proposed action or an evidence-grounded answer. Allowed users are 8010764520 and 8861370667. Conversation summaries and selected preview IDs are durable. A model never receives credentials, arbitrary shell tools, direct SQL, or authority to raise budgets. Plain status/pause remain fast even if the model is unavailable.
2. **Research/editorial agent.** A daily event gathers a bounded set of current primary sources, public watchlist observations where supported, our own post metrics, recent concepts and user feedback. The agent proposes several ideas, chooses an appropriate visual template and explains its evidence and test hypothesis. It can request a limited number of additional allowed-source reads. It cannot equate a fresh CVE or a creator's follower count with proof of viral performance.
3. **Question compiler and factual verifier.** Accept a structured scene, assumptions, answer and source links. Execute networking checks for supported scenario families. Reject multiple plausible answers, incorrect fixes, missing evidence, stale claims and unsupported mechanisms. An LLM critic can assess wording and visual clarity; it cannot override failed technical checks. New mechanisms outside the verifier's coverage are held for review rather than published confidently.
4. **Production worker.** Reusable local diagram/config/packet-flow templates provide crisp labels and consistent style. Cloudflare AI voice is tested against the approved quality target. Images are optional explanatory assets, not decorative filler. Long generation/render work runs outside the control process and writes immutable versioned artifacts.
5. **Publication worker.** Publishes approved/eligible artifacts only in configured slots. Save container ID before continuing. A network timeout is an uncertain outcome, not proof of failure. Reconcile the original container and account media; never blindly post again. Notify both Telegram users who have started the bot only after confirmed publication, with permalink and budget/usage information.
6. **Learning worker.** Snapshot results at comparable ages. Separate topic, hook, pacing, template, caption and CTA changes. Retain a baseline and exploratory allocation. Distinguish reach, watch time, follows per reach, substantive comments and shares. Learn from repeated evidence, not one lucky post. Flag factual corrections as quality incidents even if the offending post got engagement.

## Agentic, bounded decision loop

Every run has a goal, a context snapshot, available tools, an action proposal, observed results, durable memory and a stopping rule. The editorial agent can choose what evidence to inspect or which candidate to discard; it cannot spend indefinitely until satisfied. Initial limits: one daily planning run, two extra source reads, at most one critique/revision pass, and the configured shared free-neuron allowance. Exhaustion produces a saved draft and an alert, not an expensive fallback.

The scheduler wakes on time, Telegram requests, a completed job or new metrics. It does not keep an LLM thinking continuously. One process owns long-running production; a separate process handles conversation and emergency controls. Job IDs and external request IDs give every action a stable identity across restarts.

## Memory and evidence

- Project policy: `PROJECT_REQUIREMENTS.md` plus versioned configuration.
- Conversation: short per-chat summaries, user preferences and pending confirmations; retrieve only relevant entries.
- Editorial: idea hypotheses, semantic concept fingerprints, recent variants, rejected reasons and next experiments.
- Evidence: URL, publication/retrieval dates, source hash, supported claim and observed social metrics with timestamps.
- Execution: job state, step attempts, reservation, provider request ID, artifact checksums, approval and publish receipt.
- Learning: comparable-age measurements, uncertainty, chosen next test and factual correction history.

Do not call IP renumbering a new concept. Do not call a search result an inspected video. Do not call a provider price calculation an invoice-verified cost.

## Free-first routing and cost accounting

Cloudflare's Workers Free allocation is 10,000 neurons/day; excess requests fail on Free. The owner confirmed Free. We enforce an internal shared 8,000-neuron reservation budget across both users, conversation, daily research, critique and voice. Standard operation has no paid fallback, no frontier model selection, no AI Gateway credits and no automatic plan upgrade. A protected Worker uses existing Wrangler OAuth for deployment; AWS holds only the narrow endpoint secret.
Source: https://developers.cloudflare.com/workers-ai/platform/pricing/

Use the free small model for tool routing and bounded drafting first. Evaluate its ideas and instruction-following before assigning open-ended research. Aura-1 voice is eligible for the allowance and must pass audio/format checks. DeepSeek and Fal remain explicitly optional paid providers with their original USD ledger; they are not silently selected when Free is exhausted. Existing two-test reservations of about $0.02 belong to the old prototype, not a demonstrated ongoing monthly bill.

## Failure policy

| Event | Behavior |
|---|---|
| Source unavailable | Bounded backoff on read; use an appropriately dated cache or evergreen material; disclose missing trend evidence. |
| Novel idea lacks a verifier | Hold the candidate, select another supported idea; do not invent a proof. |
| Repeated topic or obvious/ambiguous question | Reject before voice/render; keep rejection reason for the next planning run. |
| Model emits invalid action/schema | Reject the action; at most one free bounded correction, then explain the failure. |
| Free allocation exhausted | Stop inference until UTC reset; keep status/pause working. |
| Paid request times out | Keep its reservation and request ID; poll/reconcile that request, never resubmit automatically. |
| Renderer crashes | Rerender saved assets; publish only a complete atomic MP4; do not repay for the same voice. |
| Service restarts | Read durable inbox/job state; reclaim safe read/render steps; hold uncertain external side effects. |
| Instagram token expires | Pause publication and alert with a concrete connection step. |
| Publish response lost | Hold `publish_unknown`, reconcile original container/media, no second post. |
| Telegram delivery unknown | Record uncertainty; avoid duplicate notification storms; status remains authoritative. |
| Bad fact discovered after publication | Halt related scheduled items, flag the post and propose a correction; do not optimize false content for engagement. |

AWS's Builders' Library explains why timeouts do not establish that a side effect failed and why backoff/idempotence are separate concerns. We apply retries to safe reads and reserve/reconcile external writes.
Sources: https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/ and https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/

## Evaluations before unattended publishing

- Tool routing: ordinary requests, paraphrases, conflicting instructions, unauthorized IDs, prompt injection in source text, attempted budget increases and ambiguous approval.
- Networking: known-good and deliberately wrong scenes; single-answer checks and a fix that actually repairs the shown fault.
- Visual: render question/reveal/fix frames; check text fit, safe margins, option ordering, diagram/audio consistency and actual phone readability.
- Reliability: interrupt each external step; restart; verify no duplicate charges/posts and no lost command intents.
- Editorial: require a genuine diagnostic clue, plausible distractors, audience relevance, correct sources, no fabricated performance claims and a useful reveal.
- Model choice: compare a small fixed evaluation set before enabling the free model for higher-discretion planning. Judge schema/technical correctness and question quality separately.

## Implementation update — 2026-10-28

Independent source repository: https://github.com/roshnicdave/slop-bot. AWS retains orchestration and rendering; Cloudflare Free handles ordinary inference and voice. Llama 3.1 8B handles chat and daily selection; Mistral Small 3.1 24B handles creative copy and editorial review; Aura-1 handles voice. The Telegram menu now exposes only budget; normal text enters the control plane. Conversation history stores both sides, requests from one user execute in order, and long production is separate.

The system compiles 16 verified mechanisms, with procedural configuration variants for several families. A free creative pass writes hooks and caption openings, followed by automatic factual/layout checks and an editorial critic. Narration uses separate question, answer and fix clips; scenes and subtitle cues use measured clip durations. One-factor pacing experiments retain exploratory allocation. Routine human approval was removed at the owner's request. Generated media is deleted one hour after confirmed publication, retaining an audit receipt.

Tests cover authorization, budget races, measured/unmeasured usage, invalid scenarios, layout, malformed creative output, ordinary-message routing, media retention, uncertain publication, WAV recovery and the actual audio/video timeline. Live small-model routing initially chose 4/10 expected actions; a hybrid read router and better instructions improved the next run to 8/10 and the latest run to 10/10 on the same small diagnostic set. This is a small diagnostic set, not a comprehensive benchmark. The latest text-model calls took at most 0.47 seconds in that sample; Telegram end-to-end timing is now recorded separately.

## Research observations and limits

The exact networking quiz supplied by the owner showed about 249K views on the creator's grid. Two inspected explainers showed about 35K and 341K, at different ages; these are not controlled format comparisons. A separate 19.8-second generic quiz had 183 visible likes and two comments when inspected. None of these observations establishes why a video spread.

The owner's additional examples confirm unrelated multilingual captions: a Chinese fashion paragraph on an approximately 18-second Reel, and Ukrainian/Japanese text on two carousels. A separate account reused the same English boilerplate on posts showing approximately 33K and 693K views. Caption reuse is observable; its incremental effect in this account's niche remains unmeasured. Do not import unrelated claims as technical evidence or call carousels inspected Reels.

Meta's April 2026 Edits announcement describes personalized inspiration, comment summaries, weekly ideas, templates and caption tooling. That supports a feedback-oriented production workflow, not a claim that any particular caption guarantees reach.
Source: https://about.fb.com/news/2026/04/one-year-of-edits-built-for-and-with-creators/

## Remaining integration work

The Page link is complete; the official publishing token is missing. Business Discovery, own performance and comment reads depend on the connected scopes. Full competitor video/audio inspection, broader verified mechanisms, comprehensive restart reconciliation and off-host backup remain gaps. Do not describe those as deployed capabilities. The current Free route has no paid fallback, and historical Fal billing still lacks invoice reconciliation.
