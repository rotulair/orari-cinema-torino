# Cinema Torino

Una pagina unica per consultare film, orari e programmazioni delle sale cinematografiche di Torino, aggiornata automaticamente.

Il servizio è gratuito e non richiede registrazione, server o installazione di applicazioni.

## Come funziona

Il sito raccoglie le programmazioni pubblicate dai cinema e le organizza in un'unica interfaccia.

L'aggiornamento avviene automaticamente sei volte al giorno:

- I dati vengono recuperati dai siti dei cinema.
- Le programmazioni vengono aggiornate.
- Il sito mostra i nuovi orari senza necessità di interventi manuali.

Il servizio è ospitato gratuitamente su GitHub Pages.

## Fonti dei dati

Le programmazioni vengono recuperate prioritariamente dai siti ufficiali dei cinema e dai rispettivi sistemi di biglietteria.

### Cinema inclusi

**Sistema di biglietteria 18tickets**
- Eliseo
- Romano
- Nazionale
- Fratelli Marx
- Due Giardini
- Massaua
- Reposi

**Siti ufficiali**
- Ideal Cityplex
- Cinema Massimo
- Movie Planet Lux
- Esedra
- Baretti
- Agnelli
- Centrale Arthouse

**Movieplayer**

Per alcuni cinema vengono utilizzati gli orari pubblicati su Movieplayer, quando non è possibile recuperare direttamente quelli dai siti ufficiali:

- The Space
- UCI Lingotto
- Greenwich Village
- Classico

In questi casi, il sito segnala chiaramente la provenienza dei dati con la dicitura «da Movieplayer».

È sempre disponibile il collegamento al sito ufficiale del cinema per verificare la programmazione.

## Aggiornamento e affidabilità

Le programmazioni vengono aggiornate automaticamente sei volte al giorno.

La disponibilità degli orari dipende dalle informazioni pubblicate dalle singole fonti:

- Quando un cinema pubblica più giorni di programmazione, vengono mostrati tutti quelli disponibili.
- Quando pubblica soltanto gli orari del giorno corrente, vengono mostrati esclusivamente quelli.
- Se una fonte non risponde, vengono mantenuti gli ultimi dati validi e viene mostrato un avviso di mancato aggiornamento.

Gli orari visualizzati possono subire variazioni. Per informazioni definitive e acquisto dei biglietti è sempre consigliabile consultare il sito ufficiale del cinema.

## Schede dei film e informazioni aggiuntive

Ogni film può avere una scheda dedicata con informazioni provenienti da TMDB e Wikipedia.

Quando disponibili, vengono mostrati:

- Locandina
- Titolo originale
- Genere
- Anno di uscita
- Durata
- Regia
- Trama
- Cast

Sono inoltre presenti i collegamenti alle schede del film su Wikipedia e TMDB.

Per evitare associazioni errate tra film omonimi, il sistema verifica la corrispondenza del titolo e, quando disponibili, del regista e dell'anno di uscita.

Se non viene individuata una corrispondenza sufficientemente affidabile, il film può essere visualizzato senza scheda informativa.

## Navigazione tra i giorni

Aprendo la scheda di un film è possibile consultare i giorni in cui è programmato.

Selezionando una data vengono mostrati tutti i cinema che proiettano quel film e i relativi orari.

È possibile cambiare giorno anche senza utilizzare le linguette:

- **Smartphone:** scorrendo la pagina verso destra o sinistra.
- **Computer:** utilizzando le frecce direzionali `←` e `→`.

## Navigazione tra film e cinema

Il sito permette di passare direttamente dalla programmazione di un cinema alla scheda di un film e viceversa.

- Toccando il nome di un cinema nella scheda di un film si apre la programmazione della sala.
- La freccia `↗` accanto al cinema permette di visitare il suo sito ufficiale.
- Toccando un film nella programmazione di un cinema si apre la relativa scheda.

Per tornare alla schermata precedente è disponibile il comando **«← Indietro»**. È supportato anche il normale tasto Indietro dello smartphone.

## Informazioni sulle sale

Quando il dato è disponibile nella fonte originale, accanto all'orario viene indicato anche il numero della sala (ad esempio `S2`).

Attualmente questa informazione è disponibile per Ideal Cityplex e Cinema Massimo.

Per gli altri cinema il dato non è disponibile nelle fonti utilizzate.

## Tecnologia e sviluppo

Il progetto utilizza tecnologie gratuite e aperte:

- **Python:** recupero e organizzazione delle programmazioni.
- **GitHub Actions:** esecuzione automatica degli aggiornamenti.
- **GitHub Pages:** pubblicazione del sito.
- **JSON:** archiviazione dei dati delle programmazioni e delle schede dei film.
- **TMDB e Wikipedia:** recupero delle informazioni cinematografiche.

Non è necessario un server dedicato né un database esterno.

### Personalizzazione e miglioramenti

Il progetto può essere ampliato e modificato, ad esempio per:

- Aggiungere altri cinema di Torino o di altre città.
- Integrare nuove fonti di programmazione.
- Migliorare il recupero degli orari.
- Aggiungere informazioni sulle sale.
- Arricchire le schede dei film.
- Modificare l'interfaccia e le modalità di navigazione.

Il codice e le configurazioni sono organizzati per consentire l'aggiunta di nuove fonti e funzionalità.
