"""Vertical H.264 + AAC video; generated art, readable overlays, timed voice."""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 720, 1280
BG = (7, 14, 27)
WHITE = (242, 247, 251)
MUTED = (160, 179, 200)
CYAN = (65, 220, 231)
LIME = (197, 248, 104)


def font(size, bold=False):
    inter = Path(__file__).resolve().parents[1] / "assets/fonts/Inter.ttf"
    if inter.exists():
        face = ImageFont.truetype(str(inter), size)
        face.set_variation_by_axes([24, 650 if bold else 450])
        return face
    candidates = (
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise RuntimeError("Install DejaVu Sans fonts before rendering")


def wrap(text, f, width):
    lines = []
    line = ""
    for word in text.split():
        test = (line + " " + word).strip()
        if f.getlength(test) > width and line:
            lines.append(line)
            line = word
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def block(draw, text, xy, size, width, color=WHITE, bold=False, max_lines=4):
    for candidate in range(size, min(size, 12) - 1, -1):
        f = font(candidate, bold)
        lines = wrap(text, f, width)
        if len(lines) <= max_lines:
            break
    if len(lines) > max_lines or any(f.getlength(x) > width for x in lines):
        raise ValueError("Text cannot fit safely in video frame")
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=f, fill=color)
        y += candidate + 9
    return y


def panel(plan, path, reveal=False, count=None):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, H), fill=(*BG, 195))
    d.rectangle((0, 0, W, 340), fill=(*BG, 35))
    d.rounded_rectangle((42, 54, 255, 90), radius=15, fill=(*BG, 230))
    d.text((57, 62), "PACKET / DAILY", font=font(17, True), fill=CYAN)
    d.text(
        (44, 270),
        "SECURITY BRIEF"
        if plan["family"] == "recent-kev"
        else (
            "INTERVIEW CHECK" if plan.get("format") == "challenge" else "NETWORK CHECK"
        ),
        font=font(19, True),
        fill=CYAN,
    )
    block(d, plan["question"], (42, 312), 35, 625, bold=True, max_lines=4)
    y = 535
    for i, answer in enumerate(plan["options"]):
        correct = reveal and i == plan["correct"]
        color = LIME if correct else (42, 61, 81)
        d.rounded_rectangle(
            (42, y, 674, y + 82), radius=14, fill=(*BG, 230), outline=color, width=2
        )
        d.text(
            (64, y + 24), "ABC"[i], font=font(23, True), fill=LIME if correct else CYAN
        )
        block(
            d,
            answer,
            (110, y + 21),
            25,
            535,
            LIME if correct else WHITE,
            bold=correct,
            max_lines=2,
        )
        y += 96
    if reveal:
        d.text((44, 854), "WHY IT WORKS", font=font(18, True), fill=LIME)
        block(d, plan["explanation"], (44, 890), 26, 615, max_lines=5)
    else:
        d.text((44, 858), "Choose before the reveal", font=font(23), fill=WHITE)
        if count is not None:
            d.ellipse((565, 838, 647, 920), outline=CYAN, width=3)
            d.text((592, 853), str(count), font=font(36, True), fill=LIME)
        else:
            d.text((44, 901), "A / B / C", font=font(22, True), fill=LIME)
    label = plan["source_label"]
    block(d, "SOURCE / " + label, (44, 1088), 15, 610, MUTED, max_lines=2)
    d.line((44, 1148, 674, 1148), fill=(*MUTED, 120), width=1)
    d.text((44, 1168), "@cybersec.peter", font=font(22, True), fill=WHITE)
    d.text((465, 1172), "LEARN / REPEAT", font=font(15), fill=CYAN)
    im.save(path)


def duration(path):
    import wave

    try:
        with wave.open(str(path)) as wav:
            return wav.getnframes() / wav.getframerate()
    except (wave.Error, EOFError):
        pass
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(p.stdout)["format"]["duration"])


def render(folder):
    folder = Path(folder).resolve()
    p = json.loads((folder / "plan.json").read_text())
    intro = duration(folder / "intro.wav")
    outro = duration(folder / "outro.wav")
    decision = int(p.get("decision_seconds", 5))
    if decision not in (3, 5):
        raise ValueError("Invalid countdown length")
    total = intro + decision + outro + 2
    panel(p, folder / "question.png")
    panel(p, folder / "reveal.png", True)
    scenes = [("question.png", intro)]
    for i in range(decision, 0, -1):
        name = f"count-{i}.png"
        panel(p, folder / name, count=i)
        scenes.append((name, 1))
    scenes.append(("reveal.png", outro + 2))
    # Precompose seven frames instead of running multiple video streams. This
    # keeps FFmpeg memory bounded on the existing 512 MB Lightsail instance.
    bg = Image.open(folder / "background.jpg").convert("RGBA").resize((W, H))
    composed = []
    for name, secs in scenes:
        target = folder / (Path(name).stem + ".jpg")
        overlay = Image.open(folder / name).convert("RGBA")
        Image.alpha_composite(bg, overlay).convert("RGB").save(target, quality=92)
        composed.append((target.name, secs))
    sequence = folder / "scenes.ffconcat"
    sequence.write_text(
        "ffconcat version 1.0\n"
        + "".join(f"file '{name}'\nduration {secs:.6f}\n" for name, secs in composed)
        + "file 'reveal.jpg'\n"
    )
    # Build audio first. A combined A/V filter graph can buffer hundreds of
    # uncompressed frames while loudnorm waits for audio on a tiny server.
    import wave

    with (
        wave.open(str(folder / "intro.wav")) as first,
        wave.open(str(folder / "outro.wav")) as second,
    ):
        if first.getparams()[:3] != second.getparams()[:3]:
            raise ValueError("Voice sample formats differ; stop before video encoding")
        channels, width, rate = first.getparams()[:3]
        with wave.open(str(folder / "speech.wav"), "wb") as combined:
            combined.setnchannels(channels)
            combined.setsampwidth(width)
            combined.setframerate(rate)
            combined.writeframes(first.readframes(first.getnframes()))
            combined.writeframes(bytes(decision * rate * channels * width))
            combined.writeframes(second.readframes(second.getnframes()))
            combined.writeframes(bytes(2 * rate * channels * width))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "1",
            "-i",
            str(folder / "speech.wav"),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(folder / "speech.m4a"),
        ],
        check=True,
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-threads",
        "1",
        "-i",
        str(sequence),
        "-i",
        str(folder / "speech.m4a"),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-filter_threads",
        "1",
        "-vf",
        "fps=24,format=yuv420p",
        "-c:v",
        "libx264",
        "-threads",
        "1",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-x264-params",
        "rc-lookahead=0:ref=1:bframes=0",
        "-crf",
        "21",
        "-r",
        "24",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        "-t",
        str(total),
        str(folder / "reel.tmp.mp4"),
    ]
    subprocess.run(command, check=True)
    if (folder / "reel.tmp.mp4").stat().st_size < 1000:
        raise RuntimeError("Rendered video is unexpectedly small")
    (folder / "reel.tmp.mp4").replace(folder / "reel.mp4")
    (folder / "timing.json").write_text(
        json.dumps(
            {
                "intro_seconds": intro,
                "countdown_seconds": decision,
                "reveal_at": intro + decision,
                "outro_seconds": outro,
                "total_seconds": total,
            },
            indent=2,
        )
    )
    (folder / "caption.txt").write_text(p["caption"])
    # Preview image includes the real generated art.
    bg = Image.open(folder / "background.jpg").convert("RGBA").resize((W, H))
    Image.alpha_composite(bg, Image.open(folder / "question.png")).convert("RGB").save(
        folder / "preview.jpg"
    )
    return folder / "reel.mp4"
