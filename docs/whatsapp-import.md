# Import storico da WhatsApp

Formato e strategia di parsing per popolare i `deposits` storici. Da implementare
in Fase 2; questo documento fissa il contratto così che lo schema regga fin da subito.

## Sorgente

Export di chat WhatsApp (*Esporta chat → Includi media*):

- `_chat.txt` — un file di testo con tutti i messaggi
- allegati media (foto) nella stessa cartella, referenziati per nome nel testo

## Righe rilevanti

WhatsApp scrive una riga per messaggio, con timestamp, mittente e corpo. Il formato
esatto varia per locale/piattaforma; il parser deve essere tollerante. Esempi tipici:

```
[12/03/2024, 09:41:22] Mario Rossi: Località: https://maps.google.com/?q=45.4384,10.9916
[12/03/2024, 09:41:58] Mario Rossi: IMG-20240312-WA0007.jpg (file allegato)
```

Due tipi di messaggio ci interessano:

1. **Location** — contiene un URL `maps.google.com/?q=<lat>,<lon>` (o `maps.app.goo.gl`
   da risolvere). Da qui si estraggono `lat`, `lon`, `ts`, mittente.
2. **Media/foto** — riga con allegato immagine (`IMG-....jpg (file allegato)` /
   `<Media omessi>` a seconda dell'export). Riferimento al file selfie.

## Pairing location ↔ selfie

Un **deposito = una location**, arricchito col selfie dello **stesso mittente** più
vicino nel tempo entro una finestra (default: **±5 minuti**).

- Nessun selfie nella finestra → deposito valido con `photo_ref = NULL`
  (placeholder coniglio in UI).
- Più selfie candidati → il più vicino nel tempo.

## Mapping mittente → utente

Il nome mittente WhatsApp si mappa su `users.wa_handle`. Nomi non riconosciuti:
riportati in un report di import, da associare manualmente (o creare l'utente).

## Normalizzazione

Ogni location diventa un `Deposit`:

| Campo | Origine |
|---|---|
| `user_id` | lookup `wa_handle` |
| `ts` | timestamp del messaggio location |
| `lat`, `lon` | dall'URL maps |
| `photo_ref` | selfie appaiato (o NULL) |
| `source` | `'whatsapp_import'` |
| `raw_ref` | offset/riga nel `_chat.txt` (audit) |
| `altitude`, `territory_osm_id` | **vuoti**: li riempie il geo-enrich a valle |

## Idempotenza

L'import è ri-eseguibile senza duplicare: la dedup su `(user_id, lat, lon, minuto)`
(indice `idx_deposits_dedup`) scarta i re-import dello stesso evento. Reimportare un
export più lungo aggiunge solo i nuovi depositi.

## Note aperte

- **URL accorciati** (`maps.app.goo.gl`): richiedono una risoluzione HTTP per
  ottenere lat/lon. Da valutare se farla in import o in un passo separato.
- **Fuso orario:** i timestamp WhatsApp sono nell'ora locale del dispositivo che
  esporta. Fissare una convenzione (UTC in storage) in fase di parsing.
