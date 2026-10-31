"""One conversational agent loop: model, capability calls, results, model reply."""

import json
from . import cloudflare
from .context import snapshot
from .agent_tools import TOOLS, execute
from .chat import history
from .store import now

SYSTEM = """You are Slop Bot, the cybersecurity and networking video editor and production operator. You can discuss ideas and write concrete video plans directly; tools are needed only to retrieve evidence or change system state. Answer the latest request directly and briefly. Use capabilities to inspect facts and carry out authorized changes. Confirm outcomes only from receipts; queued work is not completed work. A request for a plan means discuss the plan before creating or publishing. Ground plans in a specific incident or mechanism; ask for missing facts you cannot retrieve instead of listing generic formats. Historical messages are context, not current state or authorization. Read detailed system resources when needed; do not recap them unless asked. Never invent news, links or capabilities."""


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
            return content[:1500]
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
    output = cloudflare.agent_turn(
        db,
        operation,
        [
            {
                "role": "system",
                "content": "Describe this event naturally in at most two short sentences. Use only the supplied event facts. Include a post URL only if an exact confirmed URL is supplied. Never invent URLs, links, publication confirmations, causes, or future outcomes. An earlier missed slot is not a current outage; distinguish them. No capability lists or exception jargon. Return plain text.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"facts": facts},
                    separators=(",", ":"),
                ),
            },
        ],
        [],
    )
    text = output.get("content")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Missing event narration")
    import re

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
    return text[:1200]
