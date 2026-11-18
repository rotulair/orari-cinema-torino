"""Strumento di esplorazione (uso una tantum, via GitHub Actions).

Scarica le pagine dei siti ufficiali (Circuito Gran Torino, UCI, The Space, MyMovies), segue i link utili
(programmazione, PDF, cinema di Torino) e salva HTML + un rapporto in out/esplora/.
Serve solo a capire come leggere l'intera settimana: non modifica la programmazione del sito.
"""
from __future__ import annotations
import gzip, json, os, re, subprocess, sys, urllib.request, urllib.parse
from html.parser import HTMLParser

OUT = os.path.join("out", "esplora")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SITES = {
    "grantorino": ("https://www.circuitograntorino.com/", r"greenwich|classico|empire|programm|settimana|orari|\.pdf|torino"),
    "uci": ("https://www.ucicinemas.it/", r"lingotto|torino|programm|orari|cinema"),
    "thespace": ("https://www.thespacecinema.it/", r"parco-dora|torino|programm|orari|cinema"),
    "mymovies": ("https://www.mymovies.it/cinema/torino/", r"uci|lingotto|space|parco-dora|greenwich|classico|empire|cinema/torino"),
}
MAX_PAGES = 10
KEY = re.compile(r"pdf|programm|orari|settimana|lingotto|parco|dora|greenwich|classico|empire|showtime|film", re.I)


def fetch(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*", "Accept-Language": "it-IT,it;q=0.9", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return r.status, r.headers.get("Content-Type", ""), data


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.title = ""; self._t = False; self._a = None; self.scripts = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title": self._t = True
        if tag == "a" and a.get("href"): self._a = [a["href"], ""]
        if tag == "script" and a.get("src"): self.scripts.append(a["src"])
        if tag in ("iframe", "embed", "object"):
            u = a.get("src") or a.get("data")
            if u: self.links.append((u, f"<{tag}>"))
    def handle_endtag(self, tag):
        if tag == "title": self._t = False
        if tag == "a" and self._a: self.links.append(tuple(self._a)); self._a = None
    def handle_data(self, d):
        if self._t: self.title += d
        if self._a is not None: self._a[1] += d.strip() + " "


def slug(u: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", urllib.parse.urlparse(u).path.lower()).strip("_")[:60] or "home"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    rep = []
    for name, (start, rx) in SITES.items():
        rep.append(f"\n{'='*70}\n## {name}  {start}\n")
        os.makedirs(os.path.join(OUT, name), exist_ok=True)
        queue, seen, n = [start], set(), 0
        while queue and n < MAX_PAGES:
            url = queue.pop(0)
            if url in seen: continue
            seen.add(url)
            try:
                st, ct, data = fetch(url)
            except Exception as e:
                rep.append(f"- {url}  ERRORE {e}"); continue
            n += 1
            is_pdf = "pdf" in ct.lower() or url.lower().endswith(".pdf")
            fn = os.path.join(OUT, name, slug(url) + (".pdf" if is_pdf else ".html"))
            with open(fn, "wb") as f: f.write(data[:900_000])
            rep.append(f"- {url}  [{st}] {ct} {len(data)} byte -> {os.path.basename(fn)}")
            if is_pdf:
                try:
                    txt = subprocess.run(["pdftotext", "-layout", fn, "-"], capture_output=True, text=True, timeout=30).stdout
                    rep.append("  testo PDF (primi 1500 caratteri):\n" + txt[:1500])
                    open(fn + ".txt", "w", encoding="utf-8").write(txt)
                except Exception as e:
                    rep.append(f"  pdftotext non disponibile: {e}")
                continue
            html = data.decode("utf-8", "replace")
            p = Links(); p.feed(html)
            rep.append(f"  titolo: {p.title.strip()[:100]}")
            hints = []
            for tag, rxs in (("JSON-LD", r"application/ld\+json"), ("__NEXT_DATA__", r"__NEXT_DATA__"), ("stato JS", r"window\.__[A-Z_]+__|__INITIAL_STATE__"), ("Vista/ticketing", r"vista|ticket|booking")):
                if re.search(rxs, html, re.I): hints.append(tag)
            if hints: rep.append("  indizi: " + ", ".join(hints))
            api = sorted(set(re.findall(r"""["'](https?://[^"'\s<>]+|/[A-Za-z0-9_\-/]*(?:api|json|graphql|ajax)[^"'\s<>]*)["']""", html)))
            api = [a for a in api if re.search(r"api|json|graphql|ajax|programm|showtime|film|cinema", a, re.I) and not re.search(r"\.(png|jpe?g|svg|css|woff2?|gif|ico|webp)(\?|$)", a, re.I)]
            if api: rep.append("  possibili endpoint: " + "\n    ".join([""] + api[:25]))
            useful = []
            for href, text in p.links:
                u = urllib.parse.urljoin(url, href.split("#")[0])
                if not u.startswith("http"): continue
                host_ok = urllib.parse.urlparse(u).netloc.split(".")[-2:] == urllib.parse.urlparse(start).netloc.split(".")[-2:]
                if (KEY.search(u) or KEY.search(text)) and (host_ok or u.lower().endswith(".pdf")):
                    useful.append((u, text.strip()[:60]))
            uniq = list(dict.fromkeys(useful))
            rep.append(f"  link utili ({len(uniq)}):" + "".join(f"\n    {t!r} -> {u}" for u, t in uniq[:40]))
            for u, t in uniq:
                if re.search(rx, u + " " + t, re.I) and u not in seen and u not in queue:
                    (queue.insert(0, u) if u.lower().endswith(".pdf") else queue.append(u))
    with open(os.path.join(OUT, "RAPPORTO.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    print("\n".join(rep)[:6000])


if __name__ == "__main__":
    main()
