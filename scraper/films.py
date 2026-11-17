"""Arricchisce i film con scheda Wikipedia e locandina (via API pubblica di it.wikipedia.org).

Scrive data/films.json: { chiave_film: {"title", "url", "poster", "checked"} }.
Le ricerche gia' fatte non vengono ripetute (quelle senza esito si riprovano dopo 7 giorni).
Qualsiasi errore qui NON deve far fallire l'aggiornamento degli orari.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import unicodedata
import urllib.parse
from pathlib import Path

API = "https://it.wikipedia.org/w/api.php"
RETRY_DAYS = 7
MAX_LOOKUPS = 80  # per esecuzione
SCHEMA = 2        # alzare quando cambia il modo di estrarre i dati: rifa le ricerche gia' salvate


def film_key(title: str) -> str:
    """Stessa normalizzazione di filmKey() in index.html."""
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title.lower())
    t = re.sub(r"\b(4k|ried|rid)\b", " ", t)
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _words(s: str) -> set[str]:
    return {w for w in film_key(s).split() if len(w) > 1}


def pick(title: str, pages: list[dict]) -> dict | None:
    """Sceglie la pagina che e' davvero il film: l'introduzione dice 'film' e il titolo combacia."""
    want = _words(title)
    if not want:
        return None
    for p in sorted(pages, key=lambda p: p.get("index", 99)):
        extract = (p.get("extract") or "").lower()
        if "film" not in extract[:250]:
            continue
        got = _words(re.sub(r"\([^)]*\)", " ", p.get("title", "")))
        if got and len(want & got) / max(len(want), len(got)) >= 0.6:
            return p
    return None


_STOP = (r"(?:,?\s+(?:con|prodotto|prodotta|tratto|tratta|basato|basata|scritto|scritta|ispirato|ispirata|"
         r"interpretato|interpretata|distribuito|distribuita|uscito|uscita|presentato|presentata|liberamente)\b"
         r"|\s+e\s+(?:prodott\w+|sceneggiat\w+|scritt\w+|montat\w+|interpretat\w+|distribuit\w+)\b"
         r"|(?<!\b[A-Z])\.|[;(]|$)")
_NAMES = r"((?:[^.;(]|(?<=\b[A-Z])\.)+?)"   # i punti dopo un'iniziale ("J. J. Abrams") non chiudono il nome
# "diretto da X", "diretto, sceneggiato e montato da X", "scritto e diretto da X", "co-diretto da X"
_DIR = re.compile(r"\b(?:co-?)?dirett[oa]\b[^.;()]{0,70}?\bda\s+" + _NAMES + _STOP, re.I)
_DIR2 = re.compile(r"\bregia\s+di\s+" + _NAMES + _STOP, re.I)


def director_of(extract: str) -> str | None:
    """'... è un film del 2026 diretto da Paola Randi, con ...' -> 'Paola Randi'.
    Funziona anche se il regista fa anche altro: 'diretto, sceneggiato e montato da X'."""
    text = (extract or "")[:500].replace("\n", " ")
    for rx in (_DIR, _DIR2):
        m = rx.search(text)
        if m:
            d = re.sub(r"\s+", " ", m.group(1)).strip(" ,")
            if 3 <= len(d) <= 80:
                return d
    return None


def lookup(title: str, fetcher) -> dict | None:
    q = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title)
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q.strip()} film",
              "gsrlimit": "5", "prop": "pageimages|extracts|info", "inprop": "url", "piprop": "thumbnail",
              "pithumbsize": "240", "exintro": "1", "explaintext": "1", "exchars": "500", "redirects": "1"}
    data = json.loads(fetcher(API + "?" + urllib.parse.urlencode(params)))
    pages = list((data.get("query") or {}).get("pages", {}).values())
    p = pick(title, pages)
    if not p:
        return None
    return {"url": p.get("fullurl"), "poster": (p.get("thumbnail") or {}).get("source"),
            "director": director_of(p.get("extract"))}


def enrich(showtimes: list[dict], path: Path, fetcher, today: str | None = None, delay: float = 0.4) -> dict:
    today_d = dt.date.fromisoformat(today) if today else dt.date.today()
    try:
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        cache = {}
    titles: dict[str, str] = {}
    for r in showtimes:
        titles.setdefault(film_key(r["film"]), r["film"])
    n = 0
    for key, title in titles.items():
        old = cache.get(key)
        if old:
            age = (today_d - dt.date.fromisoformat(old["checked"])).days
            if (old.get("url") and old.get("v") == SCHEMA) or (not old.get("url") and old.get("v") == SCHEMA and age < RETRY_DAYS):
                continue
        if n >= MAX_LOOKUPS:
            break
        n += 1
        try:
            found = lookup(title, fetcher)
        except Exception:  # noqa: BLE001 - rete o API giu': si riprova al prossimo giro
            continue
        cache[key] = {"title": title, "url": (found or {}).get("url"),
                      "poster": (found or {}).get("poster"),
                      "director": (found or {}).get("director"), "v": SCHEMA, "checked": today_d.isoformat()}
        time.sleep(delay)
    # tieni nel file solo i film ancora in programmazione (o cercati di recente)
    cache = {k: v for k, v in cache.items() if k in titles or
             (today_d - dt.date.fromisoformat(v["checked"])).days < 30}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache
