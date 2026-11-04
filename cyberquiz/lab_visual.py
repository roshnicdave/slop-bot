"""Pictorial micro-labs derived from the same model used by the fact checks."""

import ipaddress
from .visual import text, INK, GREEN

VERSION = 2

SUPPORTED = frozenset(
    (
        "route",
        "acl",
        "trunk",
        "pool",
        "cache",
        "tls",
        "url",
        "broadcast",
        "mtu",
        "duplicate",
    )
)


def validate(p):
    if p["diagram"]["kind"] not in ("switch", "router", "dns", "flow", "config"):
        raise ValueError("No technical visual renderer for this diagram type")
    if (
        p["diagram"]["kind"] == "config"
        and p.get("model", {}).get("kind") not in SUPPORTED
    ):
        raise ValueError("No technical visual renderer for this scenario")


def evidence(p):
    """Only the problem data used in the picture, never repair/answer fields."""
    validate(p)
    if p["diagram"]["kind"] != "config":
        return p["diagram"]
    result = {
        "kind": "technical_visual",
        "data": {
            k: v
            for k, v in p["model"].items()
            if k not in ("kind", "expected", "seed") and not k.startswith("fixed")
        },
    }
    if p["model"]["kind"] == "duplicate":
        result["nodes"] = [
            {"type": "PC", "label": "PC A", "ip": p["model"]["a"]},
            {"type": "PC", "label": "PC B", "ip": p["model"]["b"]},
        ]
        result["connection"] = "Both PCs connect to a switch on the same VLAN"
    return result


def server(d, x, y):
    d.rounded_rectangle((x - 31, y - 42, x + 31, y + 38), radius=6, fill="#294e65")
    for yy in (y - 28, y - 6, y + 16):
        d.rounded_rectangle((x - 23, yy, x + 23, yy + 13), radius=2, fill="#d8e4eb")
        d.ellipse((x + 12, yy + 4, x + 17, yy + 9), fill="#3bb187")


def link(d, a, b, arrow=False, color="#426c83", dashed=False):
    if dashed:
        for i in range(0, 100, 12):
            x = a[0] + (b[0] - a[0]) * i / 100
            y = a[1] + (b[1] - a[1]) * i / 100
            xx = a[0] + (b[0] - a[0]) * min(i + 6, 100) / 100
            yy = a[1] + (b[1] - a[1]) * min(i + 6, 100) / 100
            d.line((x, y, xx, yy), fill=color, width=3)
    else:
        d.line((*a, *b), fill=color, width=3)
    if arrow:
        direction = 1 if b[0] >= a[0] else -1
        d.polygon(
            (b, (b[0] - direction * 9, b[1] - 5), (b[0] - direction * 9, b[1] + 5)),
            fill=color,
        )


def label(d, s, x, y, size=18, width=190, color=INK):
    return text(d, str(s), x, y, size, color, True, width=width, center=True)


def certificate(d, x, y, names):
    d.rounded_rectangle(
        (x - 80, y - 32, x + 80, y + 42),
        radius=5,
        fill="#eaf3f8",
        outline="#55788e",
        width=2,
    )
    d.line((x - 64, y - 17, x + 33, y - 17), fill="#9ab0bd", width=3)
    d.ellipse((x + 47, y - 23, x + 66, y - 4), outline="#cf9c34", width=3)
    label(d, "SAN: " + ", ".join(names), x, y + 2, 15, 150)


def draw(d, p, fixed):
    validate(p)
    from .clean_visual import computer, switch

    m = p["model"]
    kind = m["kind"]
    if kind == "url":
        return False  # Browser chrome has its own established screen renderer.
    d.rounded_rectangle((60, 366, 660, 623), radius=16, fill="white")
    if kind == "route":
        d.polygon(
            ((76, 430), (163, 430), (181, 448), (181, 492), (76, 492)),
            fill="#d6e9f8",
            outline="#426c83",
            width=2,
        )
        d.line((163, 430, 163, 448, 181, 448), fill="#426c83", width=2)
        d.line((85, 451, 153, 451), fill="#8caab8", width=2)
        label(d, "IPv4 packet", 128, 463, 15, 100)
        switch(d, 316, 459, True)
        link(d, (185, 459), (244, 459), True)
        label(d, "Destination", 121, 518, 16)
        label(d, m["destination"], 121, 544, 17)
        label(d, "Routing decision", 316, 525, 17)
        for i, (network, hop) in enumerate(m["routes"]):
            y = 402 + i * 76
            active = fixed and hop == m["expected"]
            link(d, (388, 459), (529, y), True, color=GREEN if active else "#688699")
            d.polygon(
                ((537, y - 10), (547, y - 19), (629, y - 19), (629, y - 10)),
                fill="#8caab8",
            )
            d.rounded_rectangle(
                (537, y - 10, 629, y + 12),
                radius=3,
                fill="#294e65",
                outline=GREEN if active else "#19394f",
                width=2,
            )
            for xx in (551, 567, 583, 599, 615):
                d.rectangle(
                    (xx - 4, y - 3, xx + 4, y + 5), fill="#102535", outline="#9db4c1"
                )
            d.line((572, y - 15, 601, y - 15), fill="white", width=2)
            d.polygon(((601, y - 18), (607, y - 15), (601, y - 12)), fill="white")
            label(d, hop, 583, y + 18, 17, 110)
            label(d, network, 452, y - 32, 14, 150)
    elif kind == "acl":
        computer(d, 121, 471)
        link(d, (166, 466), (257, 466), True)
        label(d, m["source"], 132, 540, 16, 140)
        label(d, "TCP 443", 208, 423, 17, 105)
        # A policy-processing stage, not an invented physical firewall appliance.
        d.polygon(
            ((278, 394), (448, 394), (448, 512), (363, 549), (278, 512)),
            fill="#e4eef5",
            outline="#426c83",
            width=3,
        )
        label(d, "IPv4 ACL", 363, 401, 20)
        rules = m["fixed_rules"] if fixed else m["rules"]
        for i, (action, net) in enumerate(rules):
            y = 443 + i * 50
            d.rounded_rectangle(
                (289, y - 4, 437, y + 42), radius=4, fill="white", outline="#9eb5c4"
            )
            label(d, f"{(i + 1) * 10} {action} {net}", 363, y, 14, 145)
        link(d, (449, 466), (548, 466), True)
        server(d, 590, 466)
        label(d, "HTTPS", 590, 525, 19)
    elif kind == "trunk":
        switch(d, 182, 469)
        switch(d, 538, 469)
        link(d, (254, 469), (466, 469))
        for x in (260, 460):
            d.rectangle((x - 4, 465, x + 4, 473), fill="#41a96a")
        label(d, "Switch A", 182, 516, 20)
        label(d, "Switch B", 538, 516, 20)
        label(d, "Allowed: " + ",".join(map(str, m["allowed_a"])), 182, 552, 17, 220)
        allowed = m["fixed_b"] if fixed else m["allowed_b"]
        label(d, "Allowed: " + ",".join(map(str, allowed)), 538, 552, 17, 220)
        d.rounded_rectangle(
            (309, 415, 411, 448), radius=5, fill="#dceafa", outline="#426c83", width=2
        )
        label(d, f"VLAN {m['vlan']}", 360, 422, 19)
        link(d, (287, 433), (306, 433), True)
        label(d, "Trunk link up", 360, 581, 17, 250)
    elif kind == "pool":
        computer(d, 137, 455)
        server(d, 407, 439)
        link(d, (183, 449), (369, 449), True)
        label(d, "DHCP DISCOVER", 276, 414, 16, 190)
        label(d, "New client", 137, 515, 18)
        label(d, "DHCP server", 407, 373, 19, 250)
        for i, address in enumerate(m["pool"]):
            x = 345 + i * 170
            d.rounded_rectangle(
                (x - 78, 515, x + 78, 597),
                radius=8,
                fill="#e4edf4",
                outline="#7193a8",
                width=2,
            )
            link(d, (407, 480), (x, 512))
            label(d, address, x, 530, 16, 150)
            # No invented lease owner or new scope is shown in the fix view.
            label(
                d, "Leased" if address in m["leased"] else "Available", x, 562, 16, 150
            )
    elif kind == "cache":
        computer(d, 130, 458)
        server(d, 352, 450)
        server(d, 584, 450)
        link(d, (176, 441), (319, 441), True)
        link(d, (319, 477), (176, 477), True)
        label(d, "DNS query", 244, 407, 16, 140)
        reply = m["authoritative"] if fixed else m["cached"]
        label(d, reply, 245, 492, 15, 150)
        link(d, (386, 450), (550, 450), dashed=True)
        label(d, "Upstream", 468, 407, 16, 150)
        label(d, "Client", 130, 528, 19)
        label(d, "Resolver cache", 352, 512, 18, 200)
        label(d, reply, 352, 543, 16, 190)
        label(d, "Refreshed" if fixed else f"TTL {m['ttl']} sec", 352, 573, 17, 190)
        label(d, "Authoritative", 584, 512, 17, 150)
        label(d, m["authoritative"], 584, 545, 15, 145)
    elif kind == "tls":
        computer(d, 156, 444)
        server(d, 560, 444)
        link(d, (201, 444), (523, 444), True)
        label(d, "TLS connection", 359, 405, 19, 270)
        label(d, "Requested host", 156, 506, 17)
        label(d, m["host"], 167, 536, 17, 205)
        label(d, "Server certificate", 542, 496, 17, 210)
        certificate(d, 547, 554, [m["host"]] if fixed else m["sans"])
        label(d, "Trusted / unexpired", 360, 593, 15, 250)
    elif kind == "broadcast":
        interface = ipaddress.ip_interface(m["fixed"] if fixed else m["ip"])
        network = interface.network
        computer(d, 155, 441)
        switch(d, 477, 441)
        link(d, (201, 441), (405, 441))
        label(d, str(interface), 163, 502, 18, 215)
        label(d, str(network), 483, 500, 19, 230)
        # Address-space position is derived numerically, not a diagnosis label.
        left, right, y = 112, 610, 578
        d.line((left, y, right, y), fill="#426c83", width=5)
        for x in (left, right):
            d.line((x, y - 8, x, y + 8), fill=INK, width=2)
        ratio = (int(interface.ip) - int(network.network_address)) / (
            network.num_addresses - 1
        )
        x = left + (right - left) * ratio
        d.polygon(((x, y - 9), (x - 7, y - 23), (x + 7, y - 23)), fill="#cc9d38")
        label(d, str(network.network_address), 180, 592, 14, 200)
        label(d, str(network.broadcast_address), 542, 592, 14, 200)
    elif kind == "mtu":
        computer(d, 117, 449)
        packet = m["fixed_packet"] if fixed else m["packet"]
        label(d, "Sender", 117, 516, 18)
        scale = 160 / max(m["packet"], m["mtu"])
        width = scale * packet
        d.rounded_rectangle(
            (219, 422, 219 + width, 478),
            radius=5,
            fill="#d6e9f8",
            outline="#426c83",
            width=2,
        )
        label(d, f"{packet} B", 299, 431, 20, 155)
        label(d, "DF = 1" if m["df"] else "DF = 0", 299, 493, 18)
        link(d, (162, 449), (213, 449), True)
        switch(d, 540, 449, True)
        link(d, (385, 449), (466, 449), True)
        if fixed:
            link(d, (613, 449), (640, 449), True, color=GREEN)
        label(d, "Path limit", 530, 515, 19, 200)
        label(d, f"MTU {m['mtu']} B", 530, 548, 19, 210)
    elif kind == "duplicate":
        computer(d, 149, 450)
        computer(d, 571, 450)
        switch(d, 360, 450)
        link(d, (194, 450), (288, 450))
        link(d, (432, 450), (526, 450))
        label(d, "PC A", 149, 514, 20)
        label(d, "PC B", 571, 514, 20)
        label(d, m["a"], 149, 546, 18)
        label(d, m["fixed_b"] if fixed else m["b"], 571, 546, 18)
        label(d, "Same VLAN", 360, 524, 18)
    else:
        raise ValueError("Unsupported technical visual")
    return True
