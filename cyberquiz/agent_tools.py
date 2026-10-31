"""Typed capabilities of the running agent, independent of chat wording."""

import json
from .store import config, now
from .context import read, snapshot, CATALOG


def tool(name, description, properties, required=()):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


TOOLS = [
    tool(
        "read_system",
        "Retrieve live details from the operating system.",
        {"resource": {"type": "string", "enum": list(CATALOG)}},
        ["resource"],
    ),
    tool(
        "set_pipeline_running",
        "Enable or pause autonomous generation and publishing. Enabling verifies current Meta access first.",
        {"enabled": {"type": "boolean"}},
        ["enabled"],
    ),
    tool(
        "set_publishing",
        "Enable or pause the automatic schedule only. This does not submit a Reel for publication.",
        {"enabled": {"type": "boolean"}},
        ["enabled"],
    ),
    tool(
        "set_schedule",
        "Set one or two daily posting times in the configured timezone, at least six hours apart.",
        {"slots": {"type": "array", "items": {"type": "string"}}},
        ["slots"],
    ),
    tool(
        "lower_budget",
        "Lower the shared rolling monthly paid-AI cap.",
        {"monthly_usd": {"type": "number"}},
        ["monthly_usd"],
    ),
    tool(
        "save_preference",
        "Persist new operator advice for research and scripts.",
        {"text": {"type": "string"}},
        ["text"],
    ),
    tool(
        "enqueue_work",
        "Submit work for execution, rather than only changing settings. publish_next publishes the next ready Reel immediately; create_preview generates a preview; show_preview delivers it; research refreshes the configured daily primary-source feeds, not arbitrary topic or live-news searches; ensure_ready replenishes the queue. Publication must be enabled first. Completion is asynchronous.",
        {
            "task": {
                "type": "string",
                "enum": [
                    "publish_next",
                    "create_preview",
                    "show_preview",
                    "research",
                    "ensure_ready",
                ],
            },
            "job_id": {"type": "string"},
        },
        ["task"],
    ),
]


def execute(db, update_id, user, name, args):
    from .telegram import update_config
    from . import control

    if user not in config()["telegram_allowed_user_ids"]:
        raise ValueError("Unauthorized operator")
    if name == "read_system":
        return read(db, args["resource"])
    if name == "set_pipeline_running":
        enabled = args["enabled"]
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        from .auth_health import check

        access = check(force=True) if enabled else False
        update_config(
            {
                "emergency_pause": not enabled,
                "generation_enabled": enabled,
                "publishing_enabled": enabled and access,
            }
        )
        return {
            "requested_running": enabled,
            "access_valid": access,
            "actual_state": snapshot(db),
        }
    if name == "set_publishing":
        return control.set_publishing(args["enabled"])
    if name == "set_schedule":
        return control.set_schedule(args["slots"])
    if name == "lower_budget":
        return control.lower_budget(args["monthly_usd"])
    if name == "save_preference":
        text = args["text"]
        if not isinstance(text, str) or not 0 < len(text) <= 700:
            raise ValueError("Preference must be 1-700 characters")
        from .chat import preference

        ident = preference(db, user, text)
        return {
            "saved_id": ident,
            "text": text,
            "use": "Future research and script drafting; existing renders unchanged.",
        }
    if name == "enqueue_work":
        commands = {
            "publish_next": "/publish-next",
            "create_preview": "/next",
            "show_preview": "/preview",
            "research": "/research",
            "ensure_ready": "/refill",
        }
        task = args["task"]
        if task not in commands:
            raise ValueError("Unknown task")
        # Stable child IDs permit several distinct tasks in one conversation turn.
        ident = -(int(update_id) * 100) + list(commands).index(task)
        command = commands[task]
        job = args.get("job_id")
        if job:
            if (
                task != "show_preview"
                or not isinstance(job, str)
                or not db.execute("SELECT 1 FROM jobs WHERE id=?", (job,)).fetchone()
            ):
                raise ValueError("Unknown preview job")
            command += " " + job
        db.execute(
            "INSERT OR IGNORE INTO telegram_updates VALUES(?,?,?,?,?,?)",
            (
                ident,
                user,
                command,
                "queued",
                json.dumps({"parent_update": update_id}),
                now(),
            ),
        )
        db.commit()
        from .wakeup import signal

        signal()
        row = db.execute(
            "SELECT status FROM telegram_updates WHERE id=?", (ident,)
        ).fetchone()
        return {
            "request_id": ident,
            "task": task,
            "status": row[0],
            "research_scope": "Configured daily primary-source feeds only; no topic-specific or live-news search was submitted."
            if task == "research"
            else None,
        }
    raise ValueError("Unknown capability")
