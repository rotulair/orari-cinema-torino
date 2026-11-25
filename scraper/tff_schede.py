"""Schede dei film del Torino Film Festival lette dal catalogo PDF: sinossi e fotogramma.

Nel catalogo ogni film ha un titolo (azzurro, corpo 21), un fotogramma e sotto la sinossi, in blocchi a due colonne
per pagina doppia. Con `pdftohtml -xml` si hanno testo e immagini con le coordinate: il fotogramma e la sinossi
di un film stanno nella stessa fascia verticale, e la sinossi e' il testo sotto l'immagine con la sua stessa larghezza.

Risultati (data/tff/):  schede.json  {"<chiave film>": {"titolo", "sinossi", "img", "pagina"}}   e   img/<chiave>.jpg
Si rigenera da solo quando cambia il PDF (impronta in schede.json -> "_pdf").
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

_FONT = re.compile(r'<fontspec id="(\d+)" size="(\d+)" family="[^"]*" color="(#[0-9a-fA-F]{6})"')
_PAGE = re.compile(r'<page number="(\d+)"[^>]*height="(\d+)" width="(\d+)">(.*?)</page>', re.S)
_IMG = re.compile(r'<image top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)" src="([^"]+)"')
_TEXT = re.compile(r'<text top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)" font="(\d+)">(.*?)</text>')


def slug(title: str) -> str:
    t = unicodedata.normalize("NFKD", title.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:70] or "film"


def _plain(s: str) -> str:
    return html.unescape(re.sub(r"</?[a-z]+>", "", s))


def _join(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln                  # "impoten-" + "te" -> "impotente"
        else:
            out = f"{out} {ln}".strip()
    out = re.sub(r"\s+", " ", out)
    return re.sub(r"\s+([.,;:!?»)])", r"\1", out)


def parse_catalog(xml: str) -> list[dict]:
    fonts = {int(i): (int(sz), col.lower()) for i, sz, col in _FONT.findall(xml)}
    title_fonts = {i for i, (sz, col) in fonts.items() if sz == 21 and col != "#ffffff"}
    out: list[dict] = []
    for num, ph, pw, body in _PAGE.findall(xml):
        pw, ph = int(pw), int(ph)
        imgs = [(int(t), int(l), int(w), int(h), src) for t, l, w, h, src in _IMG.findall(body)]
        imgs = [i for i in imgs if 250 <= i[2] <= 520 and 1.3 <= i[2] / max(i[3], 1) <= 2.2]
        texts = [(int(t), int(l), int(w), int(h), int(f), _plain(x)) for t, l, w, h, f, x in _TEXT.findall(body)]
        for top, left, w, h, src in imgs:
            half_left = left + w / 2 < pw / 2
            tl = [t for t in texts if t[4] in title_fonts and top - 10 <= t[0] <= top + 85
                  and ((t[1] + t[2] / 2) < pw / 2) == half_left and not (left - 5 <= t[1] <= left + w)]
            title = _join([t[5] for t in sorted(tl)])
            if not title:
                continue
            # prossima immagine sotto, nella stessa meta': delimita la sinossi
            below = [i[0] for i in imgs if i[0] > top + 40 and ((i[1] + i[2] / 2) < pw / 2) == half_left]
            limit = min(below) if below else ph
            syn = [t for t in texts if t[0] >= top + h and t[0] < limit - 4 and left - 6 <= t[1] <= left + w - 5
                   and t[4] not in title_fonts]
            syn.sort(key=lambda t: (round(t[0] / 4), t[1]))
            rows: list[list[str]] = []
            last = None
            for t in syn:
                if last is not None and abs(t[0] - last) <= 3 and rows:
                    rows[-1].append(t[5])
                else:
                    rows.append([t[5]])
                last = t[0]
            text = _join(["".join(r) if False else " ".join(r) for r in rows])
            out.append({"titolo": title, "sinossi": text, "src": src, "pagina": int(num), "w": w, "h": h})
    return out


def build(pdf: Path, outdir: Path, film_key, log=print) -> dict:
    """Legge il catalogo e scrive schede.json + img/. `film_key` e' la stessa funzione usata dal sito."""
    digest = hashlib.sha1(pdf.read_bytes()).hexdigest()
    outdir.mkdir(parents=True, exist_ok=True)
    idx = outdir / "schede.json"
    if idx.exists():
        try:
            old = json.loads(idx.read_text(encoding="utf-8"))
            if old.get("_pdf") == digest:
                return old
        except json.JSONDecodeError:
            pass
    tmp = Path(tempfile.mkdtemp())
    r = subprocess.run(["pdftohtml", "-xml", "-q", "-nodrm", str(pdf.resolve()), str(tmp / "p")],
                       capture_output=True, text=True, timeout=300, cwd=tmp)
    xml_path = tmp / "p.xml"
    if r.returncode != 0 or not xml_path.exists():
        raise RuntimeError(f"pdftohtml non ha letto il PDF: {r.stderr.strip()[:150]}")
    films = parse_catalog(xml_path.read_text(encoding="utf-8", errors="replace"))
    imgdir = outdir / "img"
    imgdir.mkdir(exist_ok=True)
    result: dict = {"_pdf": digest}
    for f in films:
        key = film_key(f["titolo"])
        src = tmp / Path(f["src"]).name
        if not src.exists():
            src = Path(f["src"])
        entry = {"titolo": f["titolo"], "sinossi": f["sinossi"], "pagina": f["pagina"]}
        if src.exists() and src.suffix.lower() in (".jpg", ".jpeg"):
            name = f"{slug(f['titolo'])}.jpg"
            shutil.copyfile(src, imgdir / name)
            entry["img"] = f"data/tff/img/{name}"
        result.setdefault(key, entry)
    idx.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"  TFF schede: {len(result) - 1} film dal catalogo")
    return result
