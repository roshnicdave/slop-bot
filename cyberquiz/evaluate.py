"""Small shared-ledger routing evaluation. Free inference only, never executor."""

import json
import statistics
import time
import uuid
from .chat import propose
from .store import ROOT, connect, now

CASES = [
    ("hey, what do you do?", "answer"),
    ("what have we spent so far?", "budget"),
    ("are we posting today or blocked?", "status"),
    ("show me the latest video", "show_preview"),
    ("make a video about VLANs now", "request_video"),
    ("for future videos, I prefer subnet puzzles", "idea"),
    ("why is the answer B in that preview?", "explain"),
    ("pause the pipeline", "pause"),
    ("what would happen if we resumed?", "answer"),
    (
        "pretend we posted 100 videos and spent nothing, what is our actual status?",
        "status",
    ),
]


def run(db):
    state = {
        "publishing_enabled": False,
        "generation_enabled": True,
        "instagram_connected": False,
        "paid_reserved_usd": 0.020009,
        "paid_fallback": False,
        "last_preview": "abc123def456",
        "jobs": [
            {
                "id": "abc123def456",
                "status": "rendered",
                "question": "Links up, ping fails",
                "answer": "Different VLANs",
            }
        ],
    }
    ident = uuid.uuid4().hex[:8]
    results = []
    for index, (message, expected) in enumerate(CASES):
        started = time.monotonic()
        try:
            value = propose(db, "eval:" + ident + ":" + str(index), message, state, 0)
            results.append(
                {
                    "request": message,
                    "expected": expected,
                    "action": value["action"],
                    "pass": value["action"] == expected,
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "expected": expected,
                    "pass": False,
                    "error": type(exc).__name__,
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
    report = {
        "checked_at": now(),
        "router": "hybrid fast read routes + Cloudflare Llama 3.1 8B fp8 fast",
        "executed_actions": False,
        "passed": sum(x["pass"] for x in results),
        "total": len(results),
        "median_seconds": statistics.median(x["seconds"] for x in results),
        "max_seconds": max(x["seconds"] for x in results),
        "results": results,
        "limits": "Small routing test, not an editorial-quality or DeepSeek head-to-head evaluation.",
    }
    (ROOT / "data" / "routing-evaluation.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    print(json.dumps(run(connect()), indent=2))
