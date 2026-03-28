# Embed rendering standard (single source of truth)

Il contratto ufficiale unico di rendering embed è definito in:

- `docs/embed_command_rendering_standard.md`

## Struttura standard definitiva (riepilogo normativo)

Tutti gli embed standard del progetto devono convergere su questa struttura:

1. **AUTHOR**: `servizio NOME CANONICO INGLESE TOP-LEVEL` (oppure `· Pag. X/Y` per multipagina).
2. **TITLE EMBED**: emoji iniziale + `__**TITOLO**__` sempre MAIUSCOLO.
3. **DESCRIPTION EMBED**: introduzione breve, in corsivo, senza emoji iniziale.
4. **FIELDS**: sezioni importanti sempre come veri field (`emoji + __**TITOLO FIELD**__`, MAIUSCOLO).
5. **FOOTER**: applicato dalla pipeline centralizzata.

Nota GREETINGS (`🚪 INGRESSI & USCITE`):
- description narrativa breve senza emoji iniziale, con testo in corsivo e placeholder chiave in grassetto;
- struttura description guidata da `settings/greetings_trigger*.json` (`narrative_contract` a slot fissi);
- unico field strutturale opzionale: `👇 __**LA MODERAZIONE AGGIUNGE**__`.

Regole tassative:

- i titoli sezione non devono stare nella `description` come testo libero;
- le sezioni importanti devono essere field reali;
- non sono ammessi doppi standard visivi;
- tutti i servizi devono usare lo stesso contratto.

Esempi NON corretti da evitare:

- `📈 **PANORAMICA**` dentro `description`;
- `👇 **Risposta:**` dentro `description` quando è una sezione strutturale.
