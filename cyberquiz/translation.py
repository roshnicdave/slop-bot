"""Opt-in Telugu audio-mix translation with an independent review gate.

Returns None on any failure so production falls back to English-only narration;
Telugu lines never bypass the gate and never block a verified Reel.
"""

import re

from . import cloudflare


PROTECTED_TERMS = (
    "TTL", "MTU", "DHCP", "HTTPS", "HTTP", "DNS", "ARP", "IP", "IPv4", "IPv6",
    "TCP", "UDP", "ICMP", "VLAN", "NAT", "PAT", "SSH", "TLS", "SSL", "BGP",
    "OSPF", "EIGRP", "RIP", "MAC", "LAN", "WAN", "VPN", "ACL", "QoS", "STP",
    "VTP", "SNMP", "SMTP", "POP3", "IMAP", "FTP", "SFTP", "LDAP", "RADIUS",
    "TACACS", "AAA", "WPA", "WPA2", "WPA3", "SSID", "AP", "URL", "CIDR",
    "Layer 2", "Layer 3", "Layer 4", "Layer 7",
)


def _has_protected_terms(english):
    return [t for t in PROTECTED_TERMS if re.search(r"\b" + re.escape(t) + r"\b", english)]


def translate(db, job, label, english):
    required = _has_protected_terms(english)
    result = cloudflare.llm(
        db,
        job + ":telugu_translate:" + label,
        [
            {
                "role": "system",
                "content": (
                    "Translate the English narration line to natural spoken Telugu "
                    "for an Indian cybersecurity learner audience. Keep every listed "
                    "technical term unchanged (English script) so the ElevenLabs voice "
                    "pronounces them correctly. Keep IPv4 addresses, port numbers and "
                    "measurements unchanged. Do not add new facts, questions, options "
                    "or hashtags. One short line, suitable to speak in under five "
                    "seconds. Return JSON {telugu: '<string>'}."
                ),
            },
            {
                "role": "user",
                "content": (
                    '{"english": ' + _json_string(english)
                    + ', "preserve_terms": ' + _json_array(required) + "}"
                ),
            },
        ],
        kind="editorial",
        max_tokens=200,
        model=cloudflare.EDITOR,
    )
    telugu = result.get("telugu") if isinstance(result, dict) else None
    if not isinstance(telugu, str):
        return None
    telugu = " ".join(telugu.split())
    if not telugu or len(telugu) > 350:
        return None
    for term in required:
        if term not in telugu:
            return None
    return telugu


def review(db, job, label, english, telugu):
    required = _has_protected_terms(english)
    result = cloudflare.llm(
        db,
        job + ":telugu_review:" + label,
        [
            {
                "role": "system",
                "content": (
                    "Independent review of a Telugu translation for an audio mix. "
                    "Check three things: (1) meaning preserved without adding facts, "
                    "(2) every listed technical term kept unchanged, (3) tone is "
                    "natural spoken Telugu, not literal word-for-word. Return JSON "
                    "{passed: bool, reason: '<short>'}."
                ),
            },
            {
                "role": "user",
                "content": (
                    '{"english": ' + _json_string(english)
                    + ', "telugu": ' + _json_string(telugu)
                    + ', "preserve_terms": ' + _json_array(required) + "}"
                ),
            },
        ],
        kind="editorial",
        max_tokens=120,
        model=cloudflare.REVIEW,
    )
    return bool(isinstance(result, dict) and result.get("passed") is True)


def prepare(db, job, label, english):
    """Translate and independently review; return Telugu string or None on any failure."""
    if not english or not isinstance(english, str):
        return None
    try:
        telugu = translate(db, job, label, english)
    except (cloudflare.CloudflareRequestError, cloudflare.FreeQuotaDeferred,
            cloudflare.ModelOutputError, ValueError):
        return None
    if not telugu:
        return None
    try:
        passed = review(db, job, label, english, telugu)
    except (cloudflare.CloudflareRequestError, cloudflare.FreeQuotaDeferred,
            cloudflare.ModelOutputError, ValueError):
        return None
    return telugu if passed else None


def _json_string(value):
    import json
    return json.dumps(value, ensure_ascii=False)


def _json_array(values):
    import json
    return json.dumps(list(values), ensure_ascii=False)
