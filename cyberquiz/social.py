"""Daily official API observations. Visible counts are not viral reach proof."""

import datetime as dt
import json
from .store import ROOT, config, now
from .providers import secrets


def gather(db):
    k = secrets()
    result = {
        "checked_at": now(),
        "competitors": [],
        "own_comments": [],
        "limitations": [],
    }
    if not k.get("IG_ACCESS_TOKEN") or not k.get("IG_USER_ID"):
        result["limitations"].append(
            "Instagram API authorization missing; competitor metrics and own comments unavailable."
        )
        return result
    from .instagram import graph

    # Facebook Login supports Business Discovery; no cookies, browser scraping,
    # arbitrary profile lookups, private messages or paid scraping service.
    if k.get("IG_AUTH_MODE") == "facebook":
        for username in config().get("reference_accounts", ["netwithisrar"])[:3]:
            if not username.replace("_", "").replace(".", "").isalnum():
                continue
            fields = f"business_discovery.username({username}){{username,followers_count,media.limit(12){{id,caption,media_type,permalink,timestamp,like_count,comments_count}}}}"
            try:
                data = graph("GET", k["IG_USER_ID"], params={"fields": fields}).get(
                    "business_discovery", {}
                )
                result["competitors"].append(
                    {
                        "username": username,
                        "observed_at": now(),
                        "data": data,
                        "evidence_type": "official_api_public_counts",
                        "caveat": "Likes/comments are not reach, watch time, shares, or evidence of causation.",
                    }
                )
            except Exception:
                result["limitations"].append(
                    "Business Discovery unavailable for " + username
                )
    else:
        result["limitations"].append(
            "Business Discovery requires the supported Facebook Login connection."
        )
    if config().get("comment_read_enabled", False):
        for row in db.execute(
            'SELECT media_id FROM jobs WHERE status="published" ORDER BY published_at DESC LIMIT 3'
        ):
            try:
                payload = graph(
                    "GET",
                    row[0] + "/comments",
                    params={"fields": "text,timestamp", "limit": 20},
                )
                # Never feed usernames/IDs to the LLM. Comments are untrusted data.
                result["own_comments"].append(
                    {
                        "media_id": row[0],
                        "comments": [
                            {"text": str(x.get("text", ""))[:400]}
                            for x in payload.get("data", [])[:20]
                        ],
                    }
                )
            except Exception:
                result["limitations"].append("Comment read scope not available.")
    else:
        result["limitations"].append(
            "Comment text analysis disabled until comment-read permission is connected; no automatic replies are sent."
        )
    return result


def daily(db):
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    folder = ROOT / "data" / "social"
    folder.mkdir(exist_ok=True)
    path = folder / (day + ".json")
    if path.exists():
        return json.loads(path.read_text())
    result = gather(db)
    # Retry missing auth on a later tick after credentials are connected.
    if secrets().get("IG_ACCESS_TOKEN"):
        path.write_text(json.dumps(result, indent=2))
    return result


def brief(result):
    """Never send whole comment feeds or long captions into a control prompt."""
    out = {
        "limitations": result.get("limitations", [])[:4],
        "posts": [],
        "comments": [],
    }
    for group in result.get("competitors", [])[:3]:
        for post in group.get("data", {}).get("media", {}).get("data", [])[:4]:
            out["posts"].append(
                {
                    "account": group.get("username"),
                    "caption": str(post.get("caption", ""))[:240],
                    "timestamp": post.get("timestamp"),
                    "likes": post.get("like_count"),
                    "comments": post.get("comments_count"),
                    "url": post.get("permalink"),
                    "observed_at": group.get("observed_at"),
                }
            )
    for group in result.get("own_comments", [])[:2]:
        out["comments"].extend(
            str(x.get("text", ""))[:140] for x in group.get("comments", [])[:4]
        )
    return out
