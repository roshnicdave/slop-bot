"""Project research into a bounded planning view; retain full evidence separately."""

import json


def text(value, limit):
    return str(value or "")[:limit]


def project(prompt):
    out = dict(prompt)
    out["user_preference"] = text(prompt.get("user_preference"), 700)
    out["sources"] = [
        {
            "source": text(p.get("source"), 60),
            "title": text(p.get("title"), 160),
            "url": p["url"],
            "summary": text(p.get("summary"), 300),
            "published": text(p.get("published"), 60),
        }
        for p in prompt.get("sources", [])[:8]
        if isinstance(p, dict)
        and isinstance(p.get("url"), str)
        and len(p["url"]) <= 2048
    ]
    out["recent"] = [
        {"family": text(p.get("family"), 80), "question": text(p.get("question"), 140)}
        for p in prompt.get("recent", [])[:12]
    ]
    out["supported_scenes"] = [
        {k: text(p.get(k), 160) for k in ("key", "family", "question", "clue")}
        for p in prompt.get("supported_scenes", [])[:20]
    ]
    refs = []
    for ref in prompt.get("inspected_reference_examples", [])[:2]:
        refs.append(
            {
                "observations": [text(x, 180) for x in ref.get("observations", [])[:3]],
                "design_hypotheses": [
                    text(x, 180) for x in ref.get("design_hypotheses", [])[:2]
                ],
            }
        )
    out["inspected_reference_examples"] = refs
    social = prompt.get("social_evidence", {})
    trend = social.get("topic_wide_discovery", {})
    examples = []
    for item in trend.get("examples", [])[:3]:
        inspection = item.get("inspection") or {}
        findings = inspection.get("findings") or {}
        examples.append(
            {
                "url": text(item.get("url"), 500),
                "tag": text(item.get("tag"), 40),
                "likes": item.get("likes"),
                "comments": item.get("comments"),
                "evidence": text(item.get("evidence"), 60),
                "caption_excerpt": text(item.get("caption_excerpt"), 180),
                "findings": {
                    k: text(findings.get(k), 150)
                    for k in (
                        "format",
                        "visible_hook",
                        "diagram_style",
                        "adaptable_hypothesis",
                        "limitations",
                    )
                },
                "scope": text(inspection.get("scope"), 200),
            }
        )
    out["social_evidence"] = {
        "limitations": [text(x, 160) for x in social.get("limitations", [])[:3]],
        "posts": [
            {k: text(p.get(k), 180) for k in ("caption", "url", "timestamp")}
            for p in social.get("posts", [])[:4]
        ],
        "topic_wide_discovery": {
            "day": trend.get("day"),
            "reels_discovered": trend.get("reels_discovered"),
            "examples": examples,
            "scope": text(trend.get("scope"), 240),
        },
    }
    out["own_metrics"] = {
        text(k, 60): {
            field: value.get(field) for field in ("posts", "median_shares_per_1000")
        }
        for k, value in list(prompt.get("own_metrics", {}).items())[:4]
    }
    return out


def messages(system, prompt):
    """Fit whole structured sections, never truncate serialized JSON or source URLs."""
    view = project(prompt)

    def pack():
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(view, ensure_ascii=False, separators=(",", ":")),
            },
        ]

    # Leave 2 KB headroom under the provider's 18 KB input ceiling.
    while len(json.dumps(pack(), ensure_ascii=False).encode()) + 512 > 16000:
        removable = [
            view["inspected_reference_examples"],
            view["social_evidence"]["posts"],
            view["social_evidence"]["topic_wide_discovery"]["examples"],
            view["supported_scenes"],
            view["recent"],
        ]
        target = next((items for items in removable if items), None)
        if target is not None:
            target.pop()
        elif len(view["sources"]) > 1:
            view["sources"].pop()
        else:
            raise ValueError("Minimal research context exceeds planning budget")
    return pack()
