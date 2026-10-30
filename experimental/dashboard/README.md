# Immution dashboards (experimental)

For the **live read-only terminal dashboard**, see [LIVE.md](LIVE.md).
The sections below describe the separate, synthetic-only offline prototypes.

**Solo SYNTHETIC.** Tutti i siti, conteggi, identità client, orari e follower sono inventati. Nessuna distribuzione deriva dai server reali. Snapshot dimostrativo 30 ottobre 2026, 18:02 Europe/Rome: non è ora corrente.

## Dashboard da shell (versione richiesta)

Prototipo GoAccess-style **nel terminale**, senza browser, dominio, rete,
servizi, dipendenze pip o database. Riusa aggregazione e fixture HTML senza
modificarle. Python 3.9+ con timezone di sistema; curses standard su Linux.

Dal checkout locale:


```sh
cd immution
python3 experimental/dashboard/terminal.py --demo

# Snapshot stampabile, anche via pipe/non-TTY:
python3 experimental/dashboard/terminal.py --demo --once
python3 experimental/dashboard/terminal.py --demo --once --site journal --width 80
python3 -m unittest discover -s experimental/dashboard -p "test_*.py" -v
```

Tasti: **Tab/n/destra** sito successivo, **p/sinistra** precedente,
**0** tutti, **j/k o giu/su** scorri, **Home** inizio, **?** aiuto,
**r** rileggi la stessa fixture, **q** esci (anche Ctrl-C).
Nessun aggiornamento live o temporizzato: refresh manuale, snapshot fisso.
Tutti i controlli sono di sola lettura; niente ban/configurazioni.

La selezione sito filtra conteggi, distinti, timeline, motivi e ultimo evento;
la tabella siti resta completa per confronto, la salute resta globale.
Il layout va a capo e scorre su terminali piccoli, riduce le barre orarie;
24x8 verificato via PTY. Consigliato almeno 80x24, 80x45 per vedere tutto.
Output ASCII (caratteri non ASCII/controllo sostituiti con ?); nessuna identita
client esportata. Senza TTY, con TERM=dumb o curses non disponibile passa
allo snapshot testuale e termina. --once non importa curses.

Verifica: 11 test Python dashboard (7 aggregazione/HTML + 4 terminale),
incluso PTY reale con avvio, cambio sito, aiuto, refresh, resize, uscita e
ripristino attributi terminale. Nessuna integrazione col daemon legacy.
Fattibilita **VALIDATED** per demo locale; dati reali/collector fuori ambito.

## Uso HTML (precedente, conservato)

Da root del repository, con Python **3.9+** e database timezone di sistema:

```sh
python3 experimental/dashboard/generate.py
python3 -m unittest discover -s experimental/dashboard -p "test_*.py" -v
node experimental/dashboard/test_ui.cjs # facoltativo, solo test; Node 18+
```

Aprire `experimental/dashboard/dashboard.html` nel browser. Funziona offline, anche via file://; abilitare JavaScript per grafici e filtri. Se serve un server locale facoltativo:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory experimental/dashboard
```

Aprire http://127.0.0.1:8765/dashboard.html. Arrestare con Ctrl-C. Nessun hosting pubblico richiesto.

## Contratto dati e sicurezza

- `fixture.json` è la fonte esplicita e deterministica. Ogni riga evento rappresenta una richiesta sintetica; non è un parser dei log Immution.
- `sites` contiene ID stabili e nomi configurati; `sources` associa ID della sorgente a ID sito. Un futuro collector deve assegnare tali ID dalla configurazione dei file/log, mai da Host o altri header. Le sorgenti sconosciute vanno nel gruppo separato “Sorgente non mappata”.
- `blocked` e `would_block` restano separati, inclusi gli IP unici (qui token sintetici). Gli IP si deduplicano globalmente: non sommare i distinti dei siti o delle modalità. Test esclusi prima dell’aggregazione.
- Finestra [start, end), massimo 48 ore. Timestamp con offset obbligatorio; bucketing in UTC e visualizzazione Europe/Rome con offset per distinguere le ore duplicate al cambio DST.
- Nessun IP, Host, URI, query o token client è esportato in HTML. Motivi normalizzati in categorie consentite; stringhe JSON HTML-escaped e DOM costruito con textContent. Solo la configurazione locale è autorizzata a definire le etichette dei siti. Non inserire segreti nelle etichette.
- Output fisso in questa directory, target symlink rifiutato; nessun percorso da dati o argomenti CLI. Eseguire in un checkout locale fidato, non in una directory condivisa ostile.
- CSP vieta rete, form e risorse esterne. Nessun CDN, framework, database, WebSocket o polling; nessun comando ban/configurazione.

## UI e limiti

Filtro sito su metriche, timeline, motivi e ultimo evento; selettore modalità solo sui motivi, per preservare il confronto fra serie. Tabella siti intenzionalmente completa e cliccabile; pulsante reset. Tabella oraria accessibile, stato vuoto, layout responsive. Salute follower globale simulata. L’età è calcolata **allo snapshot**, non al momento di apertura; assenza eventi non equivale a guasto.

Il prototipo richiede Python più recente del daemon legacy (3.6), non ne modifica i requisiti. Non installato né integrato nel servizio. Per produzione servirebbero: adapter dei log/versioni, identità sorgenti verificate, privacy/retention, ingestione e rotazione affidabili, atomicità dell’output, permessi, autenticazione e gestione degli errori. L’HTML è un artefatto dimostrativo di sola lettura.

## Verifica del prototipo

7 test Python dedicati e 14 test esistenti superati; harness DOM Node senza dipendenze verifica filtri, modalità, stato vuoto, reset e pulsanti sito. Non sostituisce un test browser. Preview tentata con lo strumento browser: file:// rifiutato come protocollo non supportato, HTTP loopback rifiutato dalla policy. Nessun aggiramento; server locale di prova arrestato. Screenshot e resa visuale desktop/mobile non verificati in questa sessione.

## File

`generate.py` aggrega e renderizza; `fixture.json` contiene dati solo sintetici; `template.html` contiene CSS/JS inline; `dashboard.html` è l’artefatto generato; `test_dashboard.py` verifica aggregazione, escaping/privacy, separazione modalità, DST/timezone, sorgenti sconosciute, invarianti e target symlink.
