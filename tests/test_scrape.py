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
        self.assertEqual([x.get("regia") for x in sorted(r, key=lambda x: x["film"])], ["A. Russo", None])
        one = scrape.parse_ideal(IDEAL_HTML, self.D)
        self.assertEqual({x["regia"] for x in one if x["film"].startswith("AVENGERS")}, {"A. Russo"})

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

    def test_baretti_regia(self):
        r = {x["film"]: x.get("regia") for x in scrape.parse_baretti(BARETTI_HTML, self.D)}
        self.assertEqual(r["BORN TO DIE IN BERLIN"], "Maurizio Spagliardi")
        self.assertEqual(r["CLEO"], "Erik Schmitt")
        self.assertEqual(r["DOMANI, Il viaggio di Maysoon Majidi"], "Vincenzo Caricari")
        self.assertIsNone(r["IN QUOTA CAMBIA TUTTO"])  # "con ..." sono ospiti, non regia

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

    def test_regista_da_wikipedia(self):
        d = self.films.director_of
        self.assertEqual(d("Se domani non torno è un film del 2026 diretto da Paola Randi, con Elio Germano."), "Paola Randi")
        self.assertEqual(d("X è un film d'animazione scritto e diretto da Anthony e Joe Russo."), "Anthony e Joe Russo")
        self.assertEqual(d("Persepolis è un film del 2007 diretto da Marjane Satrapi e Vincent Paronnaud (tratto da fumetto)."),
                         "Marjane Satrapi e Vincent Paronnaud")
        self.assertIsNone(d("Una serie televisiva americana."))
        self.assertEqual(d("2001 è un film del 1968 diretto da Stanley Kubrick, che ha curato anche gli effetti."), "Stanley Kubrick")
        self.assertEqual(d("Look Back (ルックバック, Rukku bakku) è un film del 2026 diretto, sceneggiato e montato da Hirokazu Kore'eda."),
                         "Hirokazu Kore'eda")
        self.assertEqual(d("Il film è diretto e sceneggiato da Wes Anderson."), "Wes Anderson")
        self.assertEqual(d("Un film del 2026 scritto, prodotto e diretto da Greta Gerwig, con Saoirse Ronan."), "Greta Gerwig")
        self.assertEqual(d("È un film scritto e prodotto da Mario Rossi e diretto da Luca Bianchi."), "Luca Bianchi")
        self.assertEqual(d("Un film diretto da J. J. Abrams e prodotto da Bad Robot."), "J. J. Abrams")
        self.assertEqual(d("Un film del 2026 per la regia di Ferzan Özpetek."), "Ferzan Özpetek")

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


class UnifyTests(unittest.TestCase):
    def test_anno_tra_parentesi_diventa_campo(self):
        rows = [{"film": "Cleo [2026]"}, {"film": "Cleo"}]
        scrape.unify_titles(rows)
        self.assertEqual([r.get("anno") for r in rows], [2026, None])

    def test_anno_formati_articoli_maiuscole(self):
        rows = [{"cinema": "a", "film": "Scrooge e gli spiriti del Natale [2026]"},
                {"cinema": "b", "film": "SCROOGE E GLI SPIRITI DEL NATALE"},
                {"cinema": "c", "film": "Scrooge e gli spiriti del Natale (4K)"},
                {"cinema": "d", "film": "Il maestro"}, {"cinema": "e", "film": "MAESTRO (RIED.)"},
                {"cinema": "f", "film": "L'hangar rosso"}, {"cinema": "g", "film": "L’HANGAR ROSSO"}]
        scrape.unify_titles(rows)
        self.assertEqual({r["film"] for r in rows[:3]}, {"Scrooge e gli spiriti del Natale"})
        self.assertEqual(rows[3]["film"], rows[4]["film"])
        self.assertEqual(rows[5]["film"], rows[6]["film"])
        self.assertNotIn("[", rows[0]["film"])

    def test_suffisso_vo_edizioni_e_segnaposto(self):
        rows = [{"film": "WILD HORSE NINE - V. O.", "cinema": "a"}, {"film": "Wild horse nine", "cinema": "b"},
                {"film": "FJORD - V. O.", "cinema": "a"},
                {"film": "2001: ODISSEA NELLO SPAZIO 4K – WB 100TH ANNIVERSARY (2001: A SPACE ODISSEY)", "cinema": "a"},
                {"film": "2001: Odissea nello spazio", "cinema": "b"}]
        scrape.unify_titles(rows)
        self.assertEqual(rows[0]["film"], rows[1]["film"])
        self.assertEqual(rows[0]["film"], "Wild horse nine")
        self.assertEqual((rows[0].get("tag"), rows[1].get("tag")), ("VO", None))
        self.assertEqual(rows[2]["film"], "FJORD")
        self.assertEqual(rows[3]["film"], rows[4]["film"])
        self.assertEqual(rows[3]["film"], "2001: Odissea nello spazio")
        for j in ("n.d.", "N/D", "113'", "Sala 3", "-", ""):
            self.assertTrue(scrape.is_junk_title(j), j)
        self.assertFalse(scrape.is_junk_title("Fjord"))
        self.assertFalse(scrape.is_junk_title("2001: Odissea"))

    def test_lux_ignora_nd_come_titolo(self):
        html = ("<h1>DAL 12 AL 18 NOVEMBRE</h1><h2>Il film vero</h2><p>n.d.</p><p>Martedì: 21:15</p>")
        r = scrape.parse_movieplanet(html, "2026-11-16")
        self.assertEqual([(x["film"], x["date"], x["time"]) for x in r], [("Il film vero", "2026-11-17", "21:15")])

    def test_film_diversi_restano_separati(self):
        rows = [{"film": "Toy Story 2"}, {"film": "Toy Story 3"}, {"film": "Toy Story"},
                {"film": "Cleo"}, {"film": "Cleo e Leo"}, {"film": "Mission Impossible"},
                {"film": "Mission Impossible Dead Reckoning"}]
        before = [r["film"] for r in rows]
        scrape.unify_titles(rows)
        self.assertEqual([r["film"] for r in rows], before)

    def test_refusi_e_typo_vicini(self):
        rows = [{"film": "La vallée des fous"}, {"film": "LA VALLEE DES FOUS"}, {"film": "Persepolis"}, {"film": "Perspolis"}]
        scrape.unify_titles(rows)
        self.assertEqual(rows[0]["film"], rows[1]["film"])
        self.assertEqual(rows[2]["film"], rows[3]["film"])

    def test_run_non_duplica_dopo_unione(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            cfg = tmp / "c.json"
            cfg.write_text(json.dumps([{"id": "m", "name": "M", "mode": "all", "sources": [
                {"type": "baretti", "url": "http://1/"}, {"type": "baretti", "url": "http://2/"}]}]))
            pages = {"http://1/": "<p>Lunedì 16 novembre 2026, ore 21.15: <span>CLEO [2026]</span> di X</p>",
                     "http://2/": "<p>Lunedì 16 novembre 2026, ore 21.15: <span>CLEO</span> di X</p>"}
            scrape.DELAY_SECONDS = 0
            d = scrape.run(cfg, tmp / "o.json", fetcher=pages.__getitem__, today="2026-11-16")
            self.assertEqual(len(d["showtimes"]), 1)


def fake_tmdb(table):
    """table: {id: (title, original, year, [registi], runtime, poster)}"""
    def fetch(url):
        if "/search/movie" in url:
            return json.dumps({"results": [{"id": i, "title": v[0], "original_title": v[1],
                                             "release_date": f"{v[2]}-05-01", "popularity": 5}
                                            for i, v in table.items()]})
        i = int(url.split("/movie/")[1].split("?")[0])
        v = table[i]
        return json.dumps({"id": i, "release_date": f"{v[2]}-05-01", "runtime": v[4], "poster_path": v[5],
                           "popularity": 5, "overview": f"Trama di {v[0]} {v[2]}.", "genres": [{"name": "Drammatico"}],
                           "original_title": v[1],
                           "credits": {"crew": [{"job": "Director", "name": n} for n in v[3]]
                                       + [{"job": "Writer", "name": "Altro Nome"}],
                                       "cast": [{"name": "Attore Uno"}, {"name": "Attrice Due"}]}})
    return fetch


class TmdbTests(unittest.TestCase):
    OMONIMI = {1: ("Cleo", "Cleo", 2023, ["Mario Rossi"], 90, "/old.jpg"),
               2: ("Cleo", "Cleo", 2026, ["Erik Schmitt"], 98, "/new.jpg")}

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
        import films
        self.films = films

    def run_enrich(self, rows, table, wiki_json=None):
        wiki = wiki_json or json.dumps({"query": {"pages": {}}})
        with tempfile.TemporaryDirectory() as t:
            c = self.films.enrich(rows, Path(t) / "f.json", lambda u: wiki, today="2026-11-17", delay=0,
                                  tmdb=fake_tmdb(table))
        return next(iter(c.values()))

    def test_omonimi_si_sceglie_col_regista(self):
        e = self.run_enrich([{"film": "Cleo", "regia": "Erik Schmitt"}], self.OMONIMI)
        self.assertEqual((e["tmdb"]["id"], e["tmdb"]["runtime"], e["tmdb"]["poster_path"]), (2, 98, "/new.jpg"))
        self.assertEqual(e["tmdb"]["director"], "Erik Schmitt")
        self.assertEqual((e["tmdb"]["overview"], e["tmdb"]["genres"], e["tmdb"]["cast"]),
                         ("Trama di Cleo 2026.", ["Drammatico"], ["Attore Uno", "Attrice Due"]))

    def test_regista_non_combacia_nessun_link(self):
        e = self.run_enrich([{"film": "Cleo", "regia": "Giulia Verdi"}], self.OMONIMI)
        self.assertIsNone(e["tmdb"])

    def test_anno_scarta_omonimo_senza_regista(self):
        e = self.run_enrich([{"film": "Cleo", "anno": 2026}], self.OMONIMI)
        self.assertEqual(e["tmdb"]["id"], 2)

    def test_regista_wikipedia_guida_tmdb(self):
        wiki = json.dumps({"query": {"pages": {"1": {"index": 1, "title": "Cleo (film 2026)",
                           "extract": "Cleo è un film del 2026 diretto da Erik Schmitt.", "fullurl": "http://w/c"}}}})
        e = self.run_enrich([{"film": "Cleo"}], self.OMONIMI, wiki)
        self.assertEqual((e["url"], e["tmdb"]["id"]), ("http://w/c", 2))

    def test_wikipedia_scartata_se_regista_del_cinema_diverso(self):
        wiki = json.dumps({"query": {"pages": {"1": {"index": 1, "title": "Cleo (film 2023)",
                           "extract": "Cleo è un film del 2023 diretto da Mario Rossi.", "fullurl": "http://w/old"}}}})
        e = self.run_enrich([{"film": "Cleo", "regia": "Erik Schmitt"}], self.OMONIMI, wiki)
        self.assertIsNone(e["url"])
        self.assertEqual(e["tmdb"]["id"], 2)

    def cand(self, id, year, directors, sim=1.0, release=None):
        return {"id": id, "sim": sim, "year": year, "popularity": 1, "poster_path": "/p.jpg", "runtime": 100,
                "directors": directors, "overview": "x", "genres": [], "cast": [], "original_title": "x",
                "release_date": release or f"{year}-06-01"}

    def test_look_back_anime_2014_non_per_il_live_action_2026(self):
        import datetime as dt
        today = dt.date(2026, 11, 17)
        anime = self.cand(1, 2024, ["Kiyotaka Oshiyama"])
        # nessun riscontro (ne' regista ne' anno): un film del 2024 non e' "recente" -> scartato
        w, t, note = self.films.decide("Look Back", None, None, None, [anime], today)
        self.assertIsNone(t)
        self.assertIn("non recente", note)
        # Wikipedia dice 2026: l'anno del 2024 non coincide
        wiki = {"url": "http://w", "director": "Hirokazu Kore'eda", "year": 2026, "extract": ""}
        w, t, note = self.films.decide("Look Back", None, None, wiki, [anime], today)
        self.assertIsNone(t)
        self.assertEqual(w["url"], "http://w")
        # se TMDB ha anche il live action 2026 con lo stesso regista, si sceglie quello
        live = self.cand(2, 2026, ["Hirokazu Koreeda"])
        w, t, note = self.films.decide("Look Back", None, None, wiki, [anime, live], today)
        self.assertEqual(t["id"], 2)

    def test_film_vecchi_solo_se_confermati_o_riedizioni(self):
        import datetime as dt
        today = dt.date(2026, 11, 17)
        old = self.cand(62, 1968, ["Stanley Kubrick"])
        self.assertIsNone(self.films.decide("2001", None, None, None, [old], today)[1])
        self.assertEqual(self.films.decide("2001", "Stanley Kubrick", None, None, [old], today)[1]["id"], 62)
        self.assertEqual(self.films.decide("2001", None, None, None, [old], today, rerelease=True)[1]["id"], 62)

    def test_ambiguita_e_omonimi_recenti(self):
        import datetime as dt
        today = dt.date(2026, 11, 17)
        a, b = self.cand(1, 2026, ["A Rossi"]), self.cand(2, 2026, ["B Verdi"])
        _, t, note = self.films.decide("Hope", None, None, None, [a, b], today)
        self.assertIsNone(t)
        self.assertIn("ambiguo", note)
        self.assertEqual(self.films.decide("Hope", "B Verdi", None, None, [a, b], today)[1]["id"], 2)
        self.assertEqual(self.films.decide("Hope", None, 2026, None, [self.cand(1, 2019, ["A Rossi"]), b], today)[1]["id"], 2)

    def test_wikipedia_scartata_se_anno_o_regista_non_tornano(self):
        import datetime as dt
        wiki = {"url": "http://w", "director": None, "year": 2014, "extract": "Un film del 2014."}
        w, t, note = self.films.decide("X Y", None, 2026, wiki, [], dt.date(2026, 11, 17))
        self.assertIsNone(w)
        wiki2 = {"url": "http://w", "director": None, "year": None, "extract": "Un film. Con Mario Bianchi."}
        self.assertIsNone(self.films.decide("X Y", "Luca Verdi", None, wiki2, [], dt.date(2026, 11, 17))[0])
        self.assertIsNotNone(self.films.decide("X Y", "Mario Bianchi", None, wiki2, [], dt.date(2026, 11, 17))[0])

    def test_cognomi_e_alfabeti(self):
        m = self.films.surname_match
        self.assertTrue(m("Hirokazu Kore'eda", ["Hirokazu Koreeda"]))
        self.assertTrue(m("Anthony e Joe Russo", ["Joe Russo", "Anthony Russo"]))
        self.assertFalse(m("Paolo Sorrentino", ["Paolo Genovese"]))
        self.assertIsNone(m(None, ["X Y"]))

    def test_errore_rete_tmdb_non_rompe(self):
        def boom(u):
            raise RuntimeError("giu")
        with tempfile.TemporaryDirectory() as t:
            c = self.films.enrich([{"film": "Cleo"}], Path(t) / "f.json", lambda u: "{}", today="2026-11-17",
                                  delay=0, tmdb=boom)
        # l'errore TMDB non butta via il resto: il film resta salvato (senza TMDB) e verra' riprovato
        self.assertEqual((c["cleo"]["t"], c["cleo"]["tmdb"]), (False, None))


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



class GranTorinoPdfTest(unittest.TestCase):
    """PDF reali di Circuito Gran Torino (testo con coordinate salvato in tests/fixtures)."""
    FIX = Path(__file__).resolve().parent / "fixtures"

    def test_greenwich_sale_e_giorni(self):
        xml = (self.FIX / "greenwich_bbox.xml").read_text(encoding="utf-8")
        rows = scrape.parse_grantorino_pdf(xml, "2026-11-18", "greenwich")
        self.assertEqual(len(rows), 84)                      # 7 giorni x 12 spettacoli
        self.assertEqual({r["date"] for r in rows}, {f"2026-11-{d}" for d in range(19, 26)})
        g = {(r["date"], r["time"], r["room"]): r for r in rows}
        self.assertEqual(g[("2026-11-19", "15:30", "2")]["film"], "MINOTAURO")
        self.assertEqual(g[("2026-11-19", "21:15", "3")]["film"], "PRIMETIME")
        self.assertEqual(g[("2026-11-19", "21:15", "3")]["tag"], "VO")
        self.assertEqual(g[("2026-11-19", "15:30", "3")]["tag"], "")
        self.assertEqual(g[("2026-11-23", "18:00", "3")]["film"], "DIGGER")
        self.assertEqual(g[("2026-11-25", "21:15", "3")]["film"], "HOPE")
        self.assertEqual(g[("2026-11-21", "15:45", "1")]["film"], "L'ESSERE AMATO (EL SER QUERIDO)")
        self.assertTrue(all(r["venue"] == "greenwich" for r in rows))

    def test_classico_refuso_nella_data(self):
        xml = (self.FIX / "classico_bbox.xml").read_text(encoding="utf-8")
        rows = scrape.parse_grantorino_pdf(xml, "2026-11-18", "classico")
        self.assertEqual(len(rows), 21)
        self.assertIn("2026-11-16", {r["date"] for r in rows})   # nel PDF c'e' scritto "16/101"
        self.assertEqual(sorted((r["time"], r["tag"]) for r in rows if r["date"] == "2026-11-18"),
                         [("15:45", ""), ("18:15", "VO"), ("20:45", "VO")])
        self.assertTrue(all(r["room"] == "" if "room" in r else True for r in rows))

    def test_home_con_link_ai_pdf(self):
        home = ('<a href="https://x.it/wp-content/PROGRAMMAZIONE-CINEMA-CLASSICO-DAL-12-AL-18.pdf">Programmazione Classico</a>'
                '<a href="https://x.it/RETTIFICA-GREENWICH-VILLAGE.pdf">Programmazione Greenwich Village</a>'
                '<a href="https://x.it/altro.pdf">Tariffe</a>')
        fx = {"CLASSICO": "classico_bbox.xml", "GREENWICH": "greenwich_bbox.xml"}
        old = scrape.PDF_BBOX
        scrape.PDF_BBOX = lambda url: (self.FIX / fx[next(k for k in fx if k in url)]).read_text(encoding="utf-8")
        try:
            rows = scrape.parse_grantorino(home, "2026-11-18")
        finally:
            scrape.PDF_BBOX = old
        self.assertEqual({r["venue"] for r in rows}, {"classico", "greenwich"})
        self.assertEqual(len(rows), 105)

    def test_un_pdf_rotto_non_blocca_l_altro(self):
        home = ('<a href="https://x.it/CLASSICO.pdf">Classico</a><a href="https://x.it/GREENWICH.pdf">Greenwich</a>')
        def fake(url):
            if "CLASSICO" in url:
                raise RuntimeError("giu'")
            return (self.FIX / "greenwich_bbox.xml").read_text(encoding="utf-8")
        old = scrape.PDF_BBOX; scrape.PDF_BBOX = fake
        try:
            rows = scrape.parse_grantorino(home, "2026-11-18")
        finally:
            scrape.PDF_BBOX = old
        self.assertEqual({r["venue"] for r in rows}, {"greenwich"})

if __name__ == "__main__":
    unittest.main()
