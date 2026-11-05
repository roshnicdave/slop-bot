"""Daily discovery process, independent of the publishing worker and chat."""

import json
from .store import connect, config, now, ROOT


def reserve(db):
    cfg = config()
    if not cfg.get("generation_enabled") or cfg.get("emergency_pause"):
        return {"status": "paused"}
    from .scout import daily
    from .discovery import replenish, pool

    try:
        research = daily(db)
    except Exception:
        research = {
            "day": now()[:10],
            "ideas": [],
            "evidence": {"records": []},
            "research_deferred": True,
        }
    try:
        from .cloudflare import drafting_budget

        with drafting_budget():
            result = {
                "status": replenish(db, research),
                "reviewed_text_drafts": len(pool(db)),
                "checked_at": now(),
            }
    except Exception as exc:
        result = {
            "status": "deferred",
            "reason": type(exc).__name__ + ": " + str(exc)[:180],
            "checked_at": now(),
        }
    (ROOT / "data" / "text-reserve-status.json").write_text(json.dumps(result))
    return result


def main():
    from .social import daily as social_daily
    from .trends import daily as trend_daily

    db = connect()
    try:
        print(json.dumps({"text_reserve": reserve(db)}), flush=True)
        try:
            social_daily(db)
        except Exception:
            pass  # Reference-account failures must not block topic-wide discovery.
        try:
            result = trend_daily(db)
        except Exception:
            result = {"status": "deferred", "reels_discovered": 0, "examples": []}
        print(
            json.dumps(
                {
                    "status": result.get("status"),
                    "reels_discovered": result.get("reels_discovered"),
                    "examples": len(result.get("examples", [])),
                    "limitations": result.get("limitations", []),
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
