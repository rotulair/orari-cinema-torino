# Cinema Torino

**Tutti i film e gli orari delle sale di Torino in un'unica pagina**, aggiornata automaticamente dai siti ufficiali dei cinema. Pensata per programmare la settimana al cinema da telefono, da tenere nei preferiti del browser. Gratuita, senza server, senza account e senza pubblicità.

Creato da **rotulair**.

## Cosa fa

### Programmazione
- **18 cinema** di Torino nello stesso posto: Ideal Cityplex, Massaua Cityplex, Reposi, The Space Parco Dora, UCI Lingotto, Eliseo, Fratelli Marx, Romano, Nazionale, Cinema Massimo, Movie Planet Lux, Centrale Arthouse, Classico, Greenwich Village, Due Giardini, Esedra, Baretti, Agnelli.
- **Aggiornamento automatico** 6 volte al giorno, leggendo i siti ufficiali (pagine web, sistema di biglietteria e PDF dei programmi settimanali).
- **Settimana intera**: barra dei giorni con la settimana corrente, pulsante "Più avanti" per guardare oltre, scorrimento orizzontale tra i giorni (frecce ← → sul computer).
- **Solo da ora**: nasconde gli spettacoli già iniziati; il prossimo spettacolo è evidenziato.
- **Sala e versione**: dove il sito la indica compare la sala (S1, S2…) e il tag VO per la versione originale.
- **Nessun doppione**: titoli scritti in modo diverso dai vari cinema ("Titolo [2026]", "Titolo – V.O.", refusi dei PDF) vengono riconosciuti come lo stesso film e uniti.

### Due modi di guardare
- **Film**: ogni film con i cinema e gli orari in cui lo danno.
- **Cinema**: ogni cinema con logo, indirizzo (tocco = apre Maps), link al sito ufficiale e i suoi film.
- Toccando il nome di un cinema in un film, o un film in un cinema, si passa all'altra vista; **← Indietro** (e il tasto Indietro del telefono) riporta dov'eri.

### Scheda film
- **Locandina** (a tutto schermo con un tocco), titolo, anno, regia e durata.
- **Trama** accanto alla locandina, con "Leggi tutto" per la trama completa, il cast e i link a Wikipedia e TMDB.
- **Altri giorni**: i giorni in cui lo stesso film è in programma, con cinema e orari.
- Da chiusa, la scheda mostra i prossimi orari e i cinema che lo proiettano.
- I dati vengono da TMDB e Wikipedia con **controllo incrociato** (titolo, regista, anno) per non attaccare al film la scheda di un omonimo; se i dati non combaciano non compare nessuna scheda.

### Comodità
- **La mia zona**: scegli il quartiere in cui ti trovi e i cinema si ordinano per distanza, con i metri o i chilometri accanto all'indirizzo. La scelta resta sul tuo dispositivo; il sito non legge mai la posizione.
- **Cerca** un film per titolo e **filtra** i cinema da mostrare.
- Tema scuro o chiaro in base al telefono; si aggiorna da solo quando riapri la pagina.

## Da sapere
- **The Space e UCI Lingotto**: i loro siti bloccano la lettura automatica, quindi si vedono solo gli orari di **oggi** (da Movieplayer). Per gli altri giorni la pagina rimanda al sito ufficiale. Lo stesso vale per **Greenwich Village** e **Classico** se il loro PDF non è leggibile.
- **Greenwich Village e Classico** pubblicano un PDF a settimana, scritto a mano: la programmazione dei giorni successivi appare quando il PDF nuovo viene pubblicato.
- Gli orari possono cambiare: la pagina lo ricorda sempre, e ogni cinema ha il suo link "Sito ufficiale" per controllare.
- Se un sito non risponde restano gli ultimi dati validi, con un avviso "orari non aggiornati".

## Come funziona
- `scraper/scrape.py` scarica la programmazione e scrive `data/showtimes.json`; `scraper/films.py` aggiunge le schede film (`data/films.json`); `scraper/geo.py` trova le coordinate dei cinema (`data/coordinates.json`).
- **GitHub Actions** (`.github/workflows/aggiorna.yml`) lo esegue 6 volte al giorno, lancia i test e salva i dati nel repository. Se un test fallisce, non pubblica.
- **GitHub Pages** pubblica `index.html`, che legge i file in `data/`. Nessun server.
- Pagina in HTML, CSS e JavaScript puri (nessun framework); scraper in Python con sola libreria standard.

## Pubblicare la propria copia
1. Crea un repository **pubblico** su GitHub (serve per Pages gratuito; contiene solo orari di cinema).
2. **Add file → Upload files**: carica tutto, comprese le cartelle `.github`, `scraper`, `tests` e `data`. Se `.github` non si carica, crea a mano `.github/workflows/aggiorna.yml` con **Add file → Create new file**.
3. **Settings → Pages**: *Deploy from a branch*, branch `main`, cartella `/ (root)`.
4. **Actions → Aggiorna programmazione → Run workflow** (la prima volta, per generare i dati; la prima volta impiega un minuto in più per le coordinate).
5. Il sito è su `https://TUO-UTENTE.github.io/NOME-REPO/`: aggiungilo ai preferiti.

### Chiave TMDB (facoltativa, per locandine, durata, regia, trama e cast)
1. Account gratuito su [themoviedb.org](https://www.themoviedb.org/), poi *Settings → API*: copia l'"API Read Access Token".
2. Nel repository: *Settings → Secrets and variables → Actions → New repository secret*, nome `TMDB_TOKEN`.
3. Senza chiave tutto funziona lo stesso, solo con Wikipedia.

## Manutenzione
- **Aggiungere o correggere un cinema**: tutto sta in `scraper/cinemas.json`. Ogni cinema ha una lista di `sources` provate in ordine; i tipi disponibili sono `18tickets` (con `venue`), `ideal`, `massimo`, `movieplanet`, `esedra`, `baretti`, `agnelli`, `centrale` (con `follow`), `grantorino` (PDF di Greenwich e Classico) e `movieplayer`. Un sito nuovo richiede un parser in `scrape.py`, dentro `PARSERS`.
- **Provare in locale**: `python scraper/scrape.py --only ID --debug-dir debug`; test con `python -m unittest discover -s tests`. I PDF richiedono `poppler-utils` (`pdftotext`).
- **Loghi propri**: carica le immagini in `logos/` e crea `logos/index.json`, ad esempio `{"ideal": "ideal.png"}` (le chiavi sono gli `id` dei cinema). Di base si usa la favicon del sito o una sigla colorata.
- **Correggere la posizione di un cinema**: modifica `data/coordinates.json` e aggiungi `"manual": true`.
- **Strumenti di esplorazione** (`scraper/esplora.py`, `sonda*.py` e relativi workflow): servono solo a studiare nuove fonti, non fanno parte dell'aggiornamento.
- **Inattività**: GitHub sospende i workflow pianificati dopo 60 giorni senza attività nel repository; riattivali dalla scheda Actions.

## Crediti e note
- Orari: siti ufficiali dei cinema; Movieplayer come ripiego per gli orari di oggi.
- Locandine, trame, cast e registi: [TMDB](https://www.themoviedb.org/) e [Wikipedia](https://it.wikipedia.org/). *This product uses the TMDB API but is not endorsed or certified by TMDB.*
- Coordinate dei cinema: © contributori di [OpenStreetMap](https://www.openstreetmap.org/copyright). Font: [Inter](https://rsms.me/inter/).
- Progetto personale e non ufficiale, non affiliato ai cinema. Lo scraper fa poche richieste, con pause; controlla i termini d'uso dei siti prima di condividere pubblicamente la pagina.
- Creato da **rotulair**, con l'aiuto di Claude (Anthropic).

