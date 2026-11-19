"""Sonda 2 (una tantum): prova a leggere le pagine ufficiali di UCI Lingotto e The Space passando da altre strade
(intestazioni da browser vero, servizi di lettura pubblici, archivio web) e dice se compaiono piu' giorni."""
from __future__ import annotations
import gzip, os, re, urllib.parse, urllib.request, urllib.error

OUT = os.path.join("out", "sonda2")
UCI = "https://www.ucicinemas.it/cinema/piemonte/torino/uci-cinemas-torino-lingotto/"
SPACE = "https://www.thespacecinema.it/cinema/torino/al-cinema"
BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8", "Accept-Encoding": "gzip", "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
}


def translate_host(url: str) -> str:
    u = urllib.parse.urlparse(url)
    host = u.netloc.replace("-", "--").replace(".", "-")
    return f"https://{host}.translate.goog{u.path}?_x_tr_sl=it&_x_tr_tl=en&_x_tr_hl=en"


def routes(url: str):
    q = urllib.parse.quote(url, safe="")
    yield "diretto (headers da browser)", url, BROWSER
    yield "r.jina.ai", "https://r.jina.ai/" + url, {"User-Agent": BROWSER["User-Agent"], "Accept": "text/html"}
    yield "allorigins", "https://api.allorigins.win/raw?url=" + q, {"User-Agent": BROWSER["User-Agent"]}
    yield "corsproxy.io", "https://corsproxy.io/?" + q, {"User-Agent": BROWSER["User-Agent"]}
    yield "google translate", translate_host(url), BROWSER
    yield "web.archive.org", "https://web.archive.org/web/2/" + url, {"User-Agent": BROWSER["User-Agent"]}


def get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return r.status, data


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = []
    for site, url in (("UCI", UCI), ("SPACE", SPACE)):
        for route, u, h in routes(url):
            name = re.sub(r"[^a-z0-9]+", "_", f"{site}_{route}".lower()).strip("_")
            try:
                st, data = get(u, h)
            except urllib.error.HTTPError as e:
                rep.append(f"[{site} / {route}] HTTP {e.code}"); continue
            except Exception as e:
                rep.append(f"[{site} / {route}] ERRORE {e}"); continue
            txt = data.decode("utf-8", "replace")
            plain = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", "", txt))
            times = re.findall(r"(?<!\d)(?:[01]?\d|2[0-3])[:.][0-5]\d(?!\d)", plain)
            dates = sorted(set(re.findall(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", plain)))[:12]
            words = len(re.findall(r"(?i)lingotto|parco dora|torino", plain))
            open(os.path.join(OUT, name + ".html"), "wb").write(data[:900_000])
            rep.append(f"[{site} / {route}] HTTP {st} {len(data)}B  orari:{len(times)}  parole-chiave:{words}  date:{dates}  -> {name}.html")
    open(os.path.join(OUT, "RAPPORTO.txt"), "w", encoding="utf-8").write("\n".join(rep))
    print("\n".join(rep))


if __name__ == "__main__":
    main()
