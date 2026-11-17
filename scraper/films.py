"""Arricchisce i film con schede e locandine: Wikipedia (API pubblica) e, se c'e' la chiave
TMDB_TOKEN, anche TMDB (locandina, durata, regia).

Scrive data/films.json: { chiave_film: {"title", "url", "poster", "director", "tmdb": {...}, "checked"} }.
Controllo incrociato: un link (Wikipedia o TMDB) viene tenuto solo se titolo, anno e REGISTA
sono coerenti con quanto si sa del film; cosi' non si punta a un film omonimo.
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
SCHEMA = 4        # alzare quando cambia il modo di estrarre i dati: rifa le ricerche gia' salvate


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


# ----------------------------------------------------------------------------- TMDB

TMDB_API = "https://api.themoviedb.org/3"
TMDB_PAGE = "https://www.themoviedb.org/movie/"


def tmdb_fetcher(token: str):
    """Funzione fetch(url) per TMDB: accetta sia il 'Read Access Token' (JWT) sia la vecchia api_key."""
    import urllib.request

    def fetch(url: str) -> str:
        headers = {"Accept": "application/json", "User-Agent": "CinemaTorinoPersonale/1.0"}
        if token.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {token}"
        else:
            url += ("&" if "?" in url else "?") + "api_key=" + urllib.parse.quote(token)
        last: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as r:
                    return r.read().decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1 + attempt)
        raise RuntimeError(f"TMDB: {last}")
    return fetch


def tmdb_check(fetch) -> str | None:
    """None se la chiave funziona, altrimenti il motivo (per il log)."""
    try:
        json.loads(fetch(f"{TMDB_API}/configuration"))
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _strip_articles(key: str) -> str:
    w = key.split()
    while len(w) > 1 and w[0] in {"il", "lo", "la", "l", "i", "gli", "le", "the", "un", "una", "uno"}:
        w.pop(0)
    return " ".join(w)


def title_sim(a: str, b: str) -> float:
    import difflib
    x, y = _strip_articles(film_key(a)), _strip_articles(film_key(b))
    return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0


def _tokens(s: str) -> set[str]:
    t = re.sub(r"['’`\-]", "", unicodedata.normalize("NFD", s.lower()))   # Kore'eda == Koreeda
    t = "".join(c for c in t if not unicodedata.combining(c))
    return set(re.sub(r"[^a-z0-9]+", " ", t).split())


def surname_match(ref: str | None, names: list[str] | str | None) -> bool | None:
    """True/False se i registi coincidono (per cognome), None se uno dei due non e' noto."""
    if isinstance(names, str):
        names = [p for p in re.split(r",|\be\b|\band\b|&", names) if p.strip()]
    if not ref or not names:
        return None
    ref_t = _tokens(ref)
    for n in names:
        t = [w for w in re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’`\-]", "", unicodedata.normalize("NFD", n.lower()))).split() if w]
        t = ["".join(c for c in w if not unicodedata.combining(c)) for w in t]
        if not t:
            continue
        sur = t[-1]
        if (len(sur) >= 3 and sur in ref_t) or (len(sur) < 3 and any(len(w) >= 3 and w in ref_t for w in t)):
            return True
    return False


def tmdb_candidates(title: str, fetch, hint_year: int | None = None) -> list[dict]:
    """Cerca il film e, per i risultati con titolo simile, scarica dettagli e regia."""
    q = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title).strip()
    res = json.loads(fetch(f"{TMDB_API}/search/movie?" + urllib.parse.urlencode(
        {"query": q, "language": "it-IT", "include_adult": "false"})))
    hits = []
    for r in res.get("results", []):
        sim = max(title_sim(q, r.get("title", "")), title_sim(q, r.get("original_title", "")))
        if sim >= 0.75:
            hits.append((sim, r))
    hits.sort(key=lambda x: (-x[0], -(x[1].get("popularity") or 0)))
    out = []
    for sim, r in hits[:3]:
        d = json.loads(fetch(f"{TMDB_API}/movie/{r['id']}?" + urllib.parse.urlencode(
            {"language": "it-IT", "append_to_response": "credits"})))
        crew = (d.get("credits") or {}).get("crew") or []
        year = int((d.get("release_date") or "0000")[:4] or 0) or None
        out.append({"id": d["id"], "sim": sim, "year": year, "popularity": d.get("popularity") or 0,
                    "poster_path": d.get("poster_path"), "runtime": d.get("runtime") or None,
                    "directors": [c["name"] for c in crew if c.get("job") == "Director"],
                    "overview": (d.get("overview") or "").strip()[:700] or None,
                    "genres": [g["name"] for g in (d.get("genres") or []) if g.get("name")][:4],
                    "cast": [c["name"] for c in ((d.get("credits") or {}).get("cast") or [])[:6] if c.get("name")],
                    "original_title": d.get("original_title") or None,
                    "release_date": d.get("release_date") or None})
    return out


def decide(title: str, ref_dir: str | None, hint_year: int | None, wiki: dict | None,
           cands: list[dict]) -> tuple[dict | None, dict | None, str]:
    """Controllo incrociato titolo + regista (+ anno). Restituisce (wiki, tmdb, nota)."""
    wiki_dir = (wiki or {}).get("director")
    note = ""
    # Wikipedia: scartata se il regista noto dal cinema e' un altro
    if wiki and surname_match(ref_dir, wiki_dir) is False:
        wiki, note = None, "wikipedia scartata: regista diverso da quello del cinema"
    check_dir = ref_dir or (wiki_dir if wiki else None)

    accepted, strong_conflict = [], False
    if not cands:
        note = (note + "; " if note else "") + "TMDB: nessun risultato con titolo simile"
    for c in cands:
        year_ok = not hint_year or not c["year"] or abs(c["year"] - hint_year) <= 1
        m = surname_match(check_dir, c["directors"]) if check_dir else None
        if m is True and c["sim"] >= 0.75:
            accepted.append((2, c))
        elif m is None and c["sim"] >= 0.9 and year_ok:
            accepted.append((1, c))
        elif m is False and c["sim"] >= 0.9:
            strong_conflict = True
        if not accepted or accepted[-1][1] is not c:
            note = (note + "; " if note else "") + (
                f"TMDB scartato id {c['id']} ({c['year']}): "
                + ("regista " + ", ".join(c["directors"][:2]) + f" != '{check_dir}'" if m is False
                   else "anno non coerente" if not year_ok else "regista non confrontabile e titolo non identico"))
    if accepted:
        accepted.sort(key=lambda x: (-x[0], -x[1]["sim"], -x[1]["popularity"]))
        best = accepted[0][1]
        t = {"id": best["id"], "url": f"{TMDB_PAGE}{best['id']}?language=it-IT",
             "poster_path": best["poster_path"], "runtime": best["runtime"],
             "director": ", ".join(best["directors"]) or None, "year": best["year"],
             "overview": best["overview"], "genres": best["genres"], "cast": best["cast"],
             "original_title": best["original_title"], "release_date": best["release_date"]}
        return wiki, t, note
    if strong_conflict and not ref_dir and wiki:
        # TMDB e Wikipedia indicano due registi diversi per lo stesso titolo: probabile omonimia, meglio nessun link
        return None, None, "scartati Wikipedia e TMDB: stesso titolo ma registi diversi"
    return wiki, None, note


def _refs(showtimes: list[dict]) -> dict[str, dict]:
    """Per ogni film: titolo, regista e anno dichiarati dai cinema (fonti ufficiali)."""
    refs: dict[str, dict] = {}
    for r in showtimes:
        k = film_key(r["film"])
        e = refs.setdefault(k, {"title": r["film"], "regia": "", "anno": None})
        e["regia"] = e["regia"] or r.get("regia", "")
        e["anno"] = e["anno"] or r.get("anno")
    return refs


def enrich(showtimes: list[dict], path: Path, fetcher, today: str | None = None, delay: float = 0.4,
           tmdb=None) -> dict:
    today_d = dt.date.fromisoformat(today) if today else dt.date.today()
    try:
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        cache = {}
    refs = _refs(showtimes)
    n = 0
    tmdb_errors: list[str] = []
    printed = 0
    for key, ref in refs.items():
        title = ref["title"]
        old = cache.get(key)
        if old and old.get("v") == SCHEMA and (old.get("t") or tmdb is None):
            age = (today_d - dt.date.fromisoformat(old["checked"])).days
            if old.get("url") or old.get("tmdb") or age < RETRY_DAYS:
                continue
        if n >= MAX_LOOKUPS:
            break
        n += 1
        try:
            wiki = lookup(title, fetcher)
        except Exception:  # noqa: BLE001 - rete o API giu': si riprova al prossimo giro
            continue
        cands, tmdb_ok = [], bool(tmdb)
        if tmdb:
            try:
                cands = tmdb_candidates(title, tmdb, ref["anno"])
            except Exception as exc:  # noqa: BLE001 - errore TMDB: lo si vede nel log, i dati Wikipedia restano
                if not tmdb_errors:
                    print(f"  TMDB errore: {exc}")
                tmdb_errors.append(title)
                tmdb_ok = False
        wiki, t, note = decide(title, ref["regia"] or None, ref["anno"], wiki, cands)
        if note and printed < 40:
            printed += 1
            print(f"  film '{title}': {note}")
        cache[key] = {"title": title, "url": (wiki or {}).get("url"), "poster": (wiki or {}).get("poster"),
                      "director": (wiki or {}).get("director"), "tmdb": t, "t": tmdb_ok, "v": SCHEMA,
                      "checked": today_d.isoformat()}
        time.sleep(delay)
    # tieni nel file solo i film ancora in programmazione (o cercati di recente)
    cache = {k: v for k, v in cache.items() if k in refs or
             (today_d - dt.date.fromisoformat(v["checked"])).days < 30}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache
