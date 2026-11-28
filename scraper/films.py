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
MAX_LOOKUPS = 150 # per esecuzione
SCHEMA = 7        # alzare quando cambia il modo di estrarre i dati: rifa le ricerche gia' salvate


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
         r"|,?\s+che\b"
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


def wiki_year(extract: str) -> int | None:
    m = re.search(r"\bfilm\b[^.]{0,80}?\b((?:19|20)\d{2})\b", (extract or "")[:300], re.I)
    return int(m.group(1)) if m else None


def _wiki_search(query: str, title: str, fetcher) -> dict | None:
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": query,
              "gsrlimit": "6", "prop": "pageimages|extracts|info", "inprop": "url", "piprop": "thumbnail",
              "pithumbsize": "240", "exintro": "1", "explaintext": "1", "exchars": "500", "redirects": "1"}
    data = json.loads(fetcher(API + "?" + urllib.parse.urlencode(params)))
    pages = list((data.get("query") or {}).get("pages", {}).values())
    p = pick(title, pages)
    if not p:
        return None
    return {"url": p.get("fullurl"), "poster": (p.get("thumbnail") or {}).get("source"),
            "director": director_of(p.get("extract")), "year": wiki_year(p.get("extract")),
            "extract": p.get("extract") or ""}


def lookup(title: str, fetcher, year: int | None = None, director: str | None = None) -> dict | None:
    """Cerca la pagina Wikipedia del film. Prova piu' query (con anno e regista, se noti) e tiene la prima
    pagina che sia davvero un film con quel titolo; l'omonimia si controlla poi in decide()."""
    q = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title).strip()
    queries = []
    if year:
        queries.append(f"{q} film {year}")
    if director:
        queries.append(f"{q} film {director}")
    queries.append(f"{q} film")
    last = None
    for qq in queries:
        found = _wiki_search(qq, title, fetcher)
        if not found:
            continue
        last = last or found
        ok_year = not year or not found["year"] or abs(found["year"] - year) <= 1
        ok_dir = not director or surname_match(director, found["director"]) is not False
        if ok_year and ok_dir:
            return found
    return last


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
    if not x or not y:
        return 0.0
    r = difflib.SequenceMatcher(None, x, y).ratio()
    # refusi di battitura sugli spazi ("Èandata così" per "È andata così"): si confronta anche senza spazi
    xs, ys = x.replace(" ", ""), y.replace(" ", "")
    return max(r, difflib.SequenceMatcher(None, xs, ys).ratio() - 0.02) if xs and ys else r


def _fold(s: str) -> str:
    """Minuscolo, senza accenti ne' apostrofi/trattini: 'Iñárritu' -> 'inarritu', "Kore'eda" -> 'koreeda'."""
    t = unicodedata.normalize("NFD", s.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"['’`\-]", "", t)


def _tokens(s: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9]+", " ", _fold(s)).split())


def surname_match(ref: str | None, names: list[str] | str | None) -> bool | None:
    """True/False se i registi coincidono (per cognome), None se non si puo' dire: uno dei due non e' noto,
    oppure i nomi sono in un alfabeto non latino (TMDB scrive 나홍진 o 新海誠, Wikipedia 'Na Hong-jin')."""
    if isinstance(names, str):
        names = [p for p in re.split(r",|\be\b|\band\b|&", names) if p.strip()]
    if not ref or not names:
        return None
    ref_t = _tokens(ref)
    comparable = 0
    for n in names:
        t = re.sub(r"[^a-z0-9]+", " ", _fold(n)).split()
        if not t:
            continue                       # nome non latino: non confrontabile
        comparable += 1
        sur = t[-1]
        if (len(sur) >= 3 and sur in ref_t) or (len(sur) < 3 and any(len(w) >= 3 and w in ref_t for w in t)):
            return True
    return False if comparable else None


def _all_titles(d: dict) -> list[str]:
    """Titolo italiano, originale, alternativi e traduzioni: i titoli italiani spesso esistono solo qui."""
    out = [d.get("title"), d.get("original_title")]
    out += [a.get("title") for a in ((d.get("alternative_titles") or {}).get("titles") or [])]
    out += [(t.get("data") or {}).get("title") for t in ((d.get("translations") or {}).get("translations") or [])]
    return [t for t in out if t]


def _query_variants(q: str) -> list[str]:
    """Il titolo cosi' com'e', poi versioni corrette di refusi tipici: accento attaccato alla parola dopo
    ("Èandata" -> "È andata"), spazi doppi, apostrofi tipografici."""
    out = [q]
    v = re.sub(r"\b([ÈÉÀÒÙÌèéàòùì])(?=[a-zà-ü]{2,})", r"\1 ", q)
    v = re.sub(r"\s+", " ", v.replace("’", "'")).strip()
    if v and v not in out:
        out.append(v)
    return out


def _person_titles(director: str, fetch) -> list[int]:
    """Film noti del regista dichiarato dal cinema: ultimo ripiego quando il titolo ha un refuso troppo grosso."""
    res = json.loads(fetch(f"{TMDB_API}/search/person?" + urllib.parse.urlencode(
        {"query": director, "language": "it-IT", "include_adult": "false"})))
    ids: list[int] = []
    for p in (res.get("results") or [])[:2]:
        if p.get("known_for_department") not in (None, "Directing"):
            continue
        for m in p.get("known_for") or []:
            if m.get("media_type", "movie") == "movie" and m.get("id") not in ids:
                ids.append(m["id"])
    return ids


def tmdb_candidates(title: str, fetch, hint_year: int | None = None, notes: list[str] | None = None,
                    director: str | None = None) -> list[dict]:
    """Cerca il film e, per i primi risultati, scarica dettagli, regia e titoli alternativi.
    Il titolo conta se somiglia a UNO qualsiasi dei titoli noti (anche solo traduzioni o titoli alternativi):
    una scheda TMDB senza traduzione italiana si trova comunque."""
    notes = notes if notes is not None else []
    q = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title).strip()
    results: list[dict] = []
    for qv in _query_variants(q):
        for year in ([hint_year, None] if hint_year else [None]):    # se con l'anno non c'e' nulla, riprova senza
            params = {"query": qv, "language": "it-IT", "include_adult": "false"}
            if year:
                params["year"] = str(year)
            res = json.loads(fetch(f"{TMDB_API}/search/movie?" + urllib.parse.urlencode(params)))
            results = res.get("results", [])
            if results:
                break
        if results:
            if qv != q:
                notes.append(f"titolo corretto per la ricerca: '{qv}'")
                q = qv
            break
    if director and not any(title_sim(q, r.get("title") or "") >= 0.8 or
                            title_sim(q, r.get("original_title") or "") >= 0.8 for r in results):
        try:                                   # nessun risultato somiglia al titolo: si prova dal regista
            known = [{"id": i} for i in _person_titles(director, fetch)]
        except Exception:  # noqa: BLE001
            known = []
        have = {r["id"] for r in results}
        results = results + [k for k in known if k["id"] not in have]
        if known:
            notes.append(f"ricerca anche tra i film di {director}")
    if not results:
        notes.append("TMDB: la ricerca non ha restituito nessun film")
        return []
    out = []
    for r in sorted(results, key=lambda r: -(r.get("popularity") or 0))[:5]:
        d = json.loads(fetch(f"{TMDB_API}/movie/{r['id']}?" + urllib.parse.urlencode(
            {"language": "it-IT", "append_to_response": "credits,alternative_titles,translations"})))
        sim = max([max(title_sim(q, t), title_sim(title, t)) for t in _all_titles(d)] or [0.0])
        crew = (d.get("credits") or {}).get("crew") or []
        year = int((d.get("release_date") or "0000")[:4] or 0) or None
        out.append({"id": d["id"], "sim": sim, "year": year, "popularity": d.get("popularity") or 0,
                    "title": (d.get("title") or "").strip() or None,
                    "poster_path": d.get("poster_path"), "runtime": d.get("runtime") or None,
                    "directors": [c["name"] for c in crew if c.get("job") == "Director"],
                    "overview": (d.get("overview") or "").strip()[:700] or None,
                    "genres": [g["name"] for g in (d.get("genres") or []) if g.get("name")][:4],
                    "cast": [c["name"] for c in ((d.get("credits") or {}).get("cast") or [])[:6] if c.get("name")],
                    "original_title": d.get("original_title") or None,
                    "release_date": d.get("release_date") or None})
    return out


def _months_from(today: dt.date, release: str | None) -> float | None:
    try:
        return (dt.date.fromisoformat(release) - today).days / 30.4
    except (TypeError, ValueError):
        return None


def decide(title: str, ref_dir: str | None, hint_year: int | None, wiki: dict | None,
           cands: list[dict], today: dt.date | None = None, rerelease: bool = False,
           notes: list[str] | None = None) -> tuple[dict | None, dict | None, str]:
    """Controllo incrociato titolo + regista + anno. Meglio nessun dato che un dato di un film omonimo.

    Regole per TMDB (un candidato passa solo se):
      1. titolo molto simile;
      2. se si conosce l'anno (dal cinema o da Wikipedia): uscita entro un anno;
      3. se si conosce il regista (dal cinema o da Wikipedia): coincide per cognome;
      4. se NON c'e' alcun riscontro (ne' regista ne' anno): il film deve essere uscito da poco (da 18 mesi fa
         a 8 mesi avanti), a meno che sia una riedizione dichiarata e il titolo sia identico;
      5. se piu' candidati passano e nessuno e' confermato dal regista: ambiguo -> nessuno.
    Wikipedia viene scartata se regista o anno contraddicono quanto dichiarato dal cinema.
    """
    today = today or dt.date.today()
    notes = notes if notes is not None else []
    wiki_dir = (wiki or {}).get("director")

    if wiki:
        if surname_match(ref_dir, wiki_dir) is False:
            wiki = None
            notes.append("wikipedia scartata: regista diverso da quello del cinema")
        elif hint_year and wiki.get("year") and abs(wiki["year"] - hint_year) > 1:
            wiki = None
            notes.append("wikipedia scartata: anno diverso da quello del cinema")
        elif ref_dir and not wiki_dir and surname_match(ref_dir, [w for w in (wiki.get("extract") or "").split()
                                                                  if w[:1].isupper()]) is not True:
            wiki = None
            notes.append("wikipedia scartata: il regista del cinema non compare nella scheda")
    wiki_dir = (wiki or {}).get("director")
    check_dir = ref_dir or wiki_dir
    year = hint_year or (wiki or {}).get("year")

    passed: list[tuple[bool, dict]] = []
    for c in cands:
        why = None
        m = surname_match(check_dir, c["directors"]) if check_dir else None
        if c["sim"] < 0.85 and not (m is True and c["sim"] >= 0.5):
            why = f"titolo diverso (somiglianza {c['sim']:.2f}: '{c.get('title')}' / '{c.get('original_title')}')"
        elif year and c["year"] and abs(c["year"] - year) > 1:
            why = f"anno {c['year']} != {year}"
        elif m is False:
            why = f"regista {', '.join(c['directors'][:2]) or '?'} != '{check_dir}'"
        elif m is None and not year:
            age = _months_from(today, c["release_date"])
            recent = age is not None and -18 <= age <= 8
            # film non recente senza anno/regista: va bene se Wikipedia conferma che esiste un film con questo
            # titolo e TMDB ne ha uno solo con titolo identico (le incongruenze si vedono poi nel confronto con wiki)
            sole = wiki is not None and c["sim"] >= 0.95 and sum(1 for x in cands if x["sim"] >= 0.95) == 1
            if not recent and not sole and not (rerelease and c["sim"] >= 0.95):
                why = f"nessun riscontro e uscita {c['year'] or '?'} non recente"
        if why:
            notes.append(f"TMDB scartato id {c['id']} ({c['year']}): {why}")
        else:
            passed.append((m is True, c))

    if not cands and not any(n.startswith("TMDB:") for n in notes):
        notes.append("TMDB: nessun risultato con titolo simile")
    chosen = None
    if len(passed) == 1:
        chosen = passed[0][1]
    elif passed:
        confirmed = [c for ok, c in passed if ok]
        by_year = [c for _, c in passed if year and c["year"] == year]
        pool = confirmed if len(confirmed) == 1 else by_year if len(by_year) == 1 else []
        if pool:
            chosen = pool[0]
        else:
            notes.append(f"TMDB ambiguo: {len(passed)} film con lo stesso titolo, nessuna conferma -> nessun dato")

    t = None
    if chosen:
        runtime = chosen["runtime"] if chosen["runtime"] and 30 <= chosen["runtime"] <= 400 else None
        t = {"id": chosen["id"], "title": chosen.get("title"), "url": f"{TMDB_PAGE}{chosen['id']}?language=it-IT",
             "poster_path": chosen["poster_path"], "runtime": runtime,
             "director": ", ".join(chosen["directors"]) or None, "year": chosen["year"],
             "overview": chosen["overview"], "genres": chosen["genres"], "cast": chosen["cast"],
             "original_title": chosen["original_title"], "release_date": chosen["release_date"]}
        # TMDB e Wikipedia devono parlare dello stesso film
        if wiki and wiki.get("year") and chosen["year"] and abs(wiki["year"] - chosen["year"]) > 1:
            notes.append("scartati Wikipedia e TMDB: anni diversi (omonimia probabile)")
            return None, None, "; ".join(notes)
        if wiki and wiki_dir and chosen["directors"] and surname_match(wiki_dir, chosen["directors"]) is False:
            notes.append("scartati Wikipedia e TMDB: registi diversi (omonimia probabile)")
            return None, None, "; ".join(notes)
    return wiki, t, "; ".join(notes)


def _refs(showtimes: list[dict]) -> dict[str, dict]:
    """Per ogni film: titolo, regista e anno dichiarati dai cinema (fonti ufficiali)."""
    refs: dict[str, dict] = {}
    for r in showtimes:
        k = film_key(r["film"])
        if r.get("nofilm"):
            continue                               # programmi di corti, cerimonie: niente scheda
        e = refs.setdefault(k, {"title": r["film"], "regia": "", "anno": None, "rer": False})
        e["regia"] = e["regia"] or r.get("regia", "")
        e["anno"] = e["anno"] or r.get("anno")
        e["rer"] = e["rer"] or bool(r.get("rer"))
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
            wiki = lookup(title, fetcher, ref["anno"], ref["regia"] or None)
        except Exception:  # noqa: BLE001 - rete o API giu': si riprova al prossimo giro
            continue
        cands, tmdb_ok, notes0 = [], bool(tmdb), []
        if wiki is None:
            notes0.append("Wikipedia: nessuna pagina che sia un film con questo titolo")
        if tmdb:
            try:
                cands = tmdb_candidates(title, tmdb, ref["anno"] or (wiki or {}).get("year"), notes0,
                                        ref["regia"] or None)
            except Exception as exc:  # noqa: BLE001 - errore TMDB: lo si vede nel log, i dati Wikipedia restano
                if not tmdb_errors:
                    print(f"  TMDB errore: {exc}")
                tmdb_errors.append(title)
                tmdb_ok = False
                notes0.append(f"TMDB: errore di rete/API ({exc})")
        elif not tmdb:
            notes0.append("TMDB: chiave non configurata")
        wiki, t, note = decide(title, ref["regia"] or None, ref["anno"], wiki, cands, today_d, ref["rer"], notes0)
        if tmdb_ok and tmdb and not t and not note:
            note = "TMDB: nessun candidato adatto"
        if note and printed < 200:
            printed += 1
            print(f"  film '{title}': {note}")
        cache[key] = {"title": title, "url": (wiki or {}).get("url"), "poster": (wiki or {}).get("poster"),
                      "director": (wiki or {}).get("director"), "tmdb": t, "t": tmdb_ok, "v": SCHEMA,
                      "why": note or None, "ref": {"regia": ref["regia"] or None, "anno": ref["anno"]},
                      "checked": today_d.isoformat()}
        time.sleep(delay)
    # tieni nel file solo i film ancora in programmazione (o cercati di recente)
    cache = {k: v for k, v in cache.items() if k in refs or
             (v.get("v") == SCHEMA and (today_d - dt.date.fromisoformat(v["checked"])).days < 30)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        write_report(cache, refs, path.with_name("tmdb_report.txt"), today_d)
    except Exception as exc:  # noqa: BLE001 - il report e' solo un aiuto
        print(f"  report TMDB non scritto: {exc}")
    return cache


def write_report(cache: dict, refs: dict, out: Path, today: dt.date) -> None:
    """Elenco leggibile dei film SENZA dati TMDB e del motivo (data/tmdb_report.txt)."""
    ok = [k for k in refs if (cache.get(k) or {}).get("tmdb")]
    bad = [k for k in refs if not (cache.get(k) or {}).get("tmdb")]
    lines = [f"Report TMDB del {today.isoformat()}: {len(ok)} film con dati TMDB, {len(bad)} senza.", ""]
    for k in sorted(bad, key=lambda k: refs[k]["title"].lower()):
        e = cache.get(k) or {}
        ref = refs[k]
        lines.append(f"- {ref['title']}  [regia dichiarata: {ref['regia'] or '-'}; anno: {ref['anno'] or '-'}; "
                     f"Wikipedia: {'si' if e.get('url') else 'no'}]")
        lines.append(f"    motivo: {e.get('why') or 'non ancora cercato (limite di ricerche per giro o errore di rete)'}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
