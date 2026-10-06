#!/usr/bin/env python3
"""Exact-layout OCR: image -> monospaced text (Courier New) preserving spacing.

Usage:  python exact_ocr.py image.png [-o out_basename] [--lang eng] [--psm 6]
Writes  <out>.txt  (plain, fixed-width layout)
        <out>.html (same text rendered in Courier New)
        <out>.docx (Courier New, only if python-docx is installed)
"""
import argparse
import html
import statistics
import sys
from pathlib import Path

import pytesseract
from PIL import Image, ImageChops, ImageOps

MIN_HEIGHT = 1800  # upscale small images so Tesseract sees enough pixels


def median_level(ch):
    hist, half, acc = ch.histogram(), ch.width * ch.height / 2, 0
    for level, n in enumerate(hist):
        acc += n
        if acc >= half:
            return level


def fix_braces(text):
    """Tesseract reads a lone { or } as i/l/[/$/3...; restore them from indentation."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip() in ("i", "I", "l", "[", "$", "&", "|", "1", "3", "BI", "IF", "DIF"):
            ind = len(ln) - len(ln.lstrip())
            nxt = next((x for x in lines[i + 1:] if x.strip()), "")
            opens = len(nxt) - len(nxt.lstrip()) > ind
            lines[i] = " " * ind + ("{" if opens else "}")
        elif ln.strip() in ("//i", "//I", "//[", "//1"):
            lines[i] = ln.replace(ln.strip(), "//{")
        elif ln.strip() in ("//3);", "//5);", "//1);"):
            lines[i] = ln.replace(ln.strip(), "//});")
        elif ln.strip().startswith("3);") or ln.strip().startswith("5)"):
            lines[i] = ln.replace("3);", "});", 1).replace("5)", "});", 1)
    return "\n".join(lines)


def load(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if img.height < MIN_HEIGHT:
        s = MIN_HEIGHT / img.height
        img = img.resize((round(img.width * s), MIN_HEIGHT), Image.LANCZOS)
    # ink = distance from the background colour, so coloured syntax-highlighted text
    # (e.g. dark-blue braces on a dark theme) stays as strong as white text
    bg = [median_level(ch) for ch in img.split()]
    diff = [ImageChops.difference(ch, Image.new("L", img.size, b)) for ch, b in zip(img.split(), bg)]
    ink = ImageChops.lighter(ImageChops.lighter(diff[0], diff[1]), diff[2])
    gray = ImageOps.invert(ImageOps.autocontrast(ink, cutoff=1))
    return gray


def read_words(img, lang, psm):
    d = pytesseract.image_to_data(
        img, lang=lang, config=f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
        output_type=pytesseract.Output.DICT)
    words = []
    for i, t in enumerate(d["text"]):
        if t.strip() and float(d["conf"][i]) >= 0:
            words.append(dict(t=t.strip(), x=d["left"][i], y=d["top"][i],
                              w=d["width"][i], h=d["height"][i]))
    return words


def to_layout(words):
    if not words:
        return ""
    # character cell width: median of word pixel width / chars (longer words are more reliable)
    ws = [w["w"] / len(w["t"]) for w in words if len(w["t"]) >= 3] or \
         [w["w"] / len(w["t"]) for w in words]
    cw = statistics.median(ws)
    lh = statistics.median(w["h"] for w in words)

    # cluster words into visual rows by vertical centre
    words.sort(key=lambda w: w["y"] + w["h"] / 2)
    rows, cur = [], [words[0]]
    for w in words[1:]:
        cy = statistics.fmean(c["y"] + c["h"] / 2 for c in cur)
        if abs(w["y"] + w["h"] / 2 - cy) < 0.6 * lh:
            cur.append(w)
        else:
            rows.append(cur)
            cur = [w]
    rows.append(cur)

    cys = [statistics.fmean(w["y"] + w["h"] / 2 for w in r) for r in rows]
    gaps = [b - a for a, b in zip(cys, cys[1:])]
    pitch = max(min(gaps), lh) if gaps else lh  # one text line of vertical space
    x0 = min(w["x"] for w in words)
    out, prev_cy = [], None
    for row in rows:
        cy = statistics.fmean(w["y"] + w["h"] / 2 for w in row)
        if prev_cy is not None:  # keep vertical gaps as blank lines
            out.extend([""] * max(0, round((cy - prev_cy) / pitch) - 1))
        prev_cy = cy
        line, prev_end = "", None
        for w in sorted(row, key=lambda w: w["x"]):
            if not line:  # indent measured from the left edge of the page
                line = " " * max(0, round((w["x"] - x0) / cw))
            else:  # gaps measured from the previous word, so errors don't accumulate
                gap = round((w["x"] - prev_end) / cw)
                if w["t"][0] in ".,;)" and gap <= 1:
                    gap = 0
                line += " " * max(gap, 1 if gap else 0)
            prev_end = w["x"] + w["w"]
            line += w["t"]
        out.append(line.rstrip())
    return fix_braces("\n".join(out)) + "\n"


def write_outputs(text, base):
    base.with_suffix(".txt").write_text(text, encoding="utf-8")
    base.with_suffix(".html").write_text(
        '<!doctype html><meta charset="utf-8"><title>OCR</title>'
        '<pre style="font-family:\'Courier New\',Courier,monospace;font-size:14px">'
        f"{html.escape(text)}</pre>", encoding="utf-8")
    written = [".txt", ".html"]
    try:
        from docx import Document
        from docx.shared import Pt
        doc = Document()
        st = doc.styles["Normal"]
        st.font.name, st.font.size = "Courier New", Pt(10)
        for ln in text.rstrip("\n").split("\n"):
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.add_run(ln).font.name = "Courier New"
        doc.save(base.with_suffix(".docx"))
        written.append(".docx")
    except ImportError:
        pass
    return [str(base.with_suffix(e)) for e in written]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("-o", "--out", help="output basename (default: image name)")
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--psm", type=int, default=6, help="Tesseract page mode (6=block, 4=columns, 11=sparse)")
    a = ap.parse_args()
    text = to_layout(read_words(load(a.image), a.lang, a.psm))
    sys.stdout.write(text)
    base = Path(a.out) if a.out else Path(a.image).with_suffix("")
    print("\nSaved:", ", ".join(write_outputs(text, base)), file=sys.stderr)


if __name__ == "__main__":
    main()
