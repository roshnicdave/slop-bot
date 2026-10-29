"""Executable micro-labs. Questions use evidence viewers can reason from."""

import copy
import ipaddress
from urllib.parse import urlparse

RFC = "https://www.rfc-editor.org/rfc/"


def scene(key, title, clue, lines, answer, others, why, fix, source, model):
    return dict(
        key=key,
        family="lab-" + key,
        question=title,
        clue=clue,
        diagram={"kind": "config", "lines": lines, "links_up": True, "routing": True},
        answer=answer,
        distractors=others,
        explanation=why,
        fix=fix,
        fix_label="What the evidence tells us",
        fix_diagram={},
        source_url=source,
        source_label="Protocol micro-lab",
        narration_question=title.replace("\n", " "),
        narration_answer=why + " " + fix,
        model=model,
    )


def bank():
    return [
        scene(
            "longest-prefix",
            "Routes overlap.\nWhich next hop wins?",
            "Routing table only. All next hops reachable.",
            [
                "Destination: 10.1.2.9",
                "10.0.0.0/8      -> Router A",
                "10.1.2.0/24     -> Router B",
                "0.0.0.0/0      -> Router C",
            ],
            "Router B",
            ["Router A", "Router C", "Equal-cost split"],
            "The /24 is the longest matching prefix. A shorter matching route does not win.",
            "Compare prefix length before route metrics.",
            RFC + "rfc1812.txt",
            {
                "kind": "route",
                "destination": "10.1.2.9",
                "routes": [
                    ["10.0.0.0/8", "Router A"],
                    ["10.1.2.0/24", "Router B"],
                    ["0.0.0.0/0", "Router C"],
                ],
                "expected": "Router B",
            },
        ),
        scene(
            "acl-order",
            "The permit exists.\nWhy is HTTPS blocked?",
            "First-match IPv4 ACL. Applied inbound. TCP 443.",
            [
                "Source: 10.1.2.9 -> TCP 443",
                "10 deny   10.0.0.0/8",
                "20 permit 10.1.2.0/24",
                "First match wins",
            ],
            "The deny matches first",
            [
                "The permit is more specific",
                "DNS must use TCP 443",
                "The cable is reversed",
            ],
            "The broad deny matches first. This ACL stops there, even though a later permit is more specific.",
            "Put the narrow permit before the broad deny.",
            RFC + "rfc8519.txt",
            {
                "kind": "acl",
                "source": "10.1.2.9",
                "rules": [["deny", "10.0.0.0/8"], ["permit", "10.1.2.0/24"]],
                "fixed_rules": [["permit", "10.1.2.0/24"], ["deny", "10.0.0.0/8"]],
            },
        ),
        scene(
            "trunk-allow",
            "VLAN exists at both ends.\nWhy does it stop here?",
            "Access ports correct. Single trunk. No routing.",
            [
                "Traffic: VLAN 20",
                "Switch A trunk allows: 10,20",
                "Switch B trunk allows: 10",
                "Physical link: UP",
            ],
            "VLAN 20 excluded on B",
            [
                "VLAN numbers must differ",
                "A router is always required",
                "VLAN 10 must be deleted",
            ],
            "Switch B does not allow VLAN twenty on this trunk. A green link does not prove VLAN delivery.",
            "Allow VLAN twenty on both ends of the trunk.",
            "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/vlan/b_1712_vlan_9300_cg/configuring_vlan_trunks.html",
            {
                "kind": "trunk",
                "vlan": 20,
                "allowed_a": [10, 20],
                "allowed_b": [10],
                "fixed_b": [10, 20],
            },
        ),
        scene(
            "pool-exhausted",
            "DHCP is running.\nWhy no new lease?",
            "One scope. No exclusions. Every address shown.",
            [
                "Pool: 192.168.1.10 - .11",
                "192.168.1.10: active lease",
                "192.168.1.11: active lease",
                "New client: DHCP DISCOVER",
            ],
            "The address pool is full",
            [
                "The lease time is too short",
                "DNS has no A record",
                "The gateway needs rebooting",
            ],
            "Both pool addresses already have active leases. Running DHCP is not the same as having a free address.",
            "Expand the valid scope or reclaim an expired lease.",
            RFC + "rfc2131.txt",
            {
                "kind": "pool",
                "pool": ["192.168.1.10", "192.168.1.11"],
                "leased": ["192.168.1.10", "192.168.1.11"],
            },
        ),
        scene(
            "dns-cache",
            "The record changed.\nWhy the old address?",
            "Resolver cache is valid. No hosts-file override.",
            [
                "Authoritative A: 203.0.113.20",
                "Cached A:        203.0.113.10",
                "Cache TTL remaining: 240 sec",
                "Client uses this resolver",
            ],
            "The cached TTL remains",
            [
                "The subnet mask changed",
                "DNS must use a router IP",
                "An A record stores a MAC",
            ],
            "The resolver still has a valid cached answer. Changing the authoritative record does not instantly remove every cache.",
            "Wait for expiry or clear the cache you control.",
            RFC + "rfc1034.txt",
            {
                "kind": "cache",
                "authoritative": "203.0.113.20",
                "cached": "203.0.113.10",
                "ttl": 240,
            },
        ),
        scene(
            "tls-name",
            "HTTPS reaches the server.\nWhy the certificate error?",
            "Certificate trusted, unexpired. No other SAN names.",
            [
                "Requested: api.example.com",
                "Certificate SAN: www.example.com",
                "TCP 443: connected",
                "Trust chain: valid",
            ],
            "The hostname does not match",
            [
                "The certificate is expired",
                "TCP 443 cannot carry TLS",
                "DNS must return the SAN",
            ],
            "The trusted certificate does not cover the requested hostname. Encryption alone does not establish the right server identity.",
            "Install a certificate covering the actual hostname.",
            RFC + "rfc9525.txt",
            {"kind": "tls", "host": "api.example.com", "sans": ["www.example.com"]},
        ),
        scene(
            "url-host",
            "Which site receives\nthis login request?",
            "Read the actual URL host. No redirects.",
            [
                "https://login.example.com.evil.test/",
                "Target host is between // and /",
                "Dots are part of the hostname",
            ],
            "login.example.com.evil.test",
            ["login.example.com", "example.com", "The browser chooses"],
            "The host is login dot example dot com dot evil dot test. A familiar name at the start does not make it the real site.",
            "Check the complete hostname before signing in.",
            RFC + "rfc3986.txt",
            {
                "kind": "url",
                "url": "https://login.example.com.evil.test/",
                "expected": "login.example.com.evil.test",
            },
        ),
        scene(
            "broadcast-host",
            "One PC has this IP.\nWhy is it invalid here?",
            "Ordinary IPv4 /24 LAN. No special host routes.",
            [
                "PC: 192.168.10.255/24",
                "Gateway: 192.168.10.1",
                "Network: 192.168.10.0/24",
            ],
            "It is the subnet broadcast",
            [
                "It is a private address",
                "The gateway is off-subnet",
                "A /24 has no host addresses",
            ],
            "Dot two fifty five is the broadcast address of this slash twenty four. It is not a usable host address on this LAN.",
            "Assign a unique usable address such as dot twenty five.",
            RFC + "rfc1122.txt",
            {
                "kind": "broadcast",
                "ip": "192.168.10.255/24",
                "fixed": "192.168.10.25/24",
            },
        ),
        scene(
            "mtu-df",
            "Small pings work.\nWhy do large ones fail?",
            "IPv4. DF set. ICMP fragmentation-needed reaches sender.",
            [
                "IP packet: 1500 bytes, DF = 1",
                "Path MTU: 1400 bytes",
                "Small IP packets: delivered",
                "No other packet loss",
            ],
            "Packet exceeds path MTU",
            [
                "DNS records are too long",
                "The TCP port is wrong",
                "The VLAN ID is too large",
            ],
            "The packet is larger than the path MTU, and do not fragment is set. The router cannot forward it unchanged.",
            "Use path MTU discovery to send smaller packets.",
            RFC + "rfc1191.txt",
            {
                "kind": "mtu",
                "packet": 1500,
                "mtu": 1400,
                "df": True,
                "fixed_packet": 1400,
            },
        ),
        scene(
            "duplicate-ip",
            "Both links are green.\nWhy does ARP keep changing?",
            "Same VLAN. Two distinct devices. No proxy ARP.",
            [
                "PC A: 192.168.1.20, MAC ...:AA",
                "PC B: 192.168.1.20, MAC ...:BB",
                "ARP for .20 alternates AA / BB",
            ],
            "Two hosts use the same IP",
            [
                "Two hosts share a gateway",
                "Two hosts share a subnet",
                "The DNS TTL is too low",
            ],
            "Two different devices claim the same IP address. ARP can alternate between their hardware addresses.",
            "Assign each device a unique IP address.",
            RFC + "rfc5227.txt",
            {
                "kind": "duplicate",
                "a": "192.168.1.20",
                "b": "192.168.1.20",
                "fixed_b": "192.168.1.21",
            },
        ),
    ]


def validate(p):
    m = p["model"]
    k = m["kind"]
    if k == "route":
        ip = ipaddress.ip_address(m["destination"])
        matches = [
            (ipaddress.ip_network(n).prefixlen, hop)
            for n, hop in m["routes"]
            if ip in ipaddress.ip_network(n)
        ]
        if (
            not matches
            or max(matches)[1] != m["expected"]
            or p["answer"] != m["expected"]
        ):
            raise ValueError("Route answer not supported")
    elif k == "acl":

        def first(rules):
            return next(
                (
                    action
                    for action, net in rules
                    if ipaddress.ip_address(m["source"]) in ipaddress.ip_network(net)
                ),
                "deny",
            )

        if first(m["rules"]) != "deny" or first(m["fixed_rules"]) != "permit":
            raise ValueError("ACL is not blocked and repaired")
    elif k == "trunk":
        v = m["vlan"]
        if not (v in m["allowed_a"] and v not in m["allowed_b"] and v in m["fixed_b"]):
            raise ValueError("Trunk claim invalid")
    elif k == "pool":
        if set(m["pool"]) - set(m["leased"]):
            raise ValueError("Pool has a free address")
    elif k == "cache":
        if not (m["ttl"] > 0 and m["authoritative"] != m["cached"]):
            raise ValueError("Cache example invalid")
    elif k == "tls":
        if m["host"] in m["sans"] or any("*" in n for n in m["sans"]):
            raise ValueError("Certificate may cover host")
    elif k == "url":
        if urlparse(m["url"]).hostname != m["expected"] or p["answer"] != m["expected"]:
            raise ValueError("URL answer incorrect")
    elif k == "broadcast":
        ip = ipaddress.ip_interface(m["ip"])
        fixed = ipaddress.ip_interface(m["fixed"])
        if not (
            ip.ip == ip.network.broadcast_address
            and fixed.network == ip.network
            and fixed.ip in fixed.network.hosts()
        ):
            raise ValueError("Broadcast example invalid")
    elif k == "mtu":
        if not (m["df"] and m["packet"] > m["mtu"] and m["fixed_packet"] <= m["mtu"]):
            raise ValueError("MTU example invalid")
    elif k == "duplicate":
        if not (m["a"] == m["b"] and m["fixed_b"] != m["a"]):
            raise ValueError("Duplicate IP example invalid")
    else:
        raise ValueError("Unknown micro-lab")
    # Bind model and on-screen evidence to reviewed generators. Dynamic values
    # must use a dedicated compiler; LLM edits may not silently alter evidence.
    reference = next((x for x in bank() if x["key"] == p["key"]), None)
    if reference and "seed" in m:
        reference = variant(reference, m["seed"])
    for field in (
        "model",
        "diagram",
        "answer",
        "distractors",
        "explanation",
        "fix",
        "source_url",
    ):
        if not reference or p[field] != reference[field]:
            raise ValueError("Unreviewed micro-lab mutation")
    return p


def variant(scene, seed):
    """Fresh data with the same learning objective; not a new concept claim."""
    if not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("Invalid variant seed")
    import random

    p = copy.deepcopy(scene)
    m = p["model"]
    r = random.Random(seed)
    octet = r.randint(1, 240)
    k = m["kind"]
    if k == "route":
        prefix = r.choice([24, 25, 26])
        host = r.randint(5, 50)
        target = f"10.{octet}.2.{host}"
        hops = ["Router A", "Router B", "Router C"]
        r.shuffle(hops)
        m.update(
            destination=target,
            routes=[
                ["10.0.0.0/8", hops[0]],
                [f"10.{octet}.2.0/{prefix}", hops[1]],
                ["0.0.0.0/0", hops[2]],
            ],
            expected=hops[1],
        )
        p["answer"] = hops[1]
        p["distractors"] = [hops[0], hops[2], "Equal-cost split"]
        p["diagram"]["lines"] = ["Destination: " + target] + [
            n + " -> " + h for n, h in m["routes"]
        ]
        p["explanation"] = (
            f"The slash {prefix} route is the longest matching prefix. A shorter matching route does not win."
        )
    elif k == "acl":
        net = f"10.{octet}.2.0/24"
        source = f"10.{octet}.2.9"
        m.update(
            source=source,
            rules=[["deny", "10.0.0.0/8"], ["permit", net]],
            fixed_rules=[["permit", net], ["deny", "10.0.0.0/8"]],
        )
        p["diagram"]["lines"] = [
            "Source: " + source + " -> TCP 443",
            "10 deny   10.0.0.0/8",
            "20 permit " + net,
            "First match wins",
        ]
    elif k == "trunk":
        vlan = r.choice([20, 30, 40, 50, 60, 70, 80, 90])
        m.update(vlan=vlan, allowed_a=[10, vlan], allowed_b=[10], fixed_b=[10, vlan])
        p["answer"] = f"VLAN {vlan} excluded on B"
        p["diagram"]["lines"] = [
            f"Traffic: VLAN {vlan}",
            f"Switch A trunk allows: 10,{vlan}",
            "Switch B trunk allows: 10",
            "Physical link: UP",
        ]
        p["explanation"] = (
            f"Switch B does not allow VLAN {vlan} on this trunk. A green link does not prove VLAN delivery."
        )
        p["fix"] = f"Allow VLAN {vlan} on both ends of the trunk."
    elif k == "mtu":
        mtu = r.choice([1280, 1360, 1400, 1450])
        packet = mtu + r.choice([40, 80, 100])
        m.update(packet=packet, mtu=mtu, fixed_packet=mtu)
        p["diagram"]["lines"] = [
            f"IP packet: {packet} bytes, DF = 1",
            f"Path MTU: {mtu} bytes",
            "Small IP packets: delivered",
            "No other packet loss",
        ]
    elif k == "broadcast":
        prefix = r.choice([24, 25, 26, 27])
        net = ipaddress.ip_network(f"192.168.{octet}.0/{prefix}")
        m.update(
            ip=str(net.broadcast_address) + f"/{prefix}",
            fixed=str(net.network_address + 5) + f"/{prefix}",
        )
        p["diagram"]["lines"] = [
            "PC: " + m["ip"],
            f"Gateway: 192.168.{octet}.1",
            "Network: " + str(net),
        ]
        p["explanation"] = (
            "The assigned IP is the broadcast address of the shown subnet. It is not a usable host address on this LAN."
        )
        p["fix"] = "Assign a unique usable host address inside this subnet."
    m["seed"] = seed
    # Rebuild speech from checked explanation/fix in the plan compiler.
    return p
