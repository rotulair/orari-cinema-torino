#!/usr/bin/env python3
"""Raccoglie la programmazione dei cinema di Torino e scrive data/showtimes.json.

Solo libreria standard (nessun pip install). Pensato per girare su GitHub Actions.

Uso:
    python scraper/scrape.py                 # aggiorna data/showtimes.json
    python scraper/scrape.py --only massaua  # un solo cinema (debug)
    python scraper/scrape.py --debug-dir debug   # salva l'HTML grezzo scaricato
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
import difflib
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Rome")
UA = "Mozilla/5.0 (compatible; CinemaTorinoPersonale/1.0; uso personale, pochi accessi al giorno)"
DELAY_SECONDS = 1.5  # pausa tra una richiesta e la successiva, per gentilezza verso i siti


# --------------------------------------------------------------------------- HTML

def fetch(url: str, retries: int = 3, timeout: int = 25) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download fallito: {url} ({last})")


_SKIP_TAGS = {"script", "style", "noscript"}


def events_of(html: str) -> list[tuple]:
    """Trasforma l'HTML in una lista piatta di eventi ('start'|'end'|'text', ...)."""

    class Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.ev: list[tuple] = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in _SKIP_TAGS:
                self.skip += 1
                return
            self.ev.append(("start", tag, dict(attrs)))

        def handle_endtag(self, tag):
            if tag in _SKIP_TAGS:
                self.skip = max(0, self.skip - 1)
                return
            self.ev.append(("end", tag, None))

        def handle_data(self, data):
            if self.skip:
                return
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.ev.append(("text", text, None))

    c = Collector()
    c.feed(html)
    c.close()
    return c.ev


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _valid_time(h: int, m: int) -> bool:
    return 0 <= h <= 29 and 0 <= m <= 59


def _norm_tag(tag: str) -> str:
    t = tag.strip()
    if re.search(r"(?i)(?<![\w])(v\.?o\.?s?|versione originale|lingua originale|originale|sottotitolat\w*)(?![\w])", t):
        return "VO"
    if t.upper() in {"2D", "DIGITAL"}:
        return ""
    return t


# ------------------------------------------------------------------ parser: Movieplayer
# Pagina di un cinema: ogni film e' un <h2>, seguito dagli orari "19.10" o "19.10 originale".
# Mostra solo la programmazione di OGGI.

_TIME_MP = re.compile(r"^(\d{1,2})[.:](\d{2})(?:\s+(.+))?$")


def parse_movieplayer(html: str, day: str) -> list[dict]:
    title: str | None = None
    in_h2 = False
    buf: list[str] = []
    out: list[dict] = []
    seen: set[tuple] = set()
    last_idx: int | None = None  # ultimo orario inserito, se subito prima dell'evento corrente

    for kind, a, _b in events_of(html):
        if kind == "start" and a == "h2":
            in_h2, buf, last_idx = True, [], None
        elif kind == "end" and a == "h2":
            if in_h2:
                title = clean(" ".join(buf)) or None
            in_h2 = False
        elif kind == "text":
            if in_h2:
                buf.append(a)
                continue
            if not title:
                continue
            m = _TIME_MP.match(a)
            if m and _valid_time(int(m.group(1)), int(m.group(2))):
                key = (title, f"{int(m.group(1)):02d}:{m.group(2)}")
                tag = _norm_tag(m.group(3) or "")
                if key in seen:
                    last_idx = None
                    continue
                seen.add(key)
                out.append({"film": title, "date": day, "time": key[1], "tag": tag})
                last_idx = len(out) - 1
            elif last_idx is not None and a.lower() in {"originale", "vo", "v.o."}:
                out[last_idx]["tag"] = "VO"
                last_idx = None
            else:
                last_idx = None
        elif kind in ("start", "end"):
            # un tag tra orario e "originale" non azzera il legame, ma un nuovo blocco si'
            if kind == "start" and a in {"h3", "h4", "li", "article"}:
                last_idx = None
    return out


# -------------------------------------------------------------- parser: 18tickets (Massaua)
# Home del cinema: titolo in <h5>/<h6>, poi per ogni giorno "Lunedì 16/11/2026" e link
# orario con href che contiene "#theater-init" (testo "16:50" o "19:15 CULT").

_DATE_18 = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_TIME_18 = re.compile(r"^(\d{1,2}):(\d{2})\s*(.*)$")


def parse_18tickets(html: str, day: str) -> list[dict]:
    title: str | None = None
    in_head = False
    head_buf: list[str] = []
    cur_date: str | None = None
    in_time_a = False
    a_buf: list[str] = []
    venue = ""
    out: list[dict] = []
    seen: set[tuple] = set()

    for kind, a, b in events_of(html):
        if kind == "start":
            if a in {"h5", "h6"}:
                in_head, head_buf = True, []
            elif a == "a" and "theater-init" in (b.get("href") or ""):
                in_time_a, a_buf = True, []
                venue = (urlparse(b.get("href") or "").hostname or "").lower()
        elif kind == "end":
            if a in {"h5", "h6"} and in_head:
                in_head = False
                title = clean(" ".join(head_buf)) or title
                cur_date = None
            elif a == "a" and in_time_a:
                in_time_a = False
                m = _TIME_18.match(clean(" ".join(a_buf)))
                if m and title and cur_date and _valid_time(int(m.group(1)), int(m.group(2))):
                    hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
                    key = (title, cur_date, hhmm, venue)
                    if key not in seen:
                        seen.add(key)
                        out.append({"film": title, "date": cur_date, "time": hhmm,
                                    "tag": _norm_tag(m.group(3)), "venue": venue})
        elif kind == "text":
            if in_head:
                head_buf.append(a)
            elif in_time_a:
                a_buf.append(a)
            else:
                d = _DATE_18.search(a)
                if d and title:
                    cur_date = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
    return out


# ------------------------------------------------------------------ utilita' per i siti ufficiali

MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
          "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}
_MONTH_RE = "|".join(MONTHS)
WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]  # indice = date.weekday()
_TIME_ANY = re.compile(r"(?<!\d)(\d{1,2})[.:](\d{2})(?!\d)")
_HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BOLD_TAGS = _HEAD_TAGS | {"strong", "b"}


def lines_of(html: str) -> list[tuple[str, str]]:
    """Testo del documento come lista di (riga, tag): tag e' il titolo/grassetto piu' interno
    aperto in quel punto ('' se nessuno). Ogni nodo di testo e' una riga."""
    stack: list[str] = []
    out: list[tuple[str, str]] = []
    for kind, a, _b in events_of(html):
        if kind == "start" and a in _BOLD_TAGS:
            stack.append(a)
        elif kind == "end" and a in _BOLD_TAGS and a in stack:
            while stack and stack.pop() != a:
                pass
        elif kind == "text":
            out.append((a, stack[-1] if stack else ""))
    return out


_BLOCK_TAGS = {"p", "div", "li", "br", "tr", "ul", "ol", "table", "section", "article", "blockquote",
               "td", "th", "header", "footer"} | _HEAD_TAGS


def block_segments(html: str) -> list[list[str]]:
    """Righe 'visive': i nodi di testo sono raggruppati finche' non c'e' un a-capo (br, p, div, li...).
    Un titolo evidenziato (span) resta un segmento a se'."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for kind, a, _b in events_of(html):
        if kind in ("start", "end") and a in _BLOCK_TAGS:
            if cur:
                blocks.append(cur)
                cur = []
        elif kind == "text":
            cur.append(a)
    if cur:
        blocks.append(cur)
    return blocks


def _today(day: str) -> dt.date:
    return dt.date.fromisoformat(day)


def infer_date(day: str, d: int, m: int, y: int | None = None) -> str | None:
    """Data da giorno/mese senza anno: l'anno e' quello piu' vicino a oggi."""
    today = _today(day)
    try:
        if y:
            return dt.date(y, m, d).isoformat()
        cand = dt.date(today.year, m, d)
    except ValueError:
        return None
    if (today - cand).days > 120:
        cand = dt.date(today.year + 1, m, d)
    elif (cand - today).days > 240:
        cand = dt.date(today.year - 1, m, d)
    return cand.isoformat()


def date_by_weekday(day: str, wd_abbr: str, d: int) -> str | None:
    """Giorno della settimana + numero del giorno (senza mese): cerca la data compatibile
    tra 4 giorni fa e 70 giorni avanti."""
    today = _today(day)
    wd = WEEKDAYS.index(wd_abbr[:3].lower().replace("gio", "gio"))
    for off in range(-4, 71):
        c = today + dt.timedelta(days=off)
        if c.day == d and c.weekday() == wd:
            return c.isoformat()
    return None


def times_in(text: str) -> list[str]:
    out = []
    for m in _TIME_ANY.finditer(text):
        h, mi = int(m.group(1)), int(m.group(2))
        if _valid_time(h, mi):
            out.append(f"{h:02d}:{mi:02d}")
    return out


def dates_it(text: str, day: str) -> list[str]:
    """Date in italiano libero: 'Lunedi 16 e Martedi 17 novembre', 'Da Giovedi 19 a Domenica 22
    novembre', '16-17-18 novembre', '16-18 novembre', '23 novembre 2026', '14/11/2026'."""
    t = text.lower()
    t = re.split(r"\bore\b|\bh\.", t)[0]
    n = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if n:
        r = infer_date(day, int(n.group(1)), int(n.group(2)), int(n.group(3)))
        return [r] if r else []
    tokens = [(m.start(), int(m.group(1))) for m in re.finditer(r"(?<![\d:.])(\d{1,2})(?![\d:.])", t)]
    months = [(m.start(), MONTHS[m.group(1)]) for m in re.finditer(rf"({_MONTH_RE})", t)]
    year = re.search(r"\b(20\d{2})\b", t)
    if not tokens or not months:
        return []
    tokens = [x for x in tokens if not (year and t[x[0]:x[0] + 4] == year.group(1))]
    resolved: list[tuple[int, int]] = []  # (giorno, mese)
    for pos, d in tokens:
        mo = next((m for p, m in months if p > pos), months[-1][1])
        resolved.append((d, mo))
    y = int(year.group(1)) if year else None
    is_range = bool(re.match(r"\s*(da|dal)\b", t)) or (
        len(tokens) == 2 and re.search(r"\d\s*[-–]\s*\d", t))
    dates: list[str] = []
    if is_range and len(resolved) >= 2:
        a = infer_date(day, resolved[0][0], resolved[0][1], y)
        b = infer_date(day, resolved[-1][0], resolved[-1][1], y)
        if a and b and a <= b and (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days <= 31:
            c = dt.date.fromisoformat(a)
            while c.isoformat() <= b:
                dates.append(c.isoformat())
                c += dt.timedelta(days=1)
            return dates
    for d, mo in resolved:
        r = infer_date(day, d, mo, y)
        if r:
            dates.append(r)
    return dates


_NUM_WORDS = {"uno": "1", "due": "2", "tre": "3", "quattro": "4", "cinque": "5", "sei": "6", "sette": "7",
              "otto": "8", "nove": "9", "dieci": "10"}


def room_short(text: str) -> str:
    """'SALA 1' / 'Sala Uno' -> '1'; altri nomi restano com'e' (senza la parola 'sala')."""
    t = re.sub(r"(?i)^\s*sala\s*", "", text).strip()
    return _NUM_WORDS.get(t.lower(), t)[:20]


def _add(out: list[dict], seen: set, film: str, date: str, hhmm: str, tag: str = "", room: str = "",
         regia: str = "") -> None:
    key = (film.lower(), date, hhmm)
    if film and key not in seen:
        seen.add(key)
        row = {"film": film, "date": date, "time": hhmm, "tag": tag}
        if room:
            row["room"] = room
        if regia:
            row["regia"] = regia
        out.append(row)


# ------------------------------------------------------------------ parser: Ideal Cityplex
# Home: <h?>TITOLO</h?>, poi per ogni giorno "Mercoledi 16/12" e righe "SALA 1, 15:00, INFINITY VISION".

_DAYNAME = r"(?:lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|sabato|domenica)"
_IDEAL_DAY = re.compile(rf"^{_DAYNAME}\s+(\d{{1,2}})/(\d{{1,2}})$", re.I)
_IDEAL_SHOW = re.compile(r"^([^,]+),\s*(\d{1,2}[:.]\d{2})(?:\s*,\s*(.+))?$")


_META = re.compile(r"(?i)^(regia|genere|durata|cast|anno|nazione|con)\b\s*:?")
_ROOM_ONLY = re.compile(r"(?i)^sala\s*\w+$")
_TIME_ONLY = re.compile(r"^\d{1,2}[:.]\d{2}$")


def parse_ideal(html: str, day: str) -> list[dict]:
    """Tollerante: orario sia in una riga sola ('SALA 1, 15:00, INFINITY VISION') sia spezzato in
    nodi separati ('SALA 1' / '15:00' / 'INFINITY VISION'). Titolo da un titolo HTML oppure, se non
    c'e', dal nodo che precede la prima etichetta 'Regia:/Genere:/Durata:' (etichette e valori
    possono essere nodi separati: 'Durata:' / "113'")."""
    title, cur, room = "", None, ""
    out: list[dict] = []
    seen: set = set()
    last: dict | None = None  # ultimo orario, in attesa dell'eventuale formato nel nodo seguente
    cand = ""                 # ultimo testo "libero" visto fuori dai metadati
    in_meta = skip_value = head_since = False
    regia, want_regia = "", False
    for text, tag in lines_of(html):
        text = text.strip().rstrip(",").strip()
        if not text:
            continue
        if tag in _HEAD_TAGS and not _IDEAL_DAY.match(text):
            if not text.lower().startswith(("film in programmazione", "prossimamente")):
                title, cur, room, last, head_since = clean(text), None, "", None, True
                in_meta = skip_value = False
                regia = ""
            continue
        if _META.match(text):
            if not in_meta and not head_since and cand:
                title, cur, room, last, regia = clean(cand), None, "", None, ""
            head_since, in_meta = False, True
            skip_value = text.endswith(":")      # etichetta sola: il valore e' il nodo dopo
            is_regia = text.lower().startswith("regia")
            if is_regia and not skip_value:
                regia = clean(text.split(":", 1)[1]) if ":" in text else ""
            want_regia = is_regia and skip_value
            continue
        if in_meta and skip_value:
            skip_value = False
            if want_regia:
                regia, want_regia = clean(text), False
            continue
        m = _IDEAL_DAY.match(text)
        if m:
            cur, room, last, in_meta = infer_date(day, int(m.group(1)), int(m.group(2))), "", None, False
            continue
        if in_meta:
            continue
        m = _IDEAL_SHOW.match(text)
        if m and title and cur:
            hhmm = times_in(m.group(2))
            if hhmm:
                _add(out, seen, title, cur, hhmm[0], _norm_tag(m.group(3) or ""), room_short(m.group(1)), regia)
            last = None
            continue
        if _ROOM_ONLY.match(text):
            room, last = room_short(text), None
            continue
        if _TIME_ONLY.match(text) and title and cur:
            hhmm = times_in(text)
            before = len(out)
            if hhmm:
                _add(out, seen, title, cur, hhmm[0], "", room, regia)
            last = out[-1] if len(out) > before else None
            continue
        if last is not None and len(text) <= 30 and not text.lower().startswith("scheda"):
            last["tag"] = _norm_tag(text)
            last = None
            continue
        last = None
        cand = text
    return out


# ------------------------------------------------------------------ parser: Cinema Massimo
# calendario-completo: <h2>Sala Uno</h2>, riga data in grassetto ("Da Giovedi 19 a Domenica 22
# novembre"), righe in grassetto "18.00/20.45 Titolo ...", note "sottotitolato" / "v.o. sott. it.".

_MASSIMO_SHOW = re.compile(r"^((?:\d{1,2}[.:]\d{2})(?:\s*[/,]\s*\d{1,2}[.:]\d{2})*)\s+(.+)$")


def parse_massimo(html: str, day: str) -> list[dict]:
    dates: list[str] = []
    out: list[dict] = []
    seen: set = set()
    last: list[dict] = []
    room = ""
    for text, tag in lines_of(html):
        if tag == "h2" and re.match(r"(?i)^sala\b", text):
            room, dates, last = room_short(text), [], []
            continue
        if re.match(rf"^(da\s+|dal\s+)?{_DAYNAME}\b", text, re.I) and re.search(_MONTH_RE, text, re.I):
            dates = dates_it(text, day)
            last = []
            continue
        m = _MASSIMO_SHOW.match(text)
        if m and dates:
            title = clean(re.split(r"\s+[-–(]\s+|\s{2,}", m.group(2))[0]).strip(" -–,.")
            last = []
            for d in dates:
                for hhmm in times_in(m.group(1)):
                    before = len(out)
                    _add(out, seen, title, d, hhmm, room=room)
                    if len(out) > before:
                        last.append(out[-1])
            continue
        if last and re.search(r"(?i)v\.?\s?o\.?\b|sottotitolat", text):
            for r in last:
                r["tag"] = "VO"
    return out


# ------------------------------------------------------------------ parser: Movie Planet Lux
# printProg.php: intestazione "DAL 12 AL 18 NOVEMBRE", poi per film il titolo e righe
# "Giovedi: 17:00 19:30".

_DAYLINE = re.compile(rf"^({_DAYNAME})\s*:?\s*(.*)$", re.I)
_WD_IDX = {"lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6}


def parse_movieplanet(html: str, day: str) -> list[dict]:
    lines = [t for t, _ in lines_of(html)]
    week: dict[int, str] = {}
    for t in lines:
        m = re.search(rf"dal\s+(\d{{1,2}})(?:\s+({_MONTH_RE}))?\s+al\s+(\d{{1,2}})\s+({_MONTH_RE})", t, re.I)
        if m:
            mo2 = MONTHS[m.group(4).lower()]
            mo1 = MONTHS[m.group(2).lower()] if m.group(2) else mo2
            a = infer_date(day, int(m.group(1)), mo1)
            b = infer_date(day, int(m.group(3)), mo2)
            if a and b:
                c = dt.date.fromisoformat(a)
                while c.isoformat() <= b:
                    week[c.weekday()] = c.isoformat()
                    c += dt.timedelta(days=1)
            break
    if not week:
        return []
    out: list[dict] = []
    seen: set = set()
    title = pending = ""
    cur: str | None = None
    for t in lines:
        m = _DAYLINE.match(t)
        if m:
            if pending:
                title, pending = pending, ""
            cur = week.get(_WD_IDX[m.group(1).lower()[:3]])
            for hhmm in times_in(m.group(2)):
                if title and cur:
                    _add(out, seen, title, cur, hhmm)
            continue
        if _TIME_ANY.fullmatch(t) or re.fullmatch(r"(?:\d{1,2}[.:]\d{2}\s*)+", t):
            if title and cur:
                for hhmm in times_in(t):
                    _add(out, seen, title, cur, hhmm)
            continue
        if 2 < len(t) <= 90 and not is_junk_title(t) and not re.search(r"(?i)dal\s+\d|www\.|©|stampa|programmazione|orari", t):
            pending = clean(t)
            cur = None
    return out


# ------------------------------------------------------------------ parser: Esedra
# Home: titolo in un titolo/grassetto, poi "Sabato 14/11/2026" e "h. 16:00 - 21:15".

def parse_esedra(html: str, day: str) -> list[dict]:
    title, cur = "", None
    out: list[dict] = []
    seen: set = set()
    for text, tag in lines_of(html):
        d = re.search(r"\d{1,2}/\d{1,2}/\d{4}", text)
        if d:
            found = dates_it(d.group(0), day)
            cur = found[0] if found else None
            for hhmm in times_in(text[d.end():]):
                if title and cur:
                    _add(out, seen, title, cur, hhmm)
            continue
        if cur and title and re.match(r"(?i)^(h\.?|ore)\s*\d", text):
            for hhmm in times_in(text):
                _add(out, seen, title, cur, hhmm)
            continue
        if tag in _HEAD_TAGS and 2 < len(text) <= 100:
            title, cur = clean(text), None
    return out


# ------------------------------------------------------------------ parser: Baretti
# Righe "Lunedi 16 novembre 2026, ore 21.15: TITOLO di Regista (VOS)".

_BARETTI = re.compile(
    rf"{_DAYNAME}\s+(\d{{1,2}})\s+({_MONTH_RE})(?:\s+(\d{{4}}))?\s*,?\s*ore\s*(\d{{1,2}})(?:[.:](\d{{2}}))?\s*:\s*", re.I)


def parse_baretti(html: str, day: str) -> list[dict]:
    """Righe 'Lunedi 16 novembre 2026, ore 21.15: TITOLO di Regista (VOS) [ Rassegna ]'.
    Il titolo e' di solito evidenziato (un nodo a se'); altrimenti si taglia prima di ' di Nome'.
    L'ora puo' essere senza minuti ('ore 21:')."""
    out: list[dict] = []
    seen: set = set()
    for segs in block_segments(html):
        full = clean(" ".join(segs))
        m = _BARETTI.search(full)
        if not m:
            continue
        date = infer_date(day, int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)) if m.group(3) else None)
        h, mi = int(m.group(4)), int(m.group(5) or 0)
        if not date or not _valid_time(h, mi):
            continue
        rest = full[m.end():]
        # titolo = primo segmento dopo il prefisso "... ore 21.15:" (se e' un nodo separato)
        pos, title = 0, ""
        for seg in segs:
            start = full.find(seg, pos)
            pos = start + len(seg)
            if start >= m.end() - 1 and seg.strip(" :"):
                title = seg.strip(" :")
                break
        if not title:
            title = re.split(r"\s+(?:di|con)\s+(?=[A-ZÀ-Ý])", re.sub(r"\([^)]*\)", "", rest), maxsplit=1)[0]
        title = clean(re.sub(r"\([^)]*\)", "", title)).strip(" .,-–:")
        tag = "VO" if re.search(r"\((?:v\.?o\.?s?|versione originale)[^)]*\)", rest, re.I) else ""
        after = rest[rest.find(title) + len(title):] if title in rest else ""
        dm = re.match(r"\s*di\s+([^\[\](),]+)", after)
        if title:
            _add(out, seen, title, date, f"{h:02d}:{mi:02d}", tag, regia=clean(dm.group(1)) if dm else "")
    return out


# ------------------------------------------------------------------ parser: Agnelli
# Titolo in un titolo/grassetto, poi un titolo H2 di programma: "Domenica 15 novembre ore 15:30 e 21:00",
# "16-17-18 novembre ore 19:00".

def parse_agnelli(html: str, day: str) -> list[dict]:
    title = ""
    out: list[dict] = []
    seen: set = set()
    for text, tag in lines_of(html):
        if re.search(r"(?i)\bore\b\s*\d", text) and re.search(_MONTH_RE, text, re.I):
            dates = dates_it(text, day)
            after = re.split(r"(?i)\bore\b", text, maxsplit=1)[1]
            for d in dates:
                for hhmm in times_in(after):
                    _add(out, seen, title, d, hhmm, "VO" if re.search(r"(?i)\bv\.?o\.?\b|originale", text) else "")
            continue
        if tag and 2 < len(text) <= 100 and not re.search(r"(?i)^(menu|home|cinema|contatti|programm)", text):
            title = clean(text)
    return out


# ------------------------------------------------------------------ parser: Centrale Arthouse (WordPress)
# Post settimanale: titolo del film, poi righe "GIOV 12 – 21:00", "SAB 14 – 13:15 e 18:30".

_CENTRALE_DAY = re.compile(r"^(lun|mar|mer|gio|ven|sab|dom)\w*\.?\s+(\d{1,2})\s*[–—-]\s*(.+)$", re.I)
_CENTRALE_YEAR = re.compile(r"^\(.*\b((?:19|20)\d{2})\b.*\)$")


def _centrale_times(rest: str) -> list[tuple[str, str]]:
    """'13:30 (doppiato) – 18:00 e 20:45 (v.o. sott. it.)' -> [(13:30, ITA), (18:00, VO), (20:45, VO)].
    La nota tra parentesi vale per gli orari che la precedono."""
    out: list[tuple[str, str]] = []
    pending: list[str] = []
    for tok in re.finditer(r"(\d{1,2})[:.](\d{2})|\(([^)]*)\)", rest):
        if tok.group(3) is None:
            if _valid_time(int(tok.group(1)), int(tok.group(2))):
                pending.append(f"{int(tok.group(1)):02d}:{tok.group(2)}")
            continue
        note = tok.group(3).lower()
        tag = "VO" if re.search(r"v\.?\s?o\b|originale", note) else "ITA" if "doppiat" in note else ""
        out += [(t, tag) for t in pending]
        pending = []
    out += [(t, "") for t in pending]
    return out


def _paragraphs(html: str) -> list[list[str]]:
    """Righe di testo di ogni paragrafo (<br> = a capo) del solo contenuto del post: niente barra laterale."""
    i = html.find('class="entry-content"')
    if i >= 0:
        j = html.find("</article>", i)
        html = html[i:j if j > 0 else len(html)]
    html = re.sub(r"(?is)<(script|style|figure)\b.*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    pars = []
    for m in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p>", html):
        txt = html_unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        lines = [clean(x) for x in txt.splitlines() if clean(x)]
        if lines:
            pars.append(lines)
    return pars


def parse_centrale(html: str, day: str) -> list[dict]:
    """Post "Programmazione": per ogni film un paragrafo con titolo / (titolo originale) / di REGISTA / (Paese anno, durata)
    e un paragrafo con le righe "GIOV 19 – 18:00 e 20:45 (v.o. sott. it.)". Si ignorano barra laterale e avvisi."""
    out: list[dict] = []
    seen: set = set()
    title = regia = ""
    anno = 0
    for lines in _paragraphs(html):
        has_days = any(_CENTRALE_DAY.match(l) for l in lines)
        di = next((l[3:].strip() for l in lines if re.match(r"(?i)^di\s+\S", l)), "")
        yr = next((int(m.group(1)) for l in lines for m in [_CENTRALE_YEAR.match(l)] if m), 0)
        if (di or yr) and not lines[0].startswith("(") and not _CENTRALE_DAY.match(lines[0]):
            cand = lines[0]
            if not is_junk_title(cand) and len(cand) <= 120:
                title, regia, anno = cand, di, yr
            if not has_days:
                continue
        if not has_days or not title:
            continue
        for l in lines:
            m = _CENTRALE_DAY.match(l)
            if not m:
                continue
            date = date_by_weekday(day, m.group(1).lower(), int(m.group(2)))
            if not date:
                continue
            for hhmm, tag in _centrale_times(m.group(3)):
                n0 = len(out)
                _add(out, seen, title, date, hhmm, tag)
                if len(out) > n0:
                    if regia:
                        out[-1]["regia"] = regia
                    if anno:
                        out[-1]["anno"] = anno
    return out


# ------------------------------------------------------------------ parser: Circuito Gran Torino (Greenwich + Classico)
# Il sito pubblica la programmazione settimanale come PDF (una tabella: un blocco per giorno, per Greenwich
# quattro colonne = sale). La home contiene i link ai PDF; ogni PDF si legge con le coordinate delle parole
# (pdftotext -bbox) e le righe escono con "venue": "greenwich" / "classico" (filtrato dalla configurazione).

_BBOX_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="[\d.]+">([^<]*)</word>')
_GT_DAY = re.compile(rf"^{_DAYNAME}$", re.I)
_GT_TIME = re.compile(r"^(\d{1,2})[.:](\d{2})$")


def fetch_pdf_bbox(url: str) -> str:
    """Scarica un PDF e restituisce il testo con coordinate (pdftotext -bbox, pacchetto poppler-utils)."""
    import subprocess
    import tempfile
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = resp.read()
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "p.pdf"
        f.write_bytes(data)
        r = subprocess.run(["pdftotext", "-bbox", str(f), "-"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or "<word" not in r.stdout:
        raise RuntimeError(f"pdftotext non ha letto {url}: {r.stderr.strip()[:120]}")
    return r.stdout


PDF_BBOX = fetch_pdf_bbox   # sostituibile nei test


def parse_grantorino_pdf(xml: str, day: str, venue: str) -> list[dict]:
    pages = xml.split("<page ")[1:] or [xml]
    words: list[tuple[float, float, str]] = []   # (x, y, testo), y continuo tra pagine
    off = 0.0
    for pg in pages:
        ys = [0.0]
        for m in _BBOX_WORD.finditer(pg):
            x, y, t = float(m.group(1)), float(m.group(2)) + off, html_unescape(m.group(4))
            words.append((x, y, t)); ys.append(y)
        off = max(ys) + 100
    if not words:
        return []

    # intervallo date dal titolo: "PROGRAMMAZIONE DAL 19 AL 25 NOVEMBRE"
    head = " ".join(t for _, _, t in sorted(words, key=lambda w: (round(w[1] / 4), w[0]))[:80])
    m = re.search(rf"(?i)\bdal\s+(\d{{1,2}})(?:\s+({_MONTH_RE}))?\s+al\s+(\d{{1,2}})\s+({_MONTH_RE})", head)
    if not m:
        raise RuntimeError("intervallo di date non trovato nel PDF")
    d1, d2, mo2 = int(m.group(1)), int(m.group(3)), MONTHS[m.group(4).lower()]
    mo1 = MONTHS[m.group(2).lower()] if m.group(2) else (mo2 if d1 <= d2 else (mo2 - 2) % 12 + 1)
    start = infer_date(day, d1, mo1)
    end = infer_date(day, d2, mo2)
    if not start or not end:
        raise RuntimeError("date del PDF non valide")
    sd, ed = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if ed < sd:
        ed = dt.date(ed.year + 1, ed.month, ed.day)
    span = [sd + dt.timedelta(days=i) for i in range((ed - sd).days + 1)]

    # giorni (nome del giorno a sinistra); la data viene dall'intervallo, non dal testo (nel PDF ci sono refusi)
    labels = sorted([(y, x, t) for x, y, t in words if _GT_DAY.match(t)])
    if not labels:
        return []
    days: list[tuple[float, dt.date]] = []
    for y, _x, t in labels:
        wd = WEEKDAYS.index(t[:3].lower())
        cand = [c for c in span if c.weekday() == wd]
        if cand:
            days.append((y, cand[0]))
    bounds = [(-1e9 if i == 0 else (days[i - 1][0] + days[i][0]) / 2) for i in range(len(days))] + [1e9]

    times = [(x, y, f"{int(mm.group(1)):02d}:{mm.group(2)}") for x, y, t in words
             for mm in [_GT_TIME.match(t)] if mm and _valid_time(int(mm.group(1)), int(mm.group(2)))]
    if not times:
        return []
    # colonne = gruppi di orari con lo stesso x (una colonna per sala)
    edges: list[float] = []
    for x in sorted({round(t[0]) for t in times}):
        if not edges or x - edges[-1] > 15:
            edges.append(float(x))
    def col_of(x: float) -> int | None:
        c = [i for i, e in enumerate(edges) if e <= x + 3]
        return c[-1] if c else None

    # numero di sala dall'intestazione (la prima riga "SALA n" di ogni colonna)
    rooms: dict[int, tuple[float, str]] = {}
    for i, (x, y, t) in enumerate(words):
        if t.upper() == "SALA" and i + 1 < len(words) and re.fullmatch(r"\d+", words[i + 1][2]):
            c = col_of(x)
            if c is not None and (c not in rooms or y < rooms[c][0]):
                rooms[c] = (y, words[i + 1][2])
    multi = len(edges) > 1

    out: list[dict] = []
    seen: set = set()
    for bi, (_dy, date) in enumerate(days):
        lo, hi = bounds[bi], bounds[bi + 1]
        for c in range(len(edges)):
            ts = sorted((y, hhmm) for x, y, hhmm in times if lo <= y < hi and col_of(x) == c)
            if not ts:
                continue
            # righe di testo della colonna (parole non-orario con la stessa y)
            cells = sorted((y, x, t) for x, y, t in words
                           if lo <= y < hi and col_of(x) == c and not _GT_TIME.match(t) and not _GT_DAY.match(t)
                           and not re.fullmatch(r"\d{1,2}/\d{1,3}", t) and t.upper() != "SALA"
                           and not (t.isdigit() and len(t) == 1))
            lines: list[list] = []
            for y, x, t in cells:
                if lines and abs(lines[-1][0] - y) < 2.0:
                    lines[-1][1].append(t)
                else:
                    lines.append([y, [t]])
            parts: dict[int, dict] = {i: {"title": [], "vo": False} for i in range(len(ts))}
            for ly, toks in lines:
                text = " ".join(toks)
                near = min(range(len(ts)), key=lambda i: abs(ts[i][0] - ly))
                if abs(ts[near][0] - ly) > 20:
                    continue
                if text.startswith("(") or re.search(r"(?i)versione originale|\bsott\.", text):
                    parts[near]["vo"] = True
                else:
                    parts[near]["title"].append(text)
            for i, (_y, hhmm) in enumerate(ts):
                title = clean(" ".join(parts[i]["title"]))
                if not title:
                    continue
                n0 = len(out)
                _add(out, seen, title, date.isoformat(), hhmm, "VO" if parts[i]["vo"] else "",
                     rooms[c][1] if multi and c in rooms else "")
                if len(out) > n0:
                    out[-1]["venue"] = venue
                    out[-1]["manual"] = True      # PDF scritto a mano: i titoli vanno controllati con le altre fonti
    return out


def html_unescape(t: str) -> str:
    import html as _h
    return _h.unescape(t)


def parse_grantorino(html: str, day: str) -> list[dict]:
    """Home di circuitograntorino.com: trova i PDF di Greenwich e Classico e li legge."""
    out: list[dict] = []
    errors: list[str] = []
    seen_urls: set[str] = set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        blob = (href + " " + text).lower()
        venue = "greenwich" if "greenwich" in blob else "classico" if "classico" in blob else ""
        if not venue or href in seen_urls:
            continue
        seen_urls.add(href)
        try:
            out.extend(parse_grantorino_pdf(PDF_BBOX(href), day, venue))
        except Exception as exc:  # noqa: BLE001 - un PDF rotto non blocca l'altro
            errors.append(f"{venue}: {exc}")
    if errors and not out:
        raise RuntimeError("; ".join(errors))
    return out


PARSERS = {"movieplayer": parse_movieplayer, "18tickets": parse_18tickets, "ideal": parse_ideal,
           "massimo": parse_massimo, "movieplanet": parse_movieplanet, "esedra": parse_esedra,
           "baretti": parse_baretti, "agnelli": parse_agnelli, "centrale": parse_centrale,
           "grantorino": parse_grantorino}


# --------------------------------------------------------------------------- titoli duplicati
# Cinemi diversi scrivono lo stesso film in modo diverso ("Titolo [2026]", "TITOLO (4K)", "Il titolo").
# Prima di salvare, i titoli vengono confrontati e riuniti sotto un unico nome.

_ARTICLES = {"il", "lo", "la", "l", "i", "gli", "le", "un", "uno", "una", "the"}


_JUNK = re.compile(r"(?i)^(n\.?\s?/?\s?d\.?|n\.?a\.?|nd|tba|tbd|-+|\d{2,3}['’′]?)$")


_TIME_TITLE = re.compile(r"(?i)^(?:ore\s*)?\d{1,2}[:.]\d{2}(?:\s*(?:e|-|–|/|,|&)\s*\d{1,2}[:.]\d{2})*$")


def is_junk_title(t: str) -> bool:
    """Segnaposto o valori scambiati per titoli: 'n.d.', 'N/D', durate come 113', 'Sala 3'..."""
    t = (t or "").strip()
    if not re.search(r"[A-Za-zÀ-ÿ0-9]{2,}", t) or _JUNK.match(t):
        return True
    if _TIME_TITLE.match(t):
        return True        # "21:00", "ore 16.00 e 21:00": un orario scambiato per titolo
    return t.lower().startswith(("sala ", "in programmazione", "prossimamente", "film in programma"))


_VO_SUFFIX = re.compile(r"\s*[-–—(]\s*(?:v\.?\s?o\.?s?|versione originale|lingua originale|sottotitolat\w*[^)]*)\s*\)?\s*$", re.I)
_EDITION = re.compile(r"\s*[-–—]\s*[^-–—]*\b(?:anniversar\w*|restaurat\w*|rimasterizzat\w*|remaster\w*|edition|special|"
                      r"director'?s cut)\b.*$", re.I)


def strip_noise(title: str) -> str:
    """'Titolo - V. O.' -> 'Titolo'; 'Titolo 4K – WB 100th Anniversary (...)' -> 'Titolo'."""
    t = _VO_SUFFIX.sub("", title)
    t = _EDITION.sub("", t)
    t = re.sub(r"\s+4k\b", "", t, flags=re.I)
    return t.strip()


def compare_key(title: str) -> str:
    title = strip_noise(title)
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title.lower())
    t = re.sub(r"\b(4k|ried|rid|ridistribuzione|restaurato|versione restaurata)\b", " ", t)
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", t).split()]
    while len(words) > 1 and words[0] in _ARTICLES:
        words.pop(0)
    return " ".join(words)


def display_title(title: str) -> str:
    """Toglie anni, formati, edizioni speciali e '- V.O.': 'Titolo [2026]' -> 'Titolo'."""
    t = re.sub(r"\s*\[[^\]]*\]", "", strip_noise(title))
    t = re.sub(r"\s*\((?:\d{4}|4k|ried\.?|ridistribuzione)\)", "", t, flags=re.I)
    return clean(t).strip(" -–")


def _same_film(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 6:
        return False
    if [w for w in a.split() if w.isdigit()] != [w for w in b.split() if w.isdigit()]:
        return False  # "Toy Story 2" != "Toy Story 3"
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.93


def _subtitle_of(a: str, b: str) -> bool:
    """'minotaur' / 'minotaur nel labirinto del potere': un titolo e' l'inizio dell'altro seguito da un
    sottotitolo di almeno due parole (e senza numeri diversi)."""
    ta, tb = a.split(), b.split()
    if len(ta) > len(tb):
        ta, tb = tb, ta
    if len(" ".join(ta)) < 6 or len(tb) - len(ta) < 2 or tb[:len(ta)] != ta:
        return False
    return [w for w in tb[len(ta):] if w.isdigit()] == []


def snap_manual_titles(rows: list[dict]) -> list[tuple[str, str]]:
    """Controllo incrociato dei titoli dei PDF scritti a mano: se somiglia molto (>= 0.85) a un titolo
    letto da un'altra fonte, e' un refuso e si usa quello. Rimuove poi il contrassegno 'manual'."""
    auto = Counter(r["film"] for r in rows if not r.get("manual"))
    akeys = {n: compare_key(n) for n in auto}
    fixed: dict[str, str] = {}
    log: list[tuple[str, str]] = []
    for r in rows:
        if not r.pop("manual", False):
            continue
        t = r["film"]
        if t in fixed:
            r["film"] = fixed[t]
            continue
        k = compare_key(t)
        if t in auto or k in akeys.values():
            continue
        best, score = None, 0.0
        for n, kn in akeys.items():
            if min(len(k), len(kn)) < 6 or [w for w in k.split() if w.isdigit()] != [w for w in kn.split() if w.isdigit()]:
                continue
            ta, tb = k.split(), kn.split()
            sc = difflib.SequenceMatcher(None, k, kn).ratio()
            if len(ta) != len(tb):                       # titolo breve contro titolo con sottotitolo
                short, long_ = (ta, tb) if len(ta) < len(tb) else (tb, ta)
                sc = max(sc, difflib.SequenceMatcher(None, " ".join(short), " ".join(long_[:len(short)])).ratio())
            if sc > score or (sc == score and best and auto[n] > auto[best]):
                best, score = n, sc
        if best and score >= 0.85:
            fixed[t] = best
            r["film"] = best
            log.append((t, best))
    return sorted(set(log))


def unify_titles(rows: list[dict]) -> list[tuple[str, str]]:
    """Riscrive r['film'] col nome canonico di ogni gruppo. Restituisce le unificazioni fatte."""
    keys = {r["film"]: compare_key(r["film"]) for r in rows}
    where: dict[str, set] = {}
    for r in rows:
        where.setdefault(r["film"], set()).add((r.get("cinema"), r.get("date")))
    names = sorted(keys, key=lambda n: (keys[n], n))
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if find(a) == find(b):
                continue
            if _same_film(keys[a], keys[b]) or (_subtitle_of(keys[a], keys[b]) and not (where[a] & where[b])):
                parent[find(b)] = find(a)

    counts = Counter(r["film"] for r in rows)
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)

    canon: dict[str, str] = {}
    merged: list[tuple[str, str]] = []
    for members in groups.values():
        cleaned = Counter()
        for n in members:
            cleaned[display_title(n)] += counts[n]

        def rank(t: str):
            letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
            mixed = letters != letters.upper() or len(letters) < 4
            return (-cleaned[t], not mixed, -len(t), t)
        best = sorted(cleaned, key=rank)[0]
        longer = [t for t in cleaned if t != best and compare_key(t).startswith(compare_key(best) + " ")]
        if longer:                                        # "Minotaur" + "Minotaur nel labirinto del potere": meglio il completo
            best = max(longer, key=lambda t: (cleaned[t] > 0, len(t)))
        for n in members:
            canon[n] = best
            if n != best:
                merged.append((n, best))
    for r in rows:
        if re.search(r"(?i)\b4k\b|\bried\b|\brid\.|restaurat|rimasterizz|remaster|anniversar|riedizione|ritorna", r["film"]):
            r["rer"] = True                                   # riedizione di un film vecchio: serve a TMDB
        if _VO_SUFFIX.search(r["film"]) and not r.get("tag"):
            r["tag"] = "VO"                                   # "Titolo - V. O." = proiezione in originale
        y = re.search(r"[\[(]\s*((?:19|20)\d{2})\s*[\])]", r["film"])   # "Titolo [2026]": serve a TMDB
        if y and "anno" not in r:
            r["anno"] = int(y.group(1))
        r["film"] = canon[r["film"]]
    return merged


# --------------------------------------------------------------------------- orchestrazione

def scrape_cinema(cfg: dict, day: str, fetcher, debug_dir: Path | None) -> tuple[list[dict], dict]:
    """Prova le fonti in ordine. mode='first': si ferma alla prima che trova orari;
    mode='all': unisce tutte le fonti."""
    mode = cfg.get("mode", "first")
    rows: list[dict] = []
    errors: list[str] = []
    used: list[str] = []
    fetched_ok = False

    for i, src in enumerate(cfg["sources"]):
        parser = PARSERS[src["type"]]
        try:
            html = fetcher(src["url"])
            fetched_ok = True
            if src.get("follow"):  # pagina indice: segue il primo link che combacia (es. ultimo post)
                link = next((h for h in re.findall(r'href=["\']([^"\']+)["\']', html)
                             if re.search(src["follow"], h)), None)
                if not link:
                    raise RuntimeError(f"nessun link '{src['follow']}' trovato")
                html = fetcher(urljoin(src["url"], link))
            if debug_dir:
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"{cfg['id']}-{i}.html").write_text(html, encoding="utf-8")
            found = parser(html, day)
            if src.get("venue"):  # sito condiviso da piu' cinema (18tickets): tieni solo il suo
                found = [r for r in found if src["venue"] in r.get("venue", "")]
            for r in found:
                r.pop("venue", None)
        except Exception as exc:  # noqa: BLE001 - una fonte rotta non deve fermare le altre
            errors.append(f"{src['type']}: {exc}")
            continue
        finally:
            time.sleep(DELAY_SECONDS)
        if found:
            used.append(src.get("label") or src["type"])
            rows.extend(found)
            if mode == "first":
                break

    # con mode='all' (o fonti sovrapposte) lo stesso spettacolo puo' arrivare due volte
    unique: dict[tuple, dict] = {}
    for r in rows:
        unique.setdefault((r["film"].lower(), r["date"], r["time"]), r)
    rows = list(unique.values())

    status = {
        "ok": fetched_ok and not (errors and not rows),
        "n": len(rows),
        "source": " + ".join(dict.fromkeys(used)) if used else None,
        "error": "; ".join(errors) if errors else None,
        "stale": False,
        "fetched_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
    }
    return rows, status


def run(config_path: Path, out_path: Path, only: str | None = None,
        debug_dir: Path | None = None, fetcher=fetch, today: str | None = None) -> dict:
    cinemas = json.loads(config_path.read_text(encoding="utf-8"))
    day = today or dt.datetime.now(TZ).date().isoformat()

    previous: dict = {}
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    prev_rows: dict[str, list[dict]] = {}
    for r in previous.get("showtimes", []):
        prev_rows.setdefault(r["cinema"], []).append(r)

    cache: dict[str, str | Exception] = {}
    raw_fetcher = fetcher

    def fetcher(url: str) -> str:  # noqa: F811 - una pagina condivisa si scarica una volta sola
        if url not in cache:
            try:
                cache[url] = raw_fetcher(url)
            except Exception as exc:  # noqa: BLE001
                cache[url] = exc
        if isinstance(cache[url], Exception):
            raise cache[url]
        return cache[url]

    all_rows: list[dict] = []
    meta: list[dict] = []
    for cfg in cinemas:
        if only and cfg["id"] != only:
            continue
        if not cfg.get("sources"):
            rows, status = [], {"ok": False, "n": 0, "source": None, "stale": False,
                                "error": "nessuna fonte configurata", "fetched_at": None}
        else:
            rows, status = scrape_cinema(cfg, day, fetcher, debug_dir)

        # Se il download e' fallito del tutto, riusa i dati precedenti ancora validi.
        if not rows and status["error"] and not status["ok"]:
            keep = [r for r in prev_rows.get(cfg["id"], []) if r["date"] >= day]
            if keep:
                for r in keep:
                    r.pop("cinema", None)
                rows = keep
                status["stale"] = True
                status["n"] = len(keep)

        for r in rows:
            all_rows.append({"cinema": cfg["id"], **{k: v for k, v in r.items() if k != "cinema"}})
        meta.append({
            "id": cfg["id"], "name": cfg["name"], "address": cfg.get("address"),
            "site": cfg.get("site"), "info_url": cfg.get("info_url"), "status": status,
        })

    all_rows = [r for r in all_rows if r["date"] >= day]
    junk = [r for r in all_rows if is_junk_title(r["film"])]
    if junk:
        print(f"  scartate {len(junk)} proiezioni senza titolo valido (es. {junk[0]['film']!r} a {junk[0]['cinema']})")
        all_rows = [r for r in all_rows if not is_junk_title(r["film"])]
    for a, b in snap_manual_titles(all_rows):
        print(f"  refuso nel PDF corretto: {a!r} -> {b!r}")
    for a, b in unify_titles(all_rows):
        print(f"  titoli unificati: {a!r} -> {b!r}")
    # dopo l'unificazione lo stesso spettacolo puo' comparire due volte nello stesso cinema
    uniq: dict[tuple, dict] = {}
    for r in all_rows:
        uniq.setdefault((r["cinema"], r["film"].lower(), r["date"], r["time"]), r)
    all_rows = list(uniq.values())
    all_rows.sort(key=lambda r: (r["date"], r["cinema"], r["film"].lower(), r["time"]))

    data = {
        "generated_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "today": day,
        "cinemas": meta,
        "showtimes": all_rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "scraper" / "cinemas.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "showtimes.json"))
    ap.add_argument("--only", help="id di un solo cinema")
    ap.add_argument("--debug-dir", help="cartella dove salvare l'HTML scaricato")
    args = ap.parse_args()

    data = run(Path(args.config), Path(args.out), args.only,
               Path(args.debug_dir) if args.debug_dir else None)

    try:  # schede e locandine: opzionale, non deve mai far fallire gli orari
        import os

        import films
        token = (os.environ.get("TMDB_TOKEN") or os.environ.get("TMDB_API_KEY") or "").strip()
        tmdb = films.tmdb_fetcher(token) if token else None
        if not tmdb:
            print("TMDB: nessuna chiave ricevuta (segreto TMDB_TOKEN non letto dal workflow?) -> solo Wikipedia")
        else:
            why = films.tmdb_check(tmdb)
            if why:
                print(f"TMDB: chiave non accettata ({why}) -> solo Wikipedia")
                tmdb = None
            else:
                print("TMDB: chiave OK")
        cache = films.enrich(data["showtimes"], Path(args.out).with_name("films.json"), fetch, data["today"],
                             tmdb=tmdb)
        print(f"schede film: {sum(1 for v in cache.values() if v.get('url'))}/{len(cache)} su Wikipedia, "
              f"{sum(1 for v in cache.values() if v.get('tmdb'))}/{len(cache)} su TMDB")
    except Exception as exc:  # noqa: BLE001
        print(f"schede film saltate: {exc}")

    try:  # posizione dei cinema (ordinamento per zona): opzionale
        import geo
        geo.ensure(data["cinemas"], Path(args.out).with_name("coordinates.json"), fetch)
    except Exception as exc:  # noqa: BLE001
        print(f"coordinate saltate: {exc}")

    ok = [c for c in data["cinemas"] if c["status"]["n"] > 0]
    print(f"{len(data['showtimes'])} proiezioni da {len(ok)}/{len(data['cinemas'])} cinema")
    for c in data["cinemas"]:
        s = c["status"]
        flag = "OK " if s["n"] > 0 else ("-- " if s["ok"] else "ERR")
        extra = " (dati precedenti)" if s["stale"] else ""
        print(f"  {flag} {c['name']:<28} {s['n']:>3} orari  {s['source'] or ''}{extra}"
              + (f"  [{s['error']}]" if s["error"] else ""))

    # Se non esce NESSUN orario da NESSUN cinema, la struttura dei siti e' cambiata:
    # fallire in modo visibile (GitHub manda una mail) invece di pubblicare un sito vuoto.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
