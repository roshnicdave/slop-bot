"""Short, relevant metadata; no unrelated copied viral-caption boilerplate."""


def caption(p):
    cert = p.get("certification")
    follow = (
        "Follow for visual " + cert + " practice."
        if cert in ("CCNA", "Network+", "Security+")
        and p.get("content_scope") != "industry"
        else "Follow for practical networking and security."
    )
    practice = (
        "\n\n" + cert + " practice: " + p.get("exam_skill", "")
        if cert and p.get("exam_skill") and p.get("content_scope") != "industry"
        else ""
    )
    return (
        p["question"].replace("\n", " ")
        + "\n\n"
        + follow
        + "\nComment your answer."
        + "\n\n"
        + p["explanation"]
        + " "
        + p["fix"]
        + practice
        + "\n\nAssumptions: "
        + p["clue"]
        + "\nSource: "
        + p["source_url"]
        + "\n\n"
        + hashtags(p)
    )


def hashtags(p):
    text = " ".join(
        str(p.get(k, "")) for k in ("family", "topic", "core_claim", "question")
    ).lower()
    tags = ["#CyberSecurity", "#Networking"]
    cert = p.get("certification")
    exam_tags = p.get("content_scope") != "industry"
    if exam_tags and cert in ("CCNA", "Network+", "Security+"):
        tags.insert(
            0,
            {"CCNA": "#CCNA", "Network+": "#NetworkPlus", "Security+": "#SecurityPlus"}[
                cert
            ],
        )
    if exam_tags and any(
        word in text
        for word in (
            "vlan",
            "route",
            "routing",
            "subnet",
            "dns",
            "arp",
            "dhcp",
            "switch",
            "acl",
            "nat ",
        )
    ):
        tags.append("#CCNA")
    elif exam_tags and any(
        word in text for word in ("phishing", "tls", "firewall", "certificate")
    ):
        tags.append("#SecurityPlus")
    for keywords, tag in [
        ("dns", "#DNS"),
        ("vlan", "#VLAN"),
        ("route routing prefix", "#Routing"),
        ("url phishing login", "#PhishingAwareness"),
        ("tls certificate", "#TLS"),
        ("acl firewall", "#NetworkSecurity"),
        ("cache caching", "#Caching"),
        ("model inference", "#AISecurity"),
    ]:
        if any(word in text for word in keywords.split()):
            tags.append(tag)
    tags.extend(["#TechQuiz", "#NetworkEngineer"])
    return " ".join(list(dict.fromkeys(tags))[:5])
