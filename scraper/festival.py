"""Torino Film Festival: proiezioni dal PDF ufficiale, modifiche manuali e registro delle variazioni.

Il programma del festival non compare (o compare in ritardo) sui siti dei cinema. Qui lo si legge dal PDF
ufficiale ("PROGRAMMA DI SALA": una pagina per giorno, colonne MASSIMO 1-3 e ROMANO 1-3) e lo si aggiunge agli
orari dei cinema con il marchio fest="TFF". Se il cinema pubblica poi la stessa proiezione sul proprio sito,
le due righe vengono fuse (nessun doppione) e quella del cinema riceve il marchio TFF.

File (cartella data/tff/, da modificare direttamente su GitHub):
  programma.pdf   il PDF ufficiale (se ne esce uno nuovo basta sostituirlo)
  modifiche.txt   correzioni giorno per giorno: annulla / sposta / aggiungi (vedi esempio nel file)
Risultati (scritti dallo scraper in data/):
  tff.json        programma letto (con le modifiche) all'ultimo giro
  tff_report.txt  sorgente usata, proiezioni per giorno, modifiche non applicate, ultime variazioni
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
          "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
CINEMAS = {"MASSIMO": "massimo", "ROMANO": "romano"}
FEST = "TFF"

_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
_DAY = re.compile(r"(?:LUNEDÌ|MARTEDÌ|MERCOLEDÌ|GIOVEDÌ|VENERDÌ|SABATO|DOMENICA)\s+(\d{1,2})\s+([A-ZÌ]+)", re.I)
_TIME = re.compile(r"^(\d{1,2})[.:](\d{2})(?:\s+PROIEZIONE UFFICIALE)?$")
_NOTE_START = re.compile(r"^(?:Sott\.|Eng\.|Il film sarà|Prima del|Dopo il|A seguire|Ingresso|Alla presenza|Incontro|In collaborazione)", re.I)
_SECTIONS = ("CONCORSO LUNGOMETRAGGI", "CONCORSO DOCUMENTARI", "CONCORSO CORTOMETRAGGI", "FUORI CONCORSO",
             "ZIBALDONE", "MARILYN MONROE")


def _read_words(xml: str) -> list[tuple[float, list[tuple[float, float, float, float, str]]]]:
    pages = []
    for m in _PAGE.finditer(xml):
        words = [(float(a), float(b), float(c), float(d), html.unescape(t))
                 for a, b, c, d, t in _WORD.findall(m.group(3))]
        pages.append((float(m.group(2)), words))
    return pages


def _lines(words: list[tuple[float, float, float, float, str]], tol: float = 4.0) -> list[str]:
    """Parole -> righe di testo (dall'alto in basso, da sinistra a destra)."""
    items = sorted(((w[1] + w[3]) / 2, w[0], w[4]) for w in words)
    rows: list[list[tuple[float, float, str]]] = []
    for yc, x, t in items:
        if rows and abs(rows[-1][-1][0] - yc) <= tol:
            rows[-1].append((yc, x, t))
        else:
            rows.append([(yc, x, t)])
    return [" ".join(t for _, _, t in sorted(r, key=lambda i: i[1])) for r in rows]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("/ ", "/")).strip()


def _meta(inner: str) -> dict:
    """'Gli spostati, John Huston, Usa, 1961, DCP, 125’' -> regia, anno, titolo alternativo."""
    toks = [t.strip() for t in inner.split(",") if t.strip()]
    year = None
    while toks:
        t = toks.pop()
        m = re.fullmatch(r"(\d{4})(?:\s*[-–]\s*\d{2,4})?", t)
        if m:
            year = int(m.group(1))
            break
    out: dict = {"anno": year}
    if year is None or not toks:
        return out
    toks.pop()                                   # paese
    if toks:
        out["regia"] = ", ".join(toks)
        if len(toks) >= 2:
            out["alt"] = toks[0]                 # a volte e' il titolo italiano, a volte il primo regista
    return out


def _entry(lines: list[str]) -> dict | None:
    lines = [l for l in lines if l.strip()]
    if not lines:
        return None
    sez = ""
    for s in _SECTIONS:
        if lines[0].upper().startswith(s):
            sez, lines = s, lines[1:]
            break
    title: list[str] = []
    i = 0
    while i < len(lines) and not lines[i].startswith("(") and not _NOTE_START.match(lines[i]):
        title.append(lines[i])
        i += 1
    meta_txt = ""
    if i < len(lines) and lines[i].startswith("("):
        depth, buf = 0, []
        while i < len(lines) and not (buf and _NOTE_START.match(lines[i])):
            buf.append(lines[i])
            depth += lines[i].count("(") - lines[i].count(")")
            i += 1
            if depth <= 0:
                break
        meta_txt = _clean(" ".join(buf)).strip()
        meta_txt = meta_txt[1:].rstrip(")").strip() if meta_txt.startswith("(") else meta_txt
    extra_title: list[str] = []
    if not meta_txt:       # eventi senza scheda film: titolo = righe in maiuscolo, il resto e' una nota
        keep: list[str] = []
        for n, l in enumerate(title):
            if l == l.upper() and len(keep) == n:
                keep.append(l)
        extra_title, title = title[len(keep):], keep
    notes = extra_title + [l for l in lines[i:]]
    sott = [n for n in notes if _NOTE_START.match(n) and n.lower().startswith(("sott", "eng"))]
    nota = _clean(" ".join(n for n in notes if n not in sott))
    film = _clean(" ".join(title))
    prog = re.match(r"^PROGRAMMA\s+(\d+)\b\s*(.*)$", film, re.I)
    if prog:               # programmi di cortometraggi: "PROGRAMMA 1 Titolo, Titolo, ..."
        film, nota = f"CORTOMETRAGGI - PROGRAMMA {prog.group(1)}", _clean("Cortometraggi: " + prog.group(2) + " " + nota)
    if not film:
        return None
    row = {"film": film, "sez": sez.title() if sez else "", "nota": nota[:240]}
    row.update(_meta(meta_txt) if meta_txt else {"anno": None})
    if prog or not meta_txt:
        row["nofilm"] = True          # programmi di corti, cerimonie: niente ricerca di locandina/scheda
    return row


def parse_program(xml: str, year: int) -> list[dict]:
    """Legge le pagine "programma di sala" del PDF (pdftotext -bbox) -> righe con cinema, sala, data, ora."""
    rows: list[dict] = []
    for page_h, words in _read_words(xml):
        # intestazioni di colonna: "MASSIMO 1", "ROMANO 2"...
        heads = []
        for w in words:
            if w[4] in CINEMAS:
                nxt = [v for v in words if abs(v[1] - w[1]) < 3 and 0 < v[0] - w[2] < 12 and re.fullmatch(r"\d", v[4])]
                if nxt:
                    heads.append((w[4], nxt[0][4], (w[0] + nxt[0][2]) / 2, max(w[3], nxt[0][3])))
        if len(heads) < 3:
            continue
        heads.sort(key=lambda h: h[2])
        top = max(h[3] for h in heads)
        day = None
        for ln in _lines([w for w in words if w[3] < top - 2]):
            m = _DAY.search(ln)
            if m and m.group(2).lower() in MONTHS:
                day = dt.date(year, MONTHS[m.group(2).lower()], int(m.group(1)))
        if not day:
            continue
        cuts = [(heads[i][2] + heads[i + 1][2]) / 2 for i in range(len(heads) - 1)]
        for idx, (cin, room, _, _) in enumerate(heads):
            lo = cuts[idx - 1] if idx else -1.0
            hi = cuts[idx] if idx < len(cuts) else 1e9
            col = [w for w in words if lo <= (w[0] + w[2]) / 2 < hi and w[1] > top and w[3] < page_h - 32]
            blocks: list[list[str]] = []
            times: list[str] = []
            for ln in _lines(col):
                m = _TIME.match(ln.strip())
                if m:
                    times.append(f"{int(m.group(1)):02d}:{m.group(2)}")
                    blocks.append([])
                elif blocks:
                    blocks[-1].append(ln.strip())
            for hhmm, blk in zip(times, blocks):
                e = _entry(blk)
                if e:
                    rows.append({"cinema": CINEMAS[cin], "room": room, "date": day.isoformat(), "time": hhmm,
                                 "tag": "", "fest": FEST, **e})
    known: dict[str, dict] = {}
    for r in rows:
        if r.get("regia") or r.get("anno"):
            known.setdefault(r["film"], r)
    for r in rows:                      # le repliche spesso riportano solo il titolo: regia e anno dalla prima scheda
        k = known.get(r["film"])
        if k and k is not r:
            for f in ("regia", "anno", "alt"):
                if not r.get(f) and k.get(f):
                    r[f] = k[f]
    return rows


# ------------------------------------------------------------------ PDF
def pdf_to_bbox(path: Path) -> str:
    r = subprocess.run(["pdftotext", "-bbox", str(path), "-"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or "<word" not in r.stdout:
        raise RuntimeError(f"pdftotext non ha letto {path}: {r.stderr.strip()[:120]}")
    return r.stdout


def download_pdf(url: str) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cinema-torino)"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("la risposta non e' un PDF")
    f = Path(tempfile.mkdtemp()) / "tff.pdf"
    f.write_bytes(data)
    return f


# ------------------------------------------------------------------ modifiche manuali
_WHERE = r"(?P<{p}cin>massimo|romano)\s*(?P<{p}room>\d)"
_MOD_DATE = r"(?P<d>\d{1,2})/(?P<m>\d{1,2})"
_MOD_TIME = r"(?P<h>\d{1,2})[.:](?P<min>\d{2})"
_RE_CANCEL = re.compile(rf"^(?:annulla|cancella|togli)\s+{_MOD_DATE}\s+{_MOD_TIME}\s+{_WHERE.format(p='')}\s*$", re.I)
_RE_MOVE = re.compile(rf"^sposta\s+{_MOD_DATE}\s+{_MOD_TIME}\s+{_WHERE.format(p='')}\s*(?:->|→|=>)\s*"
                      rf"(?:(?P<nd>\d{{1,2}})/(?P<nm>\d{{1,2}})\s+)?(?P<nh>\d{{1,2}})[.:](?P<nmin>\d{{2}})"
                      rf"(?:\s+{_WHERE.format(p='n')})?\s*$", re.I)
_RE_ADD = re.compile(rf"^(?:aggiungi|nuovo)\s+{_MOD_DATE}\s+{_MOD_TIME}\s+{_WHERE.format(p='')}\s*\|\s*(?P<rest>.+)$", re.I)

MODIFICHE_ESEMPIO = """# Modifiche al programma del Torino Film Festival, giorno per giorno.
# Una riga per modifica. Le righe che iniziano con # sono commenti. Orari come 21.30 oppure 21:30.
# Si applicano sopra il PDF a ogni aggiornamento; quando le correzioni sono già nel nuovo PDF si possono togliere.
#
#   annulla 27/11 21.00 Romano 2
#   sposta 27/11 21.00 Romano 2 -> 21.30
#   sposta 27/11 21.00 Romano 2 -> 28/11 18.00 Massimo 1
#   aggiungi 28/11 18.00 Massimo 3 | TITOLO DEL FILM | Nome del regista | nota facoltativa
"""


def apply_mods(rows: list[dict], text: str, year: int) -> tuple[list[dict], list[str], list[str]]:
    """Applica annulla/sposta/aggiungi. Restituisce (righe, righe applicate, righe NON applicate con il motivo)."""
    done: list[str] = []
    bad: list[str] = []

    def key(m, p=""):
        return (f"{year}-{int(m.group('m')):02d}-{int(m.group('d')):02d}",
                f"{int(m.group('h')):02d}:{m.group('min')}", CINEMAS[m.group(p + 'cin').upper()], m.group(p + "room"))

    def find(k):
        return next((r for r in rows if (r["date"], r["time"], r["cinema"], r["room"]) == k), None)

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if m := _RE_CANCEL.match(line):
            r = find(key(m))
            if r:
                rows.remove(r)
                done.append(f"{line}  ({r['film']})")
            else:
                bad.append(f"{line}  -> nessuna proiezione a quell'ora in quella sala")
        elif m := _RE_MOVE.match(line):
            r = find(key(m))
            if not r:
                bad.append(f"{line}  -> nessuna proiezione a quell'ora in quella sala")
                continue
            if m.group("nd"):
                r["date"] = f"{year}-{int(m.group('nm')):02d}-{int(m.group('nd')):02d}"
            r["time"] = f"{int(m.group('nh')):02d}:{m.group('nmin')}"
            if m.group("ncin"):
                r["cinema"], r["room"] = CINEMAS[m.group("ncin").upper()], m.group("nroom")
            done.append(f"{line}  ({r['film']})")
        elif m := _RE_ADD.match(line):
            d, t, cin, room = key(m)
            parts = [p.strip() for p in m.group("rest").split("|")]
            if not parts[0]:
                bad.append(f"{line}  -> manca il titolo")
                continue
            row = {"cinema": cin, "room": room, "date": d, "time": t, "tag": "", "fest": FEST, "sez": "",
                   "film": parts[0], "nota": parts[2][:240] if len(parts) > 2 else "", "anno": None}
            if len(parts) > 1 and parts[1]:
                row["regia"] = parts[1]
            rows.append(row)
            done.append(line)
        else:
            bad.append(f"{line}  -> riga non riconosciuta (usa annulla / sposta / aggiungi)")
    return rows, done, bad


# ------------------------------------------------------------------ unione con i cinema e registro
def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def merge(cinema_rows: list[dict], fest_rows: list[dict], today: str, same_film) -> tuple[list[dict], int]:
    """Aggiunge le proiezioni del festival agli orari dei cinema senza doppioni.
    Se il cinema ha gia' la stessa proiezione (stesso giorno, stessa ora +-10 minuti, titolo simile oppure stessa
    sala) tiene la riga del cinema e le aggiunge il marchio TFF."""
    merged = 0
    out = list(cinema_rows)
    by_day: dict[tuple, list[dict]] = {}
    for r in cinema_rows:
        by_day.setdefault((r["cinema"], r["date"]), []).append(r)
    for t in fest_rows:
        if t["date"] < today:
            continue
        hit = None
        for c in by_day.get((t["cinema"], t["date"]), []):
            if abs(_minutes(c["time"]) - _minutes(t["time"])) > 10:
                continue
            names = [t["film"]] + ([t["alt"]] if t.get("alt") else [])
            if any(same_film(c["film"], n) for n in names) or (c.get("room") and c["room"] == t["room"]):
                hit = c
                break
        if hit:
            hit["fest"] = FEST
            hit.setdefault("room", t["room"])
            if t.get("sez"):
                hit["sez"] = t["sez"]
            if t.get("nota") and not hit.get("nota"):
                hit["nota"] = t["nota"]
            merged += 1
        else:
            row = {k: v for k, v in t.items() if k != "alt" and v not in (None, "")}
            row.setdefault("tag", "")
            out.append(row)
            by_day.setdefault((row["cinema"], row["date"]), []).append(row)
    return out, merged


def _sig(r: dict) -> tuple:
    return (r["date"], r["time"], r["cinema"], r["room"], r["film"])


def diff(prev: list[dict], cur: list[dict], today: str) -> list[str]:
    a = {_sig(r): r for r in prev if r["date"] >= today}
    b = {_sig(r): r for r in cur if r["date"] >= today}
    notes = []

    def label(r):
        return f"{r['date'][8:]}/{r['date'][5:7]} {r['time']} {r['cinema'].title()} {r['room']}: {r['film']}"
    removed = [a[k] for k in a if k not in b]
    added = [b[k] for k in b if k not in a]
    moved = []
    for r in list(removed):                       # stesso film e stesso giorno ma ora/sala diversa = spostamento
        m = next((x for x in added if x["film"] == r["film"] and x["date"] == r["date"]), None)
        if m:
            removed.remove(r); added.remove(m); moved.append((r, m))
    for r, m in moved:
        notes.append(f"SPOSTATA  {label(r)}  ->  {m['time']} {m['cinema'].title()} {m['room']}")
    notes += [f"AGGIUNTA   {label(r)}" for r in added]
    notes += [f"TOLTA      {label(r)}" for r in removed]
    return notes


def load_rows(base: Path, year: int, urls: list[str] | None = None, log=print) -> tuple[list[dict], str]:
    """Legge il PDF: prima gli indirizzi online (se configurati), poi data/tff/programma.pdf."""
    candidates: list[tuple[str, object]] = [(u, u) for u in (urls or [])]
    local = base / "tff" / "programma.pdf"
    if local.exists():
        candidates.append((f"file {local.name}", local))
    errors = []
    for label, src in candidates:
        try:
            path = download_pdf(src) if isinstance(src, str) else src
            rows = parse_program(pdf_to_bbox(path), year)
            if len(rows) >= 10:
                return rows, label
            errors.append(f"{label}: lette solo {len(rows)} proiezioni")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    for e in errors:
        log(f"  TFF: {e}")
    return [], ("; ".join(errors) if errors else "nessun PDF configurato")


def build(base: Path, today: str, same_film, cfg: dict | None = None, log=print) -> tuple[list[dict], dict]:
    """Programma TFF pronto da fondere: PDF + modifiche. Restituisce (righe, info per il report)."""
    cfg = cfg or {}
    year = int(cfg.get("year") or today[:4])
    rows, source = load_rows(base, year, cfg.get("urls"), log)
    info = {"source": source, "applied": [], "unapplied": [], "changes": [], "from_cache": False}
    snap = base / "tff.json"
    prev: list[dict] = []
    if snap.exists():
        try:
            prev = json.loads(snap.read_text(encoding="utf-8")).get("rows", [])
        except json.JSONDecodeError:
            prev = []
    if not rows:
        rows = prev                                   # PDF non leggibile: restano i dati dell'ultimo giro
        info["from_cache"] = True
    mods = base / "tff" / "modifiche.txt"
    if mods.exists():
        rows, info["applied"], info["unapplied"] = apply_mods(rows, mods.read_text(encoding="utf-8"), year)
    rows = [r for r in rows if r["film"]]
    info["changes"] = diff(prev, rows, today) if prev and not info["from_cache"] else []
    return rows, info


def save(base: Path, rows: list[dict], info: dict, today: str, now_iso: str) -> None:
    """Scrive data/tff.json e data/tff_report.txt (con il registro delle ultime variazioni)."""
    (base / "tff.json").write_text(json.dumps({"checked": now_iso, "source": info["source"], "rows": rows},
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    old = ""
    rep = base / "tff_report.txt"
    if rep.exists():
        txt = rep.read_text(encoding="utf-8")
        old = txt.split("== Registro variazioni ==\n", 1)[1] if "== Registro variazioni ==\n" in txt else ""
    log_lines = [f"[{now_iso[:16].replace('T', ' ')}] {n}" for n in info["changes"]]
    history = "\n".join(log_lines + [l for l in old.splitlines() if l.strip()][:300 - len(log_lines)])
    per_day: dict[str, dict[str, int]] = {}
    for r in rows:
        per_day.setdefault(r["date"], {}).setdefault(f"{r['cinema'].title()} {r['room']}", 0)
        per_day[r["date"]][f"{r['cinema'].title()} {r['room']}"] += 1
    out = [f"Torino Film Festival - controllo del {now_iso[:16].replace('T', ' ')}",
           f"Fonte del programma: {info['source']}" + ("  (PDF non leggibile: usati i dati dell'ultimo giro)" if info["from_cache"] else ""),
           f"Proiezioni lette: {len(rows)}", "", "== Proiezioni per giorno =="]
    for d in sorted(per_day):
        tot = sum(per_day[d].values())
        out.append(f"{d[8:]}/{d[5:7]}: {tot:3d}  (" + ", ".join(f"{k} {v}" for k, v in sorted(per_day[d].items())) + ")")
    out += ["", "== Modifiche manuali applicate (data/tff/modifiche.txt) =="] + (info["applied"] or ["nessuna"])
    out += ["", "== Modifiche NON applicate =="] + (info["unapplied"] or ["nessuna"])
    out += ["", "== Registro variazioni ==", history]
    rep.write_text("\n".join(out) + "\n", encoding="utf-8")
