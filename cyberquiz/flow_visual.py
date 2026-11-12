"""Small readable technical graphs, including branches and three-device loops."""

import math
from .visual import text, INK, F


def check_annotations(view):
    count = sum(
        bool(detail.strip()) for n in view["nodes"] for detail in n.get("details", [])
    )
    count += sum(bool(edge["label"].strip()) for edge in view["edges"])
    if count > 4:
        raise ValueError(
            f"Diagram shows {count} settings and link labels. Keep at most four and remove labels that do not affect the answer."
        )


def triangle(view):
    positions = {n["id"]: i for i, n in enumerate(view["nodes"])}
    return len(positions) == 3 and any(
        abs(positions[e["from"]] - positions[e["to"]]) > 1 for e in view["edges"]
    )


def icon(d, node, x, y):
    from .clean_visual import computer, switch
    from .lab_visual import server

    kind = node["kind"]
    if kind in ("pc", "browser"):
        computer(d, x, y)
    elif kind in ("switch", "router"):
        switch(d, x, y, kind == "router")
    elif kind == "firewall":
        d.rounded_rectangle(
            (x - 36, y - 33, x + 36, y + 33),
            radius=5,
            fill="#294e65",
            outline="#19394f",
            width=2,
        )
        for row in range(4):
            yy = y - 32 + row * 16
            d.line((x - 35, yy + 16, x + 35, yy + 16), fill="#b9d6e2", width=2)
            for xx in range(-36 + (12 if row % 2 else 0), 37, 24):
                d.line((x + xx, yy, x + xx, yy + 16), fill="#b9d6e2", width=2)
    elif kind == "access_point":
        d.rounded_rectangle(
            (x - 30, y - 4, x + 30, y + 29),
            radius=9,
            fill="#294e65",
            outline="#19394f",
            width=2,
        )
        for radius in (14, 24, 34):
            d.arc(
                (x - radius, y - radius - 8, x + radius, y + radius - 8),
                205,
                335,
                fill="#365f79",
                width=3,
            )
        d.ellipse((x - 4, y + 4, x + 4, y + 12), fill="#5cce91")
    elif kind == "cloud":
        for xx, yy, rr in ((-25, 1, 25), (0, -16, 30), (29, 1, 24)):
            d.ellipse(
                (x + xx - rr, y + yy - rr, x + xx + rr, y + yy + rr),
                fill="#d6e8f2",
                outline="#294e65",
                width=2,
            )
        d.rounded_rectangle((x - 27, y, x + 30, y + 24), radius=7, fill="#d6e8f2")
    elif kind == "phone":
        d.rounded_rectangle((x - 23, y - 42, x + 23, y + 40), radius=8, fill="#294e65")
        d.rounded_rectangle((x - 18, y - 32, x + 18, y + 26), radius=3, fill="#d6e8f2")
        d.line((x - 7, y + 33, x + 7, y + 33), fill="white", width=2)
    else:
        server(d, x, y)
        if kind == "cache":
            d.ellipse(
                (x + 17, y + 13, x + 44, y + 40),
                fill="white",
                outline="#365f79",
                width=2,
            )
            d.line(
                (x + 30, y + 19, x + 30, y + 27, x + 36, y + 30),
                fill="#365f79",
                width=2,
            )


def boundary(node, ux, uy):
    wide = node["kind"] in ("router", "switch")
    hw, up, down = (72, 42, 24) if wide else (48, 42, 54)
    return (
        min(
            hw / abs(ux) if ux else 10000,
            (down if uy > 0 else up) / abs(uy) if uy else 10000,
        )
        + 5
    )


def draw(d, p):
    view = p["diagram"]
    nodes = view["nodes"]
    compact = triangle(view)
    points = (
        [(180, 466), (540, 466)]
        if len(nodes) == 2
        else (
            [(180, 426), (540, 426), (360, 550)]
            if compact
            else [(140, 466), (360, 466), (580, 466)]
        )
    )
    positions = {n["id"]: point for n, point in zip(nodes, points)}
    byid = {n["id"]: n for n in nodes}
    for edge in view["edges"]:
        x, y = positions[edge["from"]]
        xx, yy = positions[edge["to"]]
        length = math.hypot(xx - x, yy - y)
        ux, uy = (xx - x) / length, (yy - y) / length
        left = boundary(byid[edge["from"]], ux, uy)
        right = boundary(byid[edge["to"]], -ux, -uy)
        a = (x + ux * left, y + uy * left)
        b = (xx - ux * right, yy - uy * right)
        d.line((*a, *b), fill="#365f79", width=3)
        if edge.get("directional", True):
            d.polygon(
                [
                    b,
                    (b[0] - ux * 10 - uy * 5, b[1] - uy * 10 + ux * 5),
                    (b[0] - ux * 10 + uy * 5, b[1] - uy * 10 - ux * 5),
                ],
                fill="#365f79",
            )
        size = 14 if compact else 17
        width = 100 if compact else 180
        while size > 14 and F(size, False).getlength(edge["label"]) > width:
            size -= 1
        text(
            d,
            edge["label"],
            (x + xx) / 2,
            (y + yy) / 2 - (42 if compact else 75),
            size,
            INK,
            center=True,
        )
    for index, node in enumerate(nodes):
        x, y = positions[node["id"]]
        icon(d, node, x, y)
        title_y = 595 if compact and index == 2 else y + 57
        size = 18 if compact else 21
        while size > 16 and F(size, True).getlength(node["label"]) > (
            180 if compact else 192
        ):
            size -= 1
        text(d, node["label"], x, title_y, size, INK, True, center=True)
        for j, detail in enumerate(node.get("details", [])[:2]):
            dx, dy = (
                (530, 548 + j * 22)
                if compact and index == 2
                else (x, y + 81 + j * 22 if compact else 577 + j * 22)
            )
            size = 14 if compact else 16
            while size > 14 and F(size, False).getlength(detail) > (
                170 if compact else 190
            ):
                size -= 1
            if compact and index == 2:
                left = dx - F(size, False).getlength(detail) / 2
                right = x + boundary(node, 1, 0)
                if left > right + 12:
                    d.line((right, dy + 9, left - 6, dy + 9), fill="#8fa7b4", width=1)
            text(d, detail, dx, dy, size, INK, center=True)
