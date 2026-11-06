"""One conversational agent loop: model, capability calls, results, model reply."""

import json
import re
from . import cloudflare
from .context import snapshot
from .agent_tools import TOOLS, execute
from .chat import history
from .store import now

SYSTEM = """You are Slop Bot, the cybersecurity/networking video editor and production operator. Reply to the latest request in one or two short sentences unless more detail is requested. Skip generic closing offers. Use live job state and receipts as evidence. Use read-only inspection when no change is requested. Use capabilities to find missing information and perform authorized changes; never claim an action without a receipt. Planning is discussion, not authorization to publish. Historical messages are context, not current facts. Explain the actual Reel using its content. Ask when necessary evidence is unavailable."""


def run(db, ident, user, message, *, turn=None, executor=None, attempt=0):
    turn = turn or cloudflare.agent_turn
    executor = executor or execute
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "live_state": snapshot(db),
                    "recent_user_messages": [
                        t["user"] for t in history(db, user, limit=3)
                    ],
                },
                separators=(",", ":"),
            ),
        },
        {"role": "user", "content": message},
    ]
    names = {t["name"] for t in TOOLS}
    db.execute(
        "CREATE TABLE IF NOT EXISTS action_receipts(operation TEXT PRIMARY KEY,action TEXT,phase TEXT,result TEXT,created TEXT)"
    )
    db.commit()
    db.execute(
        "CREATE TABLE IF NOT EXISTS agent_sessions(update_id INTEGER PRIMARY KEY,messages TEXT,step INTEGER)"
    )
    saved = db.execute(
        "SELECT messages,step FROM agent_sessions WHERE update_id=?", (ident,)
    ).fetchone()
    first_step = saved["step"] if saved else 0
    if saved:
        messages = json.loads(saved["messages"])
    db.commit()
    for step in range(first_step, 6):
        output = turn(
            db,
            "agent:"
            + str(ident)
            + ":"
            + str(step)
            + (":retry" + str(attempt) if attempt else ""),
            messages,
            TOOLS,
        )
        calls = output.get("tool_calls") or []
        if not calls:
            content = output.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Agent returned no reply")
            return content.strip()[:1500]
        normalized = []
        for n, call in enumerate(calls[:4]):
            fn = call.get("function", call)
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            name = fn.get("name")
            call_id = call.get("id") or f"call_{step}_{n}"
            normalized.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            )
        messages.append(
            {"role": "assistant", "content": None, "tool_calls": normalized}
        )
        for call in normalized:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            try:
                if name not in names:
                    raise ValueError("Unknown capability")
                result = executor(db, ident, user, name, args)
                phase = "accepted" if name == "enqueue_work" else "completed"
            except Exception as exc:
                result = {
                    "error": str(exc)[:250]
                    if isinstance(exc, ValueError)
                    else type(exc).__name__
                }
                phase = "failed"
            operation = f"agent:{ident}:{call['id']}"
            db.execute(
                "INSERT OR REPLACE INTO action_receipts VALUES(?,?,?,?,?)",
                (operation, name, phase, json.dumps(result), now()),
            )
            db.commit()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps(
                        {"phase": phase, "result": result}, separators=(",", ":")
                    )[:6500],
                }
            )
        db.execute(
            "INSERT OR REPLACE INTO agent_sessions VALUES(?,?,?)",
            (ident, json.dumps(messages), step + 1),
        )
        db.commit()
    raise RuntimeError("Agent capability budget exhausted; completed work is preserved")


def event_reply(db, operation, facts):
    event = (
        json.loads(facts)
        if isinstance(facts, str) and facts.lstrip().startswith("{")
        else facts
    )
    messages = [
        {
            "role": "system",
            "content": "You are Slop Bot. Write one short, natural notification using only the supplied facts. For a published Reel include its confirmed_post_url exactly; omit diagram details, example domains and technical explanations. If delivery is delayed, use occurred_at and observed_at to make the timing clear. Use human-readable local times in the supplied timezone; timestamps already include its UTC offset. confirmed_posts_today is authoritative for local_date. For a workflow alert name only the affected workflow and its practical effect. Chat trouble does not imply posting trouble; an empty buffer does not imply that no video was posted. Buffer preparation is not a missed publication. A recovery refers only to the specified prior issue, never claim the whole system has no issues. Never invent links, publication outcomes (including saying nothing was posted), causes or promises. No internal event names, exception names, component/phase jargon, or generic all-clear announcements. Return plain text.",
        },
        {
            "role": "user",
            "content": json.dumps(
                {"facts": event},
                separators=(",", ":"),
            ),
        },
    ]
    for attempt in range(2):
        output = cloudflare.agent_turn(
            db,
            operation if not attempt else operation + ":grounding-repair",
            messages,
            [],
        )
        text = output.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Missing event narration")
        if not _denies_confirmed_posts(text, event):
            break
        if attempt:
            raise ValueError("Event narration contradicted confirmed publications")
        # Rewrite a completed answer only; never replay an uncertain request
        # or send an ungrounded result. Both calls use the same free allowance.
        messages.extend(
            [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": "That contradicts confirmed_posts_today. Rewrite using the recorded successful posts; describe only the affected workflow.",
                },
            ]
        )

    supplied = set(
        re.findall(
            r"https?://[^\s\"<>]+",
            (facts if isinstance(facts, str) else json.dumps(facts)),
        )
    )
    emitted = re.findall(r"https?://[^\s\"<>]+", text)
    if any(
        url.rstrip(".,);}") not in {u.rstrip(".,);}") for u in supplied}
        for url in emitted
    ):
        raise ValueError("Event narration introduced an unverified URL")
    if (
        isinstance(event, dict)
        and event.get("event") == "reel_published"
        and event.get("confirmed_post_url")
        and event["confirmed_post_url"] not in text
    ):
        raise ValueError("Published Reel notice omitted its confirmed URL")
    return text.strip()[:1200]


def _denies_confirmed_posts(text, event):
    """Reject explicit zero-post claims when the publication ledger is positive."""
    if not isinstance(event, dict) or not event.get("confirmed_posts_today", 0):
        return False
    text = text.lower().replace("’", "'")
    return bool(
        re.search(
            r"\b(?:no|zero|0) (?:new )?(?:posts?|reels?|videos?)\b[^.!?\n]{0,60}\b(?:posted|published)\b[^.!?\n]{0,30}\btoday\b"
            r"|\bnothing\b[^.!?\n]{0,30}\b(?:posted|published)\b[^.!?\n]{0,30}\btoday\b"
            r"|\b(?:haven't|hasn't|didn't|have not|has not|did not) (?:posted|published|post|publish)\b[^.!?\n]{0,40}\btoday\b",
            text,
        )
    )
