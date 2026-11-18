"""Sonda (uso una tantum, via GitHub Actions): prova indirizzi alternativi per leggere piu' giorni
di programmazione di UCI Lingotto e The Space (i loro siti ufficiali rifiutano GitHub con errore 403).
Scrive out/sonda/RAPPORTO.txt e salva le pagine ricevute."""
from __future__ import annotations
import datetime as dt, gzip, hashlib, os, re, urllib.request, urllib.error

OUT = os.path.join("out", "sonda")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
T = dt.date.today()
D1, D2 = T + dt.timedelta(days=1), T + dt.timedelta(days=3)


def variants(base: str, label: str):
    yield f"{label} base", base
    for d in (D1, D2):
        iso, it = d.isoformat(), d.strftime("%d/%m/%Y")
        for q in (f"?data={iso}", f"?data={it}", f"?giorno={iso}", f"?giorno={it}", f"?d={iso}", f"?day={iso}", f"?date={iso}"):
            yield f"{label} {q}", base + q
        yield f"{label} /{iso}/", base + iso + "/"


PROBES = list(variants("https://www.mymovies.it/cinema/torino/5410/", "mymovies-UCI")) + [
    ("mymovies-Space base", "https://www.mymovies.it/cinema/torino/5884/"),
    ("mymovies-Space ?data", f"https://www.mymovies.it/cinema/torino/5884/?data={D1.isoformat()}"),
    ("mymovies RSS torino", "https://www.mymovies.it/cinema/xml/rss/?id=torino"),
    ("mymovies RSS UCI", "https://www.mymovies.it/cinema/xml/rss/?id=torino&cinema=5410"),
    ("mymovies provincia", "https://www.mymovies.it/cinema/torino/provincia/"),
    ("imdb 1034361", "https://www.imdb.com/it/showtimes/cinema/IT/ci1034361/IT/10080"),
    ("imdb 1034361 +1", f"https://www.imdb.com/it/showtimes/cinema/IT/ci1034361/IT/10080?date={D1.isoformat()}"),
    ("imdb 1034359", "https://www.imdb.com/showtimes/cinema/IT/ci1034359/IT/10016"),
    ("imdb 1034380", "https://www.imdb.com/showtimes/cinema/IT/ci1034380/IT/10080"),
    ("movieplayer UCI ?data", f"https://movieplayer.it/cinema/uci-cinemas-lingotto_1455/?data={D1.isoformat()}"),
    ("movieplayer UCI /orari", "https://movieplayer.it/cinema/uci-cinemas-lingotto_1455/orari/"),
    ("movieplayer Space", "https://movieplayer.it/cinema/the-space-cinema-torino-parco-dora_1451/"),
    ("UCI ufficiale (UA browser)", "https://www.ucicinemas.it/cinema/piemonte/torino/uci-cinemas-torino-lingotto/"),
    ("Space ufficiale", "https://www.thespacecinema.it/cinema/torino-parco-dora"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
                                               "Accept-Language": "it-IT,it;q=0.9", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return r.status, r.headers.get("Content-Type", ""), r.geturl(), data


def main():
    os.makedirs(OUT, exist_ok=True)
    rep, base_hash = [f"data di oggi: {T}  (giorni provati: {D1}, {D2})\n"], None
    for i, (name, url) in enumerate(PROBES):
        try:
            st, ct, final, data = get(url)
        except urllib.error.HTTPError as e:
            rep.append(f"[{name}] {url}\n   HTTP {e.code}"); continue
        except Exception as e:
            rep.append(f"[{name}] {url}\n   ERRORE {e}"); continue
        txt = data.decode("utf-8", "replace")
        body = re.sub(r"<(script|style)[\s\S]*?</\1>", "", txt)
        times = re.findall(r"(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)", re.sub(r"<[^>]+>", " ", body))
        h = hashlib.md5(re.sub(r"\s+", "", body).encode()).hexdigest()[:8]
        same = " (IDENTICA alla base)" if base_hash and h == base_hash else ""
        if name.endswith("base") and "mymovies-UCI" in name:
            base_hash = h
        title = (re.search(r"<title>([^<]*)", txt) or [0, ""])[1].strip()[:80]
        fn = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:50] + ".html"
        open(os.path.join(OUT, fn), "wb").write(data[:700_000])
        rep.append(f"[{name}] {url}\n   HTTP {st} {ct.split(';')[0]} {len(data)}B finale={final if final != url else '='} "
                   f"titolo={title!r}\n   orari trovati: {len(times)} hash={h}{same} -> {fn}")
    open(os.path.join(OUT, "RAPPORTO.txt"), "w", encoding="utf-8").write("\n".join(rep))
    print("\n".join(rep))


if __name__ == "__main__":
    main()
