# Cinema Torino

Una pagina unica con film e orari delle sale di Torino, che si aggiorna da sola. 

Come funziona:

- `scraper/scrape.py` scarica la programmazione e scrive `data/showtimes.json`.
- GitHub Actions lo esegue 6 volte al giorno (`.github/workflows/aggiorna.yml`) e salva il file aggiornato nel repository.
- GitHub Pages pubblica `index.html`, che legge quel file.

## Cosa aspettarsi

- **Fonti: siti ufficiali, con Movieplayer solo dove il sito ufficiale non è leggibile.**
  - Sistema di biglietteria dei cinema (18tickets, lo stesso del sito del cinema): Eliseo, Romano, Nazionale, Fratelli Marx, Due Giardini, Massaua, Reposi.
  - Pagine dei cinema: Ideal Cityplex, Cinema Massimo (calendario completo), Movie Planet Lux, Esedra, Baretti, Agnelli, Centrale Arthouse (ultimo post del blog).
  - **Movieplayer (solo orari di oggi)** per The Space, UCI Lingotto, Greenwich Village e Classico: i loro siti caricano gli orari con JavaScript o in PDF. Sul sito compare l'indicazione "da Movieplayer" e ogni cinema ha comunque il link "Sito ufficiale" per verificare.
- **Giorni.** Dove il sito mostra più giorni (quasi tutti) compaiono tutti; se ne mostra uno solo, vedrai solo quello.
- **Guasti.** Se un sito non risponde, restano gli ultimi dati validi con un avviso "orari non aggiornati". Se non esce nessun orario da nessun cinema, il workflow fallisce e GitHub ti manda una mail. Nella scheda Actions trovi l'HTML scaricato (artifact `html-debug`) per capire cosa è cambiato.
- **Inattività.** GitHub può sospendere i workflow pianificati dopo 60 giorni senza attività nel repository. In quel caso riattivali dalla scheda Actions.
- **Uso personale.** Lo scraper fa poche richieste, con pause. Controlla i termini d'uso dei siti prima di condividere pubblicamente la pagina.

## Aggiungere o correggere un cinema

Tutto sta in `scraper/cinemas.json`. Ogni cinema ha una lista di `sources` provate in ordine:

```json
{"type": "movieplayer", "url": "https://movieplayer.it/cinema/..."}
```

I tipi disponibili sono `18tickets` (con `venue` per filtrare un cinema su un sito condiviso), `ideal`, `massimo`, `movieplanet`, `esedra`, `baretti`, `agnelli`, `centrale` (con `follow`, un'espressione regolare per aprire l'ultimo post) e `movieplayer` (non usato). Per un sito nuovo serve un parser in `scrape.py`, dentro `PARSERS`. Provalo in locale con `python scraper/scrape.py --only ID --debug-dir debug` e lancia i test con `python -m unittest discover -s tests`.

## Sale
Dove la fonte la indica compare la sala accanto all'orario (es. `S2`): oggi per Ideal Cityplex e Cinema Massimo. Per gli altri la fonte non la espone in modo che io abbia potuto verificare.

## Schede film e locandine
Ogni film ha un link alla scheda Wikipedia (e la locandina, se Wikipedia ce l'ha); se non la trova, il link porta a una ricerca Google. Le ricerche si salvano in `data/films.json` (non si ripetono) e sono un passaggio facoltativo: se falliscono, gli orari si aggiornano lo stesso. Il match è prudente (il titolo deve combaciare e la pagina deve parlare di un film), quindi qualche film uscirà senza scheda piuttosto che con quella sbagliata.
