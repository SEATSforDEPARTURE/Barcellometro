# Campaigns News: pipeline riassunti AI e normalizzazione extra

## Riassunto news

Per ogni notizia selezionata dal servizio `campaigns news`:

1. **Input pulito**: il titolo e lo snippet vengono sanitizzati prima dell'AI (rimozione boilerplate/meta/feed junk, HTML/entities, prefissi sporchi, duplicazioni titolo/summary).
2. **Prompt stretto**: il task editoriale richiede massimo 2 frasi, solo fatti presenti nell'input, nessuna introduzione meta e nessuna quasi-copia del feed.
3. **Validazione output**: l'output AI viene rifiutato se è meta, troppo corto/lungo, troppo simile alla sorgente, non conforme al limite frasi o con markup sporco.
4. **Fallback locale pulito**: se l'AI fallisce, viene usato un fallback breve e sanitizzato, basato solo su titolo/contenuto disponibile.

## Extra giornalieri

Gli extra (`aforisma`, `barzelletta`, `canzone`, `meme`) vengono normalizzati per avere output finale in italiano:

- se il testo è già italiano, viene mantenuto;
- se il testo è in inglese, si tenta adattamento AI in italiano;
- se l'adattamento non è affidabile, viene applicato fallback locale italiano.

Per la canzone viene preservata la riga `titolo — artista` quando disponibile.
