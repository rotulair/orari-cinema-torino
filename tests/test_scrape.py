"""Test dei parser su HTML sintetico, costruito sulla struttura osservata nelle pagine reali.
Eseguire con:  python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import scrape  # noqa: E402

MOVIEPLAYER_HTML = """
<html><body>
<nav><a>Prossimamente</a><a>Ultime uscite</a><a>Boxoffice</a></nav>
<h1>Uci Cinemas Lingotto</h1>
<ul><li><a href="/cinema/agnelli_1434/">Agnelli</a></li></ul>
<div class="film"><h2><a href="/film/2001">2001: Odissea nello spazio</a></h2>
  <p>1968 / 139 min / Uscita ITA: 16 Novembre 2026</p>
  <span>3.5</span><span>4.8</span><span>VOTA</span>
  <ul><li>19.10 originale</li><li>18.10</li><li>21.20</li></ul></div>
<div class="film"><h2>Balcanica</h2><span>N/D</span><div>21.00</div></div>
<div class="film"><h2>Scrooge e gli spiriti del Natale</h2>
  <a>19.10</a><a>22.00</a><a>16.40</a><a>14.10</a><span>originale</span></div>
<div class="film"><h2>Senza orari</h2><p>Prossimamente</p></div>
<script>var x = "23.59";</script>
<aside><h3>Boxoffice</h3><a>Trend Se domani non torno</a></aside>
</body></html>
"""

TICKETS_HTML = """
<html><body>
<ul class="carousel"><li><a href="https://x/film/1">SE DOMANI NON TORNO</a></li></ul>
<h6><a href="https://massaua.18tickets.it/film/127289">SE DOMANI NON TORNO</a></h6>
<p><b>Regia:</b> Paola Randi</p>
<div>Lunedì 16/11/2026 <a href="http://maps.google.com/?q=PIAZZA">Massaua Cityplex</a></div>
<ul><li><a href="https://massaua.18tickets.it/film/127289/aaa#theater-init">16:50</a>
<a href="https://massaua.18tickets.it/film/127289/bbb#theater-init">21:05</a></li></ul>
<div>Martedì 17/11/2026 <a href="http://maps">Massaua Cityplex</a></div>
<ul><li><a href="https://x/film/127289/ccc#theater-init">16:50</a></li></ul>
<h6><a href="https://x/film/143822">LA STORIA INFINITA (DIE UNENDLICHE GESCHICHTE)(RIED.)</a></h6>
<div>Lunedì 16/11/2026</div>
<ul><li><a href="https://x/film/143822/ddd#theater-init">19:15 CULT</a></li></ul>
<h6><a href="https://x/film/131282">AVENGERS: DOOMSDAY</a></h6>
<div>Mercoledì 16/12/2026</div>
<ul><li><a href="https://x/film/131282/e#theater-init">00:05</a><a href="https://x/film/131282/f#theater-init">10:30</a></li></ul>
<h5>CONTATTACI</h5><p>Chiama il numero 01119901196</p>
</body></html>
"""


class MovieplayerTests(unittest.TestCase):
    def setUp(self):
        self.rows = scrape.parse_movieplayer(MOVIEPLAYER_HTML, "2026-11-16")

    def test_conteggio_e_ordine(self):
        self.assertEqual(len(self.rows), 3 + 1 + 4)

    def test_orari_e_vo(self):
        odissea = [r for r in self.rows if r["film"].startswith("2001")]
        self.assertEqual({r["time"] for r in odissea}, {"19:10", "18:10", "21:20"})
        self.assertEqual([r["tag"] for r in odissea if r["time"] == "19:10"], ["VO"])
        self.assertEqual([r["tag"] for r in odissea if r["time"] == "18:10"], [""])

    def test_originale_in_nodo_separato(self):
        scrooge = {r["time"]: r["tag"] for r in self.rows if r["film"].startswith("Scrooge")}
        self.assertEqual(scrooge["14:10"], "VO")
        self.assertEqual(scrooge["22:00"], "")

    def test_ignora_script_voti_e_film_senza_orari(self):
        films = {r["film"] for r in self.rows}
        self.assertNotIn("Senza orari", films)
        self.assertNotIn("23:59", {r["time"] for r in self.rows})
        self.assertTrue(all(r["date"] == "2026-11-16" for r in self.rows))


class TicketsTests(unittest.TestCase):
    def setUp(self):
        self.rows = scrape.parse_18tickets(TICKETS_HTML, "2026-11-16")

    def test_giorni_multipli(self):
        sdnt = [(r["date"], r["time"]) for r in self.rows if r["film"] == "SE DOMANI NON TORNO"]
        self.assertEqual(sdnt, [("2026-11-16", "16:50"), ("2026-11-16", "21:05"), ("2026-11-17", "16:50")])

    def test_etichetta_nel_link(self):
        r = next(r for r in self.rows if r["film"].startswith("LA STORIA"))
        self.assertEqual((r["date"], r["time"], r["tag"]), ("2026-11-16", "19:15", "CULT"))

    def test_mezzanotte_e_date_future(self):
        av = [(r["date"], r["time"]) for r in self.rows if r["film"].startswith("AVENGERS")]
        self.assertEqual(av, [("2026-12-16", "00:05"), ("2026-12-16", "10:30")])

    def test_carosello_non_genera_orari(self):
        self.assertEqual(len(self.rows), 3 + 1 + 2)


IDEAL_HTML = """<h1>Film in Programmazione</h1>
<h3>AVENGERS - DOOMSDAY</h3><p>Regia: A. Russo</p><a>Scheda film</a>
<ul><li>Mercoledì 16/12<ul><li>SALA 1, 15:00, INFINITY VISION</li><li>SALA 1, 21:10, INFINITY VISION</li></ul></li></ul>
<h3>GODZILLA MINUS ZERO</h3>
<ul><li>Lunedì 16/11<ul><li>SALA 2, 21:30, 2D</li><li>SALA 2, 18:00, V.O.</li></ul></li></ul>"""

MASSIMO_HTML = """<h2>Sala Uno</h2>
<p><strong>Da Giovedì 19 a Domenica 22 novembre</strong></p>
<p><strong>18.00/20.45 Look Back</strong> di Kiyotaka Oshiyama, Giappone 2024 <em>doppiato</em></p>
<p><strong>Lunedì 16 e Martedì 17 novembre</strong></p>
<p><strong>21.00 Il maestro</strong> film</p><p>v.o. sott. it.</p>
<h2>Sala Tre</h2>
<p><strong>DA MERCOLEDÌ 25 NOVEMBRE A MERCOLEDÌ 2 DICEMBRE</strong></p>
<p><strong>17.30 Segreti</strong></p>
<p><em>ingresso 7,50/5,00 euro</em></p>"""

LUX_HTML = """<h1>Programmazione DAL 12 AL 18 NOVEMBRE</h1>
<h2>2001: Odissea nello spazio (4K)</h2>
<p>Lunedì: 21:00</p><p>Martedì: 21:00</p>
<h2>Godzilla Minus Zero</h2>
<p>Giovedì: 17:00 19:30</p><p>Sabato: 15:00 21:30</p>"""

ESEDRA_HTML = """<h2>Persepolis</h2><p>Martedì 17/11/2026</p><p>h. 21:15</p><p>Mercoledì 18/11/2026</p><p>h. 17:15 - 21:15</p>
<h2>Era meglio domani</h2><p>Sabato 14/11/2026 h. 16:00 e 21:15</p>"""

BARETTI_HTML = """<p>Lunedì 16 novembre 2026, ore 21.15: <span style="background:cyan">BORN TO DIE IN BERLIN</span> di Maurizio Spagliardi [ S.O.T.TO]<br>
Martedì 17 novembre 2026, ore 21: <span>CLEO</span> di Erik Schmitt (VOS) [ Portofranco ]<br />
Lunedì 14 dicembre 2026, ore 21.15: <span>DOMANI, Il viaggio di Maysoon Majidi</span> di Vincenzo Caricari [ S.O.T.TO]</p>
<p>Mercoledì 25 novembre 2026, ore 21: IN QUOTA CAMBIA TUTTO con Farmacista in Quota [ Ferrino ]</p>
<p>Solo testo ore 10.00</p>"""

AGNELLI_HTML = """<h3>PETER PAN</h3><h2>Domenica 15 novembre ore 15:30 e 21:00</h2>
<h3>NAZA</h3><h2>16-17-18 novembre ore 19:00</h2>"""

CENTRALE_HTML = """<h2>Programmazione 12 - 18 novembre</h2><p><strong>CIVILTA PERDUTE</strong></p>
<p>GIOV 12 – 21:00</p><p>SAB 14 – 13:15 e 18:30</p><p>LUN 16 – 20:00</p>"""


def look_rows(r):
    return [x for x in r if x["film"] == "Look Back"]


IDEAL_SPLIT = """<div class="film"><b>AVENGERS - DOOMSDAY</b>
<p>Regia: Anthony Russo</p><p>Genere: Azione</p><p>Durata: 170'</p><a>Scheda film</a>
<ul><li>Mercoledì 16/12
 <ul><li><span>SALA 1</span>, <a href="/b/1">15:00</a>, <span>INFINITY VISION</span></li>
 <li><span>SALA 4</span>, <a href="/b/2">21:10</a>, <span>V.O.</span></li></ul></li></ul></div>
<div class="film"><b>GODZILLA MINUS ZERO</b><p>Durata: 135'</p>
<ul><li>Lunedì 16/11<ul><li>SALA 1, <a>21:30</a>, <span>2D</span></li></ul></li></ul></div>"""


class OfficialSiteTests(unittest.TestCase):
    D = "2026-11-16"

    def test_ideal(self):
        r = scrape.parse_ideal(IDEAL_HTML, self.D)
        self.assertEqual(len(r), 4)
        self.assertIn(("AVENGERS - DOOMSDAY", "2026-12-16", "15:00", "INFINITY VISION"),
                      [(x["film"], x["date"], x["time"], x["tag"]) for x in r])
        g = {x["time"]: x for x in r if x["film"].startswith("GODZILLA")}
        self.assertEqual((g["21:30"]["tag"], g["18:00"]["tag"]), ("", "VO"))
        self.assertEqual({x["room"] for x in r if x["film"].startswith("GODZILLA")}, {"2"})

    def test_ideal_etichette_e_valori_separati(self):
        html = ("<div><span>AVENGERS</span><p>Regia:</p><p>A. Russo</p><p>Genere:</p><p>Azione, Avventura</p>"
                "<p>Durata:</p><p>113'</p><a>Scheda film</a><ul><li>Lunedì 16/11<ul>"
                "<li><span>SALA 4</span>, <a>15:00</a>, <span>2D</span></li></ul></li></ul></div>"
                "<div><span>DOCUMENTARIO X</span><p>Genere:</p><p>Documentario</p><p>Durata:</p><p>98'</p>"
                "<ul><li>Lunedì 16/11<ul><li>SALA 3, <a>15:35</a></li></ul></li></ul></div>")
        r = scrape.parse_ideal(html, self.D)
        self.assertEqual(sorted((x["film"], x["time"], x["room"]) for x in r),
                         [("AVENGERS", "15:00", "4"), ("DOCUMENTARIO X", "15:35", "3")])

    def test_ideal_nodi_separati_senza_titoli_html(self):
        r = scrape.parse_ideal(IDEAL_SPLIT, self.D)
        got = sorted((x["film"], x["date"], x["time"], x["room"], x["tag"]) for x in r)
        self.assertEqual(got, [
            ("AVENGERS - DOOMSDAY", "2026-12-16", "15:00", "1", "INFINITY VISION"),
            ("AVENGERS - DOOMSDAY", "2026-12-16", "21:10", "4", "VO"),
            ("GODZILLA MINUS ZERO", "2026-11-16", "21:30", "1", "")])

    def test_massimo(self):
        r = scrape.parse_massimo(MASSIMO_HTML, self.D)
        look = sorted((x["date"], x["time"]) for x in r if x["film"] == "Look Back")
        self.assertEqual(len(look), 8)  # 4 giorni x 2 orari
        self.assertEqual(look[0], ("2026-11-19", "18:00"))
        maestro = [x for x in r if x["film"] == "Il maestro"]
        self.assertEqual({x["date"] for x in maestro}, {"2026-11-16", "2026-11-17"})
        self.assertTrue(all(x["tag"] == "VO" for x in maestro))
        self.assertEqual({x["room"] for x in look_rows(r)}, {"1"})
        seg = [x for x in r if x["film"] == "Segreti"]
        self.assertEqual({x["room"] for x in seg}, {"3"})
        self.assertEqual((len(seg), seg[0]["date"], seg[-1]["date"]), (8, "2026-11-25", "2026-12-02"))

    def test_movieplanet(self):
        r = scrape.parse_movieplanet(LUX_HTML, self.D)
        got = sorted((x["film"][:4], x["date"], x["time"]) for x in r)
        self.assertIn(("2001", "2026-11-16", "21:00"), got)
        self.assertIn(("2001", "2026-11-17", "21:00"), got)
        self.assertIn(("Godz", "2026-11-12", "17:00"), got)
        self.assertIn(("Godz", "2026-11-14", "21:30"), got)
        self.assertEqual(len(r), 6)

    def test_esedra(self):
        r = scrape.parse_esedra(ESEDRA_HTML, self.D)
        self.assertEqual(sorted((x["film"], x["date"], x["time"]) for x in r), [
            ("Era meglio domani", "2026-11-14", "16:00"), ("Era meglio domani", "2026-11-14", "21:15"),
            ("Persepolis", "2026-11-17", "21:15"), ("Persepolis", "2026-11-18", "17:15"),
            ("Persepolis", "2026-11-18", "21:15")])

    def test_baretti(self):
        r = scrape.parse_baretti(BARETTI_HTML, self.D)
        self.assertEqual([(x["film"], x["date"], x["time"], x["tag"]) for x in r], [
            ("BORN TO DIE IN BERLIN", "2026-11-16", "21:15", ""),
            ("CLEO", "2026-11-17", "21:00", "VO"),
            ("DOMANI, Il viaggio di Maysoon Majidi", "2026-12-14", "21:15", ""),
            ("IN QUOTA CAMBIA TUTTO", "2026-11-25", "21:00", "")])

    def test_agnelli(self):
        r = scrape.parse_agnelli(AGNELLI_HTML, self.D)
        self.assertEqual(len(r), 2 + 3)
        self.assertEqual({x["date"] for x in r if x["film"] == "NAZA"}, {"2026-11-16", "2026-11-17", "2026-11-18"})

    def test_centrale_deduce_mese_dal_giorno_settimana(self):
        r = scrape.parse_centrale(CENTRALE_HTML, self.D)
        self.assertEqual(sorted((x["date"], x["time"]) for x in r),
                         [("2026-11-12", "21:00"), ("2026-11-14", "13:15"),
                          ("2026-11-14", "18:30"), ("2026-11-16", "20:00")])

    def test_year_rollover(self):
        self.assertEqual(scrape.infer_date("2026-12-28", 3, 1), "2027-01-03")

    def test_18tickets_venue_e_follow(self):
        html = ('<h6>FILM A</h6><div>Lunedì 16/11/2026</div>'
                '<a href="https://eliseo.cctorino.18tickets.it/f/1#theater-init">20:00 VO</a>'
                '<a href="https://romano.cctorino.18tickets.it/f/1#theater-init">21:00</a>')
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            cfg = tmp / "c.json"
            cfg.write_text(json.dumps([
                {"id": "e", "name": "E", "sources": [{"type": "18tickets", "url": "http://x/", "venue": "eliseo"}]},
                {"id": "r", "name": "R", "sources": [{"type": "18tickets", "url": "http://x/", "venue": "romano"}]},
                {"id": "c", "name": "C", "sources": [{"type": "centrale", "url": "http://i/", "follow": r"/programmazione"}]},
            ]))
            calls = []

            def f(u):
                calls.append(u)
                if u == "http://i/":
                    return '<a href="/2026/11/10/programmazione-2/">x</a>'
                if u.endswith("programmazione-2/"):
                    return CENTRALE_HTML
                return html

            scrape.DELAY_SECONDS = 0
            d = scrape.run(cfg, tmp / "o.json", fetcher=f, today=self.D)
            self.assertEqual(calls.count("http://x/"), 1)
            by = {}
            for x in d["showtimes"]:
                by.setdefault(x["cinema"], []).append((x["time"], x["tag"]))
            self.assertEqual(by["e"], [("20:00", "VO")])
            self.assertEqual(by["r"], [("21:00", "")])
            self.assertEqual(by["c"], [("20:00", "")])  # 12 e 14 novembre sono passati
            self.assertNotIn("venue", d["showtimes"][0])


class FilmsTests(unittest.TestCase):
    API_OK = json.dumps({"query": {"pages": {
        "1": {"index": 2, "title": "Scrooge (serie)", "extract": "Una serie.", "fullurl": "http://w/s"},
        "2": {"index": 1, "title": "Scrooge e gli spiriti del Natale", "fullurl": "http://w/ok",
              "extract": "Scrooge e gli spiriti del Natale è un film del 2026.",
              "thumbnail": {"source": "http://img/p.jpg"}}}}})

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
        import films
        self.films = films

    def test_chiave_uguale_a_quella_della_pagina(self):
        self.assertEqual(self.films.film_key("2001: Odissea nello spazio (4K)"), "2001 odissea nello spazio")
        self.assertEqual(self.films.film_key("Perché è così"), "perche e cosi")

    def test_scelta_pagina_e_cache(self):
        calls = []

        def f(u):
            calls.append(u)
            return self.API_OK if "SCROOGE" in u.upper() else json.dumps({"query": {"pages": {
                "9": {"index": 1, "title": "Altro", "extract": "È un film.", "fullurl": "http://w/x"}}}})
        rows = [{"film": "SCROOGE E GLI SPIRITI DEL NATALE"}, {"film": "Titolo introvabile"}]
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "films.json"
            c = self.films.enrich(rows, p, f, today="2026-11-17", delay=0)
            self.assertEqual(c["scrooge e gli spiriti del natale"]["url"], "http://w/ok")
            self.assertEqual(c["scrooge e gli spiriti del natale"]["poster"], "http://img/p.jpg")
            self.assertIsNone(c["titolo introvabile"]["url"])   # pagina "Altro" scartata: titolo diverso
            n = len(calls)
            self.films.enrich(rows, p, f, today="2026-11-18", delay=0)
            self.assertEqual(len(calls), n)                      # niente ripetizioni
            self.films.enrich(rows, p, f, today="2026-11-25", delay=0)
            self.assertEqual(len(calls), n + 1)                  # solo il non trovato si riprova

    def test_errori_di_rete_non_rompono(self):
        def f(u):
            raise RuntimeError("giu")
        with tempfile.TemporaryDirectory() as t:
            c = self.films.enrich([{"film": "X Y"}], Path(t) / "f.json", f, today="2026-11-17", delay=0)
            self.assertEqual(c, {})


class RunTests(unittest.TestCase):
    def _cfg(self, tmp: Path) -> Path:
        cfg = [
            {"id": "a", "name": "A", "sources": [
                {"type": "18tickets", "label": "Sito ufficiale", "url": "http://a/"},
                {"type": "movieplayer", "label": "Movieplayer", "url": "http://a-mp/"}]},
            {"id": "b", "name": "B", "sources": [{"type": "movieplayer", "url": "http://b/"}]},
            {"id": "c", "name": "C", "sources": []},
        ]
        p = tmp / "c.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        return p

    def setUp(self):
        scrape.DELAY_SECONDS = 0

    def test_fallback_su_seconda_fonte_e_stale(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            cfg, out = self._cfg(tmp), tmp / "out.json"

            def fetcher(url):
                if url == "http://a/":
                    raise RuntimeError("giu")
                return MOVIEPLAYER_HTML

            d = scrape.run(cfg, out, fetcher=fetcher, today="2026-11-16")
            a = next(c for c in d["cinemas"] if c["id"] == "a")
            self.assertEqual(a["status"]["source"], "Movieplayer")
            self.assertEqual(a["status"]["n"], 8)
            self.assertIsNotNone(a["status"]["error"])  # il guasto resta visibile
            c = next(c for c in d["cinemas"] if c["id"] == "c")
            self.assertFalse(c["status"]["ok"])

            # secondo giro: B non risponde -> riusa i dati di ieri ancora validi (stale)
            def fetcher2(url):
                if url == "http://b/":
                    raise RuntimeError("giu")
                return MOVIEPLAYER_HTML

            d2 = scrape.run(cfg, out, fetcher=fetcher2, today="2026-11-16")
            b = next(c for c in d2["cinemas"] if c["id"] == "b")
            self.assertTrue(b["status"]["stale"])
            self.assertEqual(b["status"]["n"], 8)
            self.assertEqual(sum(1 for r in d2["showtimes"] if r["cinema"] == "b"), 8)

    def test_mode_all_non_duplica(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            cfg = tmp / "c.json"
            cfg.write_text(json.dumps([{"id": "m", "name": "M", "mode": "all", "sources": [
                {"type": "movieplayer", "url": "http://1/"}, {"type": "movieplayer", "url": "http://2/"}]}]))
            d = scrape.run(cfg, tmp / "o.json", fetcher=lambda u: MOVIEPLAYER_HTML, today="2026-11-16")
            self.assertEqual(len(d["showtimes"]), 8)

    def test_scarta_date_passate(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            d = scrape.run(self._cfg(tmp), tmp / "o.json", fetcher=lambda u: MOVIEPLAYER_HTML,
                           today="2026-11-16")
            self.assertTrue(all(r["date"] >= "2026-11-16" for r in d["showtimes"]))


if __name__ == "__main__":
    unittest.main()
