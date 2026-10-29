"""Daily discovery process, independent of the publishing worker and chat."""

import json
from .store import connect


def main():
    from .social import daily as social_daily
    from .trends import daily as trend_daily

    db = connect()
    try:
        try:
            social_daily(db)
        except Exception:
            pass  # Reference-account failures must not block topic-wide discovery.
        result = trend_daily(db)
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
