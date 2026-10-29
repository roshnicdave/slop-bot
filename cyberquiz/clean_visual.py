"""Quiet Reel layout: one puzzle, one technical diagram, four answers."""

import copy
from PIL import Image, ImageDraw
from .visual import F, text, INK, GREEN


def computer(d, x, y):
    d.rounded_rectangle((x - 42, y - 38, x + 42, y + 19), radius=5, fill="#213e54")
    for n in range(45):
        c = 220 - int(n * 0.7)
        d.line(
            (x - 35, y - 31 + n, x + 35, y - 31 + n),
            fill=(c, 235 - int(n * 0.35), 242 - int(n * 0.25)),
        )
    d.rectangle((x - 8, y + 20, x + 8, y + 33), fill="#8c9fac")
    d.rounded_rectangle((x - 28, y + 32, x + 28, y + 38), radius=4, fill="#b7c5cd")
    d.polygon(
        [(x - 42, y + 44), (x + 42, y + 44), (x + 48, y + 54), (x - 48, y + 54)],
        fill="#d1dce2",
        outline="#8498a5",
    )
    for dx in range(-31, 32, 9):
        d.line((x + dx, y + 47, x + dx + 4, y + 51), fill="#8e9fa9", width=2)


def switch(d, x, y, router=False):
    d.polygon(
        [(x - 72, y - 23), (x - 55, y - 42), (x + 72, y - 42), (x + 72, y - 23)],
        fill="#8caab8",
    )
    d.rounded_rectangle(
        (x - 72, y - 23, x + 72, y + 22),
        radius=5,
        fill="#294e65",
        outline="#19394f",
        width=2,
    )
    for dx in range(-55, 56, 16):
        d.rectangle(
            (x + dx - 5, y - 7, x + dx + 5, y + 5), fill="#102535", outline="#9db4c1"
        )
        d.rectangle((x + dx - 3, y + 9, x + dx + 2, y + 12), fill="#5cce91")
    for dx in (-28, 20):
        d.line((x + dx - 13, y - 32, x + dx + 13, y - 32), fill="white", width=3)
        d.polygon(
            [(x + dx + 13, y - 36), (x + dx + 20, y - 32), (x + dx + 13, y - 28)],
            fill="white",
        )
    if router:
        d.ellipse((x - 12, y - 39, x + 12, y - 25), outline="white", width=2)


def diagram(d, p, fixed):
    view = copy.deepcopy(p["diagram"])
    kind = view["kind"]
    fix = p.get("fix_diagram", {})
    if kind == "flow":
        nodes = view["nodes"]
        positions = {n["id"]: (140 + i * 220, 466) for i, n in enumerate(nodes)}
        if len(nodes) == 2:
            positions = {nodes[0]["id"]: (180, 466), nodes[1]["id"]: (540, 466)}
        for edge in view["edges"]:
            x, y = positions[edge["from"]]
            xx, yy = positions[edge["to"]]
            direction = 1 if xx > x else -1
            start = x + 48 * direction
            end = xx - 48 * direction
            d.line((start, y, end, yy), fill="#365f79", width=4)
            d.polygon(
                [
                    (end, yy),
                    (end - 10 * direction, yy - 6),
                    (end - 10 * direction, yy + 6),
                ],
                fill="#365f79",
            )
            text(
                d,
                edge["label"],
                (start + end) / 2,
                y - 42,
                17,
                INK,
                width=180,
                center=True,
            )
        for node in nodes:
            x, y = positions[node["id"]]
            if node["kind"] in ("pc", "browser"):
                computer(d, x, y)
            elif node["kind"] == "router":
                switch(d, x, y, True)
            else:
                d.rounded_rectangle(
                    (x - 37, y - 40, x + 37, y + 43),
                    radius=6,
                    fill="#294e65",
                    outline="#102c40",
                    width=2,
                )
                for offset in (-24, -2, 20):
                    d.rounded_rectangle(
                        (x - 27, y + offset, x + 27, y + offset + 13),
                        radius=2,
                        fill="#d8e4eb",
                    )
                    d.ellipse(
                        (x + 16, y + offset + 4, x + 21, y + offset + 9), fill="#38965f"
                    )
            text(d, node["label"], x, 543, 21, INK, True, width=192, center=True)
        return
    if kind == "config":
        if p.get("model", {}).get("kind") == "url":
            d.rounded_rectangle(
                (60, 374, 660, 600), radius=14, fill="white", outline="#c9d5dc", width=2
            )
            d.rounded_rectangle((60, 374, 660, 421), radius=14, fill="#e9eef2")
            for x in (83, 102, 121):
                d.ellipse((x - 4, 393, x + 4, 401), fill="#9badb9")
            url = p["model"]["url"]
            text(d, url, 360, 459, 21, INK, width=554, center=True)
            if fixed:
                text(d, p["answer"], 360, 540, 29, GREEN, True, center=True)
            return
        # Use the checked renderer for configuration cards; strip decorative label.
        lines = view["lines"]
        d.rounded_rectangle(
            (60, 370, 660, 622), radius=15, fill="#f0f4f7", outline="#c9d5dc", width=2
        )
        for n, line in enumerate(lines):
            size = 24
            while F(size, True).getlength(line) > 550:
                size -= 1
            text(d, line, 86, 398 + n * 49, size, INK, True)
        return
    if kind != "switch":
        from .visual import topology

        topology(d, p, fixed)
        return
    if fixed:
        if "right_vlan" in fix:
            view["right"]["vlan"] = fix["right_vlan"]
        if "right_ip" in fix:
            view["right"]["ip"] = fix["right_ip"]
        if "left_gateway" in fix:
            view["left"]["gateway"] = fix["left_gateway"]
    x1, x2, x3, y = 140, 360, 580, 466
    for start, end in [(x1 + 44, x2 - 72), (x2 + 72, x3 - 44)]:
        d.line((start, y, end, y), fill="#375c74", width=4)
        for x in (start + 5, end - 5):
            d.rectangle((x - 4, y - 4, x + 4, y + 4), fill="#41a96a")
    computer(d, x1, y)
    computer(d, x3, y)
    switch(d, x2, y, kind == "router")
    text(d, "PC 1", x1, 535, 23, INK, True, center=True)
    text(d, "PC 2", x3, 535, 23, INK, True, center=True)
    text(
        d,
        "L2 switch" if kind == "switch" else "Router",
        x2,
        523,
        21,
        INK,
        True,
        center=True,
    )
    for x, node in [(x1, view["left"]), (x3, view["right"])]:
        if "vlan" in node:
            text(
                d,
                "VLAN " + str(node["vlan"]),
                x,
                385,
                25,
                GREEN if fixed else INK,
                True,
                center=True,
            )
        text(d, node.get("ip", ""), x, 577, 17, INK, center=True)
    # No animated packet is invented where the protocol would not emit one.


def frame(p, stage="question", remaining=None, phase=0, progress=0, subtitle=None):
    dark = p.get("palette") == "ink"
    fg = "#f7fafc" if dark else INK
    im = Image.new("RGB", (720, 1280), "#101c2b" if dark else "#f4f6f8")
    d = ImageDraw.Draw(im)
    for n, line in enumerate(p["question"].split("\n")):
        size = 43
        while F(size, True).getlength(line) > 590:
            size -= 1
        text(d, line, 360, 137 + n * 57, size, fg, True, center=True)
    if dark and p["diagram"]["kind"] in ("switch", "flow"):
        d.rounded_rectangle((60, 366, 660, 623), radius=16, fill="white")
    diagram(d, p, stage == "fix")
    if stage == "fix":
        if p.get("model", {}).get("kind") != "url":
            text(
                d,
                p["fix"],
                360,
                737,
                32,
                "#8ce2b9" if dark else GREEN,
                True,
                width=570,
                center=True,
            )
    else:
        for n, answer in enumerate(p["options"]):
            y = 676 + n * 80
            correct = stage == "reveal" and n == p["correct"]
            d.rounded_rectangle(
                (72, y, 648, y + 64),
                radius=13,
                fill="#c2eed8" if correct else ("#1c3046" if dark else "#ffffff"),
                outline=GREEN if correct else ("#6e8aa0" if dark else "#899da9"),
                width=2,
            )
            text(d, "ABCD"[n] + ".", 94, y + 15, 28, GREEN if correct else fg, True)
            size = 27
            while F(size, True).getlength(answer) > 472:
                size -= 1
            text(d, answer, 144, y + 16, size, GREEN if correct else fg, True)
        if stage == "question":
            d.rounded_rectangle((74, 1020, 646, 1026), radius=3, fill="#edf1f4")
            d.rounded_rectangle(
                (74, 1020, 74 + max(1, int(572 * (1 - progress))), 1026),
                radius=3,
                fill="#ffca68" if dark else "#2c718f",
            )
            text(d, "Comment your answer.", 360, 1067, 25, fg, True, center=True)
        else:
            text(d, p["explanation"], 360, 1020, 24, fg, width=580, center=True)
    return im
