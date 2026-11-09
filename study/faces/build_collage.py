#!/usr/bin/env python3
"""Build the Genius Study header strip from plotted chart position.

Reads person records in a checkout of neuresthetics/neuresthetics_genius_study
and lays licensed portraits from portraits.json into a 900×180 strip.
Leftmost and largest is closest to the chart's top-right corner.

Only people with numeric A_locus and B_cause are ranked. That is the same
plotted set as figures/people_cause_locus.png. People who are not plotted
are left out.

Order:
  1. Euclidean distance to (A_locus 4, B_cause 4), smaller first.
     A_locus is the vertical axis, B_cause the horizontal axis.
  2. Dark before faded. Dark means the lower of the two axis certainties
     is at least 0.7, which is the darkness rule on the people chart.
  3. Tiebreak: filled before hollow (both axes corroborated, versus a
     hollow ring when either axis rests on one source), then higher
     minimum certainty, then display name A–Z.

This order is where plotted people sit on the chart. It is not a ranking
of genius and it is not a result.

Needs PyYAML, Pillow, and opencv-python-headless 4.x (face crop; 5.x
dropped CascadeClassifier). Without OpenCV, a portrait falls back to a
centered square.

Usage:
  python3 study/faces/build_collage.py --study /path/to/neuresthetics_genius_study
"""

import argparse
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

import yaml
from PIL import Image, ImageDraw, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WIDTH, HEIGHT = 900, 180
UA = "NeurestheticsStudyCollage/1.0 (https://neuresthetics.github.io; study header)"
OPEN_LICENSES = {"public domain", "cc0", "cc by", "cc by-sa"}


class _Loader(yaml.SafeLoader):
    """Keep dates as strings, matching the study repo's record reader."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def read_front_matter(path):
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---\n"):
        raise ValueError(path)
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(path)
    data = yaml.load(text[4:end], Loader=_Loader)
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def person_files(study):
    root = os.path.join(study, "people")
    out = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.endswith(".md") and name != "README.md":
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def scored(claim):
    value = (claim or {}).get("value")
    return isinstance(value, int) and not isinstance(value, bool)


def support_level(claim):
    """Match scripts/lib/records.py: corroborated when two sources agree."""
    if not scored(claim):
        return None
    main = {c.get("source") for c in claim.get("cites") or [] if isinstance(c, dict)}
    for alt in claim.get("alternatives") or []:
        if {c.get("source") for c in alt.get("cites") or [] if isinstance(c, dict)} - main:
            return "single"
    return "corroborated" if len(main) >= 2 else "single"


def plotted_people(study):
    people = []
    for path in person_files(study):
        data = read_front_matter(path)
        if data.get("record", {}).get("record_type") != "person":
            continue
        axes = data["worldview"]["lio_axes"]
        a_claim, b_claim = axes["A_locus"], axes["B_cause"]
        if not (scored(a_claim) and scored(b_claim)):
            continue
        cert = min(a_claim.get("certainty") or 0, b_claim.get("certainty") or 0)
        filled = support_level(a_claim) == support_level(b_claim) == "corroborated"
        ident = data["identity"]
        people.append({
            "id": ident["id"],
            "name": ident["display_name"],
            "A": a_claim["value"],
            "B": b_claim["value"],
            "cA": a_claim.get("certainty"),
            "cB": b_claim.get("certainty"),
            "cert": cert,
            "dark": cert >= 0.7,
            "filled": filled,
        })
    return people


def rank_key(person):
    distance = ((4 - person["A"]) ** 2 + (4 - person["B"]) ** 2) ** 0.5
    return (
        round(distance, 6),
        0 if person["dark"] else 1,
        0 if person["filled"] else 1,
        -person["cert"],
        person["name"].casefold(),
    )


def source_commit(study):
    sha = subprocess.check_output(
        ["git", "-C", study, "rev-parse", "HEAD"], text=True).strip()
    date = subprocess.check_output(
        ["git", "-C", study, "log", "-1", "--format=%cs", "HEAD"], text=True).strip()
    return sha, date


def license_ok(name):
    short = name.strip().lower()
    if "nc" in short or "nd" in short or "copyright" in short:
        return False
    if short in OPEN_LICENSES:
        return True
    if short.startswith("cc by") and "nc" not in short and "nd" not in short:
        return True
    return short.startswith("public domain") or short == "cc0"


def commons_thumb(filename, dest, width=800):
    query = urllib.parse.urlencode({
        "action": "query",
        "titles": "File:" + filename,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": str(width),
        "format": "json",
    })
    req = urllib.request.Request(
        "https://commons.wikimedia.org/w/api.php?" + query,
        headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    page = next(iter(payload["query"]["pages"].values()))
    if "missing" in page or "imageinfo" not in page:
        raise RuntimeError("missing on Commons: " + filename)
    info = page["imageinfo"][0]
    meta = info.get("extmetadata") or {}
    license_name = re.sub(r"<[^>]+>", "", (meta.get("LicenseShortName") or {}).get("value") or "")
    license_name = html.unescape(license_name).strip()
    if not license_ok(license_name):
        raise RuntimeError(f"{filename} is {license_name or 'unlicensed'}")
    thumb = info.get("thumburl") or info["url"]
    img_req = urllib.request.Request(thumb, headers={"User-Agent": UA})
    with urllib.request.urlopen(img_req, timeout=60) as resp:
        open(dest, "wb").write(resp.read())
    return license_name


def face_square(im, scale=1.9, crop_frac=None):
    if crop_frac:
        w, h = im.size
        left, top, right, bottom = crop_frac
        box = im.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))
        side = min(box.size)
        return box.crop((0, 0, side, side))
    try:
        import cv2
        import numpy as np
    except ImportError:
        cv2 = None
    if cv2 is not None:
        rgb = np.array(im.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        found = cascade.detectMultiScale(gray, 1.08, 4, minSize=(30, 30))
        if len(found):
            x, y, w, h = max(found, key=lambda box: box[2] * box[3])
            side = int(max(w, h) * scale)
            cx, cy = x + w / 2, y + h * 0.46
            left = int(round(cx - side / 2))
            top = int(round(cy - side / 2))
            return im.crop((left, top, left + side, top + side))
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = max(0, int((h - side) * 0.08))
    return im.crop((left, top, left + side, top + side))


def sepia(im):
    gray = ImageOps.grayscale(im)
    return ImageOps.colorize(gray, black="#1a120c", mid="#b8926a", white="#f4ead8")


def circle(im, diameter, scale=1.9, crop_frac=None):
    face = sepia(face_square(im, scale, crop_frac)).resize((diameter, diameter), Image.Resampling.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    face.putalpha(mask)
    return face


def layout(count):
    """Diameters and centers. Leftmost is largest. The row fills 900px.

    The smallest face stays at least 64px in the file (about 28px on a
    390px-wide phone). Returns None when another face would break that.
    """
    if count <= 0:
        return None
    margin = 8
    decay = 0.94
    overlap = 0.42

    def row(start):
        sizes = [start * (decay ** i) for i in range(count)]
        xs = []
        for index, size in enumerate(sizes):
            if index == 0:
                cx = margin + size / 2
            else:
                prev = sizes[index - 1]
                gap = prev / 2 + size / 2 - overlap * min(prev, size)
                cx = xs[-1] + gap
            xs.append(cx)
        right = xs[-1] + sizes[-1] / 2
        return sizes, xs, right

    lo, hi = 64.0, 220.0
    best = None
    for _ in range(48):
        mid = (lo + hi) / 2
        sizes, xs, right = row(mid)
        if sizes[-1] >= 64 and right <= WIDTH - margin:
            best = (sizes, xs, right)
            lo = mid
        else:
            hi = mid
    if not best:
        return None
    sizes, xs, right = best
    # Use the leftover width so the row meets the right edge.
    slack = (WIDTH - margin) - right
    if slack > 0 and len(xs) > 1:
        step = slack / (len(xs) - 1)
        xs = [x + step * i for i, x in enumerate(xs)]
    return [int(round(s)) for s in sizes], xs


def load_portrait(name, meta, cache):
    if not license_ok(meta["license"]):
        raise RuntimeError(name + " catalog license is not open: " + meta["license"])
    dest = os.path.join(cache, re.sub(r"[^A-Za-z0-9._-]+", "_", meta["commons_file"]))
    if not os.path.exists(dest):
        commons_license = commons_thumb(meta["commons_file"], dest)
        if not license_ok(commons_license):
            os.remove(dest)
            raise RuntimeError(name + " Commons license changed: " + commons_license)
    return Image.open(dest).convert("RGB")


def caption_date(iso_date):
    year, month, day = iso_date.split("-")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{int(day)} {months[int(month) - 1]} {year}"


def write_order(path, sha, iso_date, placed, unlicensed):
    lines = [
        "Genius Study header faces",
        f"Source: neuresthetics/neuresthetics_genius_study main {sha} ({iso_date})",
        "Chart: figures/people_cause_locus.png",
        "Plotted only: numeric A_locus and numeric B_cause.",
        "Order: Euclidean distance to (A_locus 4, B_cause 4), smaller first;",
        "then dark before faded (minimum certainty >= 0.7 before below);",
        "tiebreak: filled before hollow, then higher minimum certainty, then display name A–Z.",
        "This is chart position, not a ranking of genius.",
        "",
        "rank\tid\tname\tA_locus\tB_cause\tdistance\tmin_certainty\tcue\tlicense\tcommons_file",
    ]
    for index, person in enumerate(placed, 1):
        distance = ((4 - person["A"]) ** 2 + (4 - person["B"]) ** 2) ** 0.5
        cue = ("dark" if person["dark"] else "faded") + " " + ("filled" if person["filled"] else "hollow")
        lines.append("\t".join([
            str(index), person["id"], person["name"], str(person["A"]), str(person["B"]),
            f"{distance:.3f}", f"{person['cert']}", cue, person["license"], person["commons_file"],
        ]))
    lines.append("")
    if unlicensed:
        lines.append("Reached in rank order but not placed, no open portrait in portraits.json:")
        for person in unlicensed:
            lines.append(f"- {person['name']} ({person['id']}) A {person['A']} B {person['B']}")
    else:
        lines.append("No face that fit in the strip was dropped for lack of an open portrait.")
    lines.append("")
    text = "\n".join(lines)
    open(path, "w", encoding="utf-8").write(text)


def license_cell(meta):
    if meta["license_url"]:
        return f'<a href="{html.escape(meta["license_url"])}">{html.escape(meta["license"])}</a>'
    return html.escape(meta["license"])


def credits_table(placed):
    rows = []
    for index, person in enumerate(placed, 1):
        file_name = person["commons_file"]
        href = "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(file_name.replace(" ", "_"))
        rows.append(
            "<tr>\n"
            f"<td>{index}</td>\n"
            f"<td>{html.escape(person['name'])}</td>\n"
            f'<td><a href="{href}">{html.escape(file_name)}</a></td>\n'
            f"<td>{license_cell(person)}</td>\n"
            f"<td>{html.escape(person['author'])}</td>\n"
            "</tr>"
        )
    return "\n".join(rows)


def replace_between(path, start, end, body):
    text = open(path, encoding="utf-8").read()
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    updated, n = pattern.subn(start + body + end, text, count=1)
    if n != 1:
        raise RuntimeError("marker missing in " + path)
    open(path, "w", encoding="utf-8").write(updated)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", default=os.environ.get("GENIUS_STUDY", ""))
    args = parser.parse_args()
    if not args.study:
        raise SystemExit("pass --study PATH to neuresthetics_genius_study")
    catalog = json.load(open(os.path.join(HERE, "portraits.json"), encoding="utf-8"))
    sha, iso_date = source_commit(args.study)
    ranked = sorted(plotted_people(args.study), key=rank_key)
    cache = os.path.join(HERE, ".cache")
    os.makedirs(cache, exist_ok=True)

    # Walk the ranking. Skip a person with no open portrait only while another
    # face would still fit. Once the strip is full, stop. Later people are not
    # reported as unlicensed; they simply did not fit.
    chosen = []
    unlicensed = []
    for person in ranked:
        if layout(len(chosen) + 1) is None:
            break
        meta = catalog.get(person["name"])
        if not meta:
            unlicensed.append(person)
            continue
        try:
            load_portrait(person["name"], meta, cache)
        except RuntimeError:
            unlicensed.append(person)
            continue
        placed = dict(person)
        placed.update(meta)
        chosen.append(placed)
    if not chosen:
        raise SystemExit("no licensed portraits")

    sizes, xs = layout(len(chosen))
    sheet = Image.new("RGB", (WIDTH, HEIGHT), "#14110e")
    for person, size, cx in zip(chosen, sizes, xs):
        portrait = load_portrait(person["name"], person, cache)
        disc = circle(portrait, size, person.get("crop_scale", 1.9), person.get("crop_frac"))
        left = int(round(cx - size / 2))
        top = int(round((HEIGHT - size) / 2))
        sheet.paste(disc, (left, top), disc)
    out_img = os.path.join(REPO, "assets", "img", "study", "faces-by-chart.jpg")
    sheet.save(out_img, quality=90, optimize=True)

    write_order(os.path.join(HERE, "order.txt"), sha, iso_date, chosen, unlicensed)

    short = sha[:7]
    caption = (
        "Faces ordered by position on the people chart (top-right first), as of "
        f"{caption_date(iso_date)} / {short}."
    )
    replace_between(
        os.path.join(REPO, "study", "index.html"),
        "<!-- faces-caption -->", "<!-- /faces-caption -->",
        caption + " ")
    intro = (
        "<p>The Genius Study header (<code>assets/img/study/faces-by-chart.jpg</code>) "
        "shows people who are plotted on the people chart, both axes numeric. "
        "From the left, they follow that chart: closest to the top-right corner first, "
        "then the rest of the strip in the same order. "
        f"Source commit {html.escape(short)} ({html.escape(caption_date(iso_date))}) of "
        '<a href="https://github.com/neuresthetics/neuresthetics_genius_study">neuresthetics_genius_study</a>. '
        "This is where those people sit on the chart, not a ranking of genius. "
        "Every file is public domain or under a free license, as listed below. "
        "The strip as a whole is shared under CC BY-SA 4.0 because it includes CC BY-SA portraits.</p>\n"
        "<table>\n<thead>\n<tr>\n<th>#</th>\n<th>Person</th>\n"
        "<th>File (Wikimedia Commons)</th>\n<th>License</th>\n<th>Author / source</th>\n"
        "</tr>\n</thead>\n<tbody>\n"
        + credits_table(chosen) +
        "\n</tbody>\n</table>\n"
    )
    replace_between(
        os.path.join(REPO, "credits", "index.html"),
        "<!-- study-faces-credits -->", "<!-- /study-faces-credits -->",
        "\n" + intro)

    print(f"wrote {len(chosen)} faces from {sha[:12]} ({iso_date})")
    for index, person in enumerate(chosen, 1):
        print(f"{index:2} {person['name']} A{person['A']} B{person['B']} {person['license']}")
    if unlicensed:
        print("unlicensed before the strip filled:")
        for person in unlicensed:
            print(" -", person["name"])


if __name__ == "__main__":
    main()
