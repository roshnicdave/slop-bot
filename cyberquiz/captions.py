"""Short, relevant metadata; no unrelated copied viral-caption boilerplate."""


def hashtags(p):
    text = " ".join(
        str(p.get(k, "")) for k in ("family", "topic", "core_claim", "question")
    ).lower()
    tags = ["#CyberSecurity", "#Networking"]
    for keywords, tag in [
        ("dns", "#DNS"),
        ("vlan", "#VLAN"),
        ("route routing prefix", "#Routing"),
        ("url phishing login", "#PhishingAwareness"),
        ("tls certificate", "#TLS"),
        ("acl firewall", "#NetworkSecurity"),
        ("cache model inference", "#AISecurity"),
    ]:
        if any(word in text for word in keywords.split()):
            tags.append(tag)
    tags.extend(["#TechQuiz", "#NetworkEngineer"])
    return " ".join(list(dict.fromkeys(tags))[:5])
