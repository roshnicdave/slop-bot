"""Visual troubleshooting models with explicit assumptions and checked answers."""

import copy
import ipaddress
import random

VLAN_SOURCE = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/vlan/b_1712_vlan_9300_cg/configuring_vlans.html"
RFC = "https://www.rfc-editor.org/rfc/rfc1122.txt"


def vlan(a=10, b=20):
    return {
        "key": f"vlan-{a}-{b}",
        "family": "visual-vlan",
        "question": "Links are up.\nWhy does ping fail?",
        "clue": "Access ports shown. Layer 2 switch only. No router.",
        "diagram": {
            "kind": "switch",
            "left": {"name": "PC 1", "ip": "192.168.1.10/24", "vlan": a},
            "right": {"name": "PC 2", "ip": "192.168.1.20/24", "vlan": b},
            "links_up": True,
            "routing": False,
        },
        "answer": "Different VLANs",
        "distractors": ["Wrong cable", "Switch is offline", "Duplicate IP address"],
        "explanation": "Different VLANs split this network at Layer 2. There is no router between them.",
        "fix": "Put both access ports in the same VLAN.",
        "fix_label": "Same VLAN. Ping works.",
        "fix_diagram": {"right_vlan": a},
        "source_url": VLAN_SOURCE,
        "source_label": "Cisco: VLAN configuration",
        "narration_question": "The links are up, but this ping fails. What is wrong?",
        "narration_answer": "The ports are in different VLANs. This Layer two switch cannot route between them. Put both ports in the same VLAN to fix this example.",
    }


def subnet(a=10, b=20):
    return {
        "key": f"subnet-{a}-{b}",
        "family": "visual-subnet",
        "question": "Same VLAN.\nWhy does ping fail?",
        "clue": "Both links up. Same VLAN. No default gateway configured.",
        "diagram": {
            "kind": "switch",
            "left": {"name": "PC 1", "ip": f"192.168.{a}.10/24", "vlan": 10},
            "right": {"name": "PC 2", "ip": f"192.168.{b}.20/24", "vlan": 10},
            "links_up": True,
            "routing": False,
        },
        "answer": "Different IP subnets",
        "distractors": [
            "Different VLANs",
            "The switch is offline",
            "Duplicate IP address",
        ],
        "explanation": "The /24 networks differ. With no gateway configured, these hosts have no route to each other.",
        "fix": "For this single LAN, put both PCs in the same /24 subnet.",
        "fix_label": "Same subnet. Ping works.",
        "fix_diagram": {"right_ip": f"192.168.{a}.20/24"},
        "source_url": RFC,
        "source_label": "RFC 1122: local / remote decision",
        "narration_question": "Same switch. Same VLAN. But the ping fails. Look at the IP addresses.",
        "narration_answer": "The PCs are in different subnets, and neither has a gateway. Put them in the same subnet for this single LAN, and the ping works.",
    }


def gateway():
    return {
        "key": "gateway-offlink",
        "family": "visual-gateway",
        "question": "Local ping works.\nWhy is the internet down?",
        "clue": "Router LAN: 192.168.10.1/24. WAN is working. No alternate routes.",
        "diagram": {
            "kind": "router",
            "left": {
                "name": "PC 1",
                "ip": "192.168.10.25/24",
                "gateway": "192.168.20.1",
            },
            "right": {"name": "Internet", "ip": "Router: 192.168.10.1/24"},
            "links_up": True,
            "routing": True,
        },
        "answer": "Gateway is off-subnet",
        "distractors": [
            "The cable is unplugged",
            "The LAN switch is off",
            "Duplicate IP address",
        ],
        "explanation": "The configured gateway is outside the PC's /24. It cannot reach that next hop on this LAN.",
        "fix": "Set the default gateway to 192.168.10.1.",
        "fix_label": "Reachable gateway. Traffic flows.",
        "fix_diagram": {"left_gateway": "192.168.10.1"},
        "source_url": RFC,
        "source_label": "RFC 1122: routing / gateways",
        "narration_question": "This PC can ping its local network, but not the internet. Which setting is wrong?",
        "narration_answer": "The default gateway is outside the PC's subnet. Set it to the router's LAN address, nineteen two, one sixty eight, ten, one.",
    }


def dns():
    return {
        "key": "dns-unreachable",
        "family": "visual-dns",
        "question": "IP works.\nWebsite name fails. Why?",
        "clue": "Same server: IP connection succeeds. DNS lookup times out. Resolver is unreachable.",
        "diagram": {
            "kind": "dns",
            "left": {"name": "PC 1", "ip": "IP connection: OK"},
            "right": {"name": "DNS resolver", "ip": "DNS query: TIMEOUT"},
            "links_up": True,
            "routing": True,
        },
        "answer": "DNS resolver unreachable",
        "distractors": [
            "The Ethernet link is down",
            "The server is offline",
            "Duplicate IP address",
        ],
        "explanation": "The IP path works. The failing step is the DNS lookup, which needs a reachable resolver.",
        "fix": "Restore access to a working, authorized DNS resolver.",
        "fix_label": "DNS replies. Name resolves.",
        "fix_diagram": {"dns_reachable": True},
        "source_url": "https://www.rfc-editor.org/rfc/rfc1034.txt",
        "source_label": "RFC 1034: name resolution",
        "narration_question": "The same server works by IP address, but its website name fails. What should you check?",
        "narration_answer": "DNS. The IP path works, but the configured resolver is unreachable. Restore access to a working resolver so the name can resolve.",
    }


def asymmetric_mask():
    p = subnet(1, 1)
    p.update(
        key="asymmetric-mask",
        family="visual-mask",
        question="ARP works.\nWhy no ping reply?",
        clue="Both links up. Same VLAN. No default gateways.",
        answer="Mismatched subnet masks",
        distractors=[
            "Different VLANs",
            "The cable is unplugged",
            "Duplicate IP address",
        ],
        explanation="PC 1 sees PC 2 as local. PC 2 sees PC 1 as remote, but has no gateway for the reply.",
        fix="Use /24 on both PCs for this LAN.",
        fix_label="Both /24. Replies work.",
        fix_diagram={"right_ip": "192.168.1.130/24"},
        narration_question="ARP works, but this ping gets no reply. Look closely at both subnet masks.",
        narration_answer="The masks do not match. PC two sees PC one as remote, but has no gateway for the reply. Use slash twenty four on both PCs for this LAN.",
    )
    p["diagram"]["left"]["ip"] = "192.168.1.10/24"
    p["diagram"]["right"]["ip"] = "192.168.1.130/25"
    return p


def wrong_gateway():
    p = gateway()
    p.update(
        key="gateway-wrong-host",
        family="visual-gateway-host",
        question="Gateway is on-subnet.\nWhy no internet?",
        clue="Router: 192.168.10.1/24. WAN works. .99 is a host, not a router.",
        answer="Gateway points to a host",
        distractors=[
            "Gateway is off-subnet",
            "The cable is unplugged",
            "Duplicate IP address",
        ],
        explanation="A gateway must forward traffic. Being in the same subnet is not enough: .99 is not the router.",
        narration_question="The gateway is in the right subnet, but the internet still fails. What is wrong?",
        narration_answer="The gateway points to a host that does not route. Set it to the router address, ending in dot one. Same subnet alone is not enough.",
    )
    p["diagram"]["left"]["gateway"] = "192.168.10.99"
    return p


def bank():
    # New number combinations are NOT counted as new concepts. The scout sees
    # four distinct mechanisms, and the selector enforces a concept cooldown.
    from .labs import bank as labs

    return [
        vlan(),
        subnet(),
        gateway(),
        asymmetric_mask(),
        wrong_gateway(),
        *labs(),
    ]


def validate(scene):
    d = scene["diagram"]
    left = d.get("left", {})
    right = d.get("right", {})
    family = scene["family"]
    if len(set([scene["answer"], *scene["distractors"]])) != 4:
        raise ValueError("Need four distinct choices")
    if len(scene["question"].replace("\n", " ")) > 90:
        raise ValueError("Hook too long")
    if not d["links_up"]:
        raise ValueError("Assumptions must match displayed link lights")
    if family == "source-grounded":
        from .discovery import validate as source_validate

        return source_validate(scene)
    if family.startswith("lab-"):
        from .labs import validate as lab_validate

        return lab_validate(scene)
    if family == "visual-vlan":
        l = ipaddress.ip_interface(left["ip"])
        r = ipaddress.ip_interface(right["ip"])
        if not (
            left["vlan"] != right["vlan"]
            and l.network == r.network
            and l.ip != r.ip
            and not d["routing"]
        ):
            raise ValueError("VLAN scenario is ambiguous")
        if scene["fix_diagram"]["right_vlan"] != left["vlan"]:
            raise ValueError("VLAN fix does not restore Layer 2 path")
    elif family == "visual-subnet":
        l = ipaddress.ip_interface(left["ip"])
        r = ipaddress.ip_interface(right["ip"])
        fixed = ipaddress.ip_interface(scene["fix_diagram"]["right_ip"])
        if not (
            left["vlan"] == right["vlan"]
            and l.network != r.network
            and not d["routing"]
            and fixed.network == l.network
        ):
            raise ValueError("Subnet scenario invalid")
    elif family == "visual-mask":
        l = ipaddress.ip_interface(left["ip"])
        r = ipaddress.ip_interface(right["ip"])
        fixed = ipaddress.ip_interface(scene["fix_diagram"]["right_ip"])
        if not (
            r.ip in l.network and l.ip not in r.network and l.network == fixed.network
        ):
            raise ValueError("Mask asymmetry not demonstrated or fixed")
    elif family == "visual-gateway-host":
        l = ipaddress.ip_interface(left["ip"])
        if (
            ipaddress.ip_address(left["gateway"]) not in l.network
            or left["gateway"] == scene["fix_diagram"]["left_gateway"]
        ):
            raise ValueError("Wrong-host gateway example invalid")
    elif family == "visual-gateway":
        l = ipaddress.ip_interface(left["ip"])
        if ipaddress.ip_address(left["gateway"]) in l.network:
            raise ValueError("Bad gateway is actually on-link")
        if ipaddress.ip_address(scene["fix_diagram"]["left_gateway"]) not in l.network:
            raise ValueError("Fix is still off-link")
    elif family == "visual-dns":
        if not scene["fix_diagram"].get("dns_reachable"):
            raise ValueError("DNS fix missing")
    else:
        raise ValueError(
            "Unsupported visual scenario; needs an executable validator before automatic use"
        )
    return scene


def plan(scene, creative, job):
    validate(scene)
    p = copy.deepcopy(scene)
    options = [p["answer"], *p["distractors"]]
    random.Random(job).shuffle(options)
    from .store import config

    p.update(
        account=config()["account"],
        id=job,
        visual=True,
        format="visual-troubleshooting",
        options=options,
        correct=options.index(p["answer"]),
        decision_seconds=5,
    )
    from .speech import speak

    p["intro"] = speak(p["narration_question"])
    p["reveal_voice"] = "ABCD"[p["correct"]] + ". " + speak(p["explanation"])
    p["fix_voice"] = speak(p["fix"])
    p["outro"] = p["reveal_voice"] + " " + p["fix_voice"]
    p["voice_version"] = 2
    if (
        not p["intro"].isascii()
        or not p["outro"].isascii()
        or len(p["intro"]) + len(p["outro"]) > 600
    ):
        raise ValueError("Narration exceeds ASCII character budget")
    p["caption"] = (
        p["question"].replace("\n", " ")
        + "\n\nPick A, B, C or D before the reveal.\n\n"
        "Explanation: " + p["explanation"] + "\n" + p["fix"] + "\n\n"
        "Assumptions: " + p["clue"] + "\nSource: " + p["source_url"] + "\n\n"
        "Follow for visual networking challenges.\n#networking #cybersecurity #networkengineer"
    )
    p["creative"] = creative
    return p
