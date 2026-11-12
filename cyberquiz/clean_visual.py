"""Quiet Reel layout: one puzzle, one technical diagram, four answers."""

import copy
from functools import lru_cache
from PIL import Image, ImageDraw
from .store import ROOT
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
        from .flow_visual import draw

        draw(d, p)
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
        from .lab_visual import draw

        draw(d, p, fixed)
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


def clock(d, remaining, progress, dark):
    x, y, radius = 120, 1056, 43
    track = "#30465d" if dark else "#ccd7df"
    accent = "#ffca68" if remaining > 2 else "#ff937e"
    d.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill="#1c3046" if dark else "white",
        outline=track,
        width=7,
    )
    end = -90 + 360 * max(0, min(1, 1 - progress))
    d.arc(
        (x - radius, y - radius, x + radius, y + radius), -90, end, fill=accent, width=7
    )
    face = F(34, True)
    label = str(max(1, int(remaining)))
    box = d.textbbox((0, 0), label, font=face)
    d.text(
        (x - face.getlength(label) / 2, y - (box[3] - box[1]) / 2 - box[1]),
        label,
        font=face,
        fill="#f7fafc" if dark else INK,
    )


@lru_cache(maxsize=4)
def reel_badge(crop):
    size = 54
    with Image.open(ROOT / "data" / "reel-badge.jpg") as source:
        left, top, right, bottom = crop
        if not (
            0 <= left < right <= source.width and 0 <= top < bottom <= source.height
        ):
            raise ValueError("Badge crop is outside the image")
        badge = (
            source.crop(crop)
            .convert("RGB")
            .resize((size, size), Image.Resampling.LANCZOS)
        )
    mask = Image.new("L", badge.size)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return badge, mask


@lru_cache(maxsize=1)
def mascot_source():
    with Image.open(ROOT / "data" / "reel-mascot.png") as source:
        return source.convert("RGBA")


@lru_cache(maxsize=12)
def mascot_at_height(height):
    source = mascot_source()
    scale = min(138 / source.width, height / source.height)
    width = max(1, round(source.width * scale))
    height = max(1, round(source.height * scale))
    return source.resize((width, height), Image.Resampling.LANCZOS)


def frame(p, stage="question", remaining=None, phase=0, progress=0, subtitle=None):
    dark = p.get("palette") == "ink"
    fg = "#f7fafc" if dark else INK
    im = Image.new("RGB", (720, 1280), "#101c2b" if dark else "#f4f6f8")
    d = ImageDraw.Draw(im)
    lines = p["question"].split("\n")
    for n, line in enumerate(lines):
        size = 43
        while F(size, True).getlength(line) > 590:
            size -= 1
        text(
            d,
            line,
            360,
            (205 if len(lines) == 1 else 177) + n * 57,
            size,
            fg,
            True,
            center=True,
        )
    mascot = None
    if p.get("reel_mascot"):
        height = 108
        if stage == "reveal":
            # Ease out from the corner as the answer narration starts.
            height += round(76 * (1 - (1 - progress) ** 3))
        elif stage == "fix":
            height = 184
        try:
            mascot = mascot_at_height(height)
        except OSError:
            pass  # Optional artwork cannot block production.
    if not p.get("reel_mascot") and (crop := p.get("reel_badge_crop")):
        try:
            badge, mask = reel_badge(tuple(crop))
        except (OSError, ValueError, TypeError):
            pass  # Optional artwork cannot block production.
        else:
            im.paste(badge, (72, 294), mask)
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
            if p.get("countdown_style", "dial") == "dial":
                if remaining is not None:
                    clock(d, remaining, progress, dark)
                text(d, "Comment your answer.", 395, 1041, 25, fg, True, center=True)
            else:
                d.rounded_rectangle((74, 1020, 580, 1026), radius=3, fill="#edf1f4")
                d.rounded_rectangle(
                    (74, 1020, 74 + max(1, int(506 * (1 - progress))), 1026),
                    radius=3,
                    fill="#ffca68" if dark else "#2c718f",
                )
                if remaining is not None:
                    text(
                        d,
                        str(max(1, int(remaining))) + "s",
                        616,
                        1002,
                        24,
                        fg,
                        True,
                        center=True,
                    )
                text(d, "Comment your answer.", 360, 1067, 25, fg, True, center=True)
        else:
            center, width = (267, 390) if mascot else (360, 580)
            text(d, p["explanation"], center, 1020, 24, fg, width=width, center=True)
    if mascot:
        im.paste(mascot, (624 - mascot.width, 1168 - mascot.height), mascot)
    return im
