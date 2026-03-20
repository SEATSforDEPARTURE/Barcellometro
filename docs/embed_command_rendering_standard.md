# Standard centralizzato per il rendering degli embed comando

## Regola obbligatoria

Tutti gli embed prodotti dai percorsi standardizzati (`send_standard_response`, `send_legacy_standard_response`, `build_command_embeds` e wrapper locali che li delegano) devono seguire questa regola:

- **Titolo** = top-level visuale reale del comando mostrato all'utente, **pari pari**.
- **Sottotitolo** = soli sotto-comandi + eventuali parametri rilevanti.
- Gli input runtime rilevanti devono comparire nel sottotitolo in forma leggibile e stabile.
- Il top-level **non va mai ripetuto** nel sottotitolo.
- Wrapper tecnici o namespace interni (per esempio `admin`) **non devono comparire nel titolo** se il comando visuale appartiene a un altro namespace.
- Il body deve evitare duplicazioni inutili dei parametri già presenti nel sottotitolo.
- Le prime righe del body non devono introdurre prefissi narrativi come `Dettaglio:`, `Warning:`, `Result:`, `Results:`, `Error:`.
- Il builder standard deve mantenere sempre una separazione visiva stabile tra sottotitolo e body: `sottotitolo`, riga vuota, body.
- Il sottotitolo usa sempre l’icona semantica ufficiale del tipo embed, non icone locali di sezione.
- Il body non deve ripetere come primo marker la stessa icona già usata nel sottotitolo.
- Il body non deve mai riusare la stessa icona del sottotitolo nelle sezioni: se una sezione la erediterebbe o la riceve esplicitamente, il builder centralizzato la sostituisce con un fallback semantico o neutro non ridondante.
- Footer, colori e metadata devono passare dalla pipeline centralizzata.

## Standard ufficiale tipo embed → icona / colore

Per tutti gli embed standardizzati:

- `success` → sottotitolo `✅`, colore verde (`0x57F287`);
- `warning` → sottotitolo `⚠️`, colore giallo (`0xFEE75C`);
- `error` → sottotitolo `❌`, colore rosso (`0xED4245`);
- `info` → sottotitolo `ℹ️`, colore azzurro (`0x3498DB`).

Questo mapping è centralizzato in `app/shared/discord/command_embeds.py` e vale anche per percorsi `status/show/list/set/reset/test/config` quando transitano dal builder standard.

## Esempi

### Prima

- `/frasi template_global_show` renderizzato come titolo `ADMIN` e sottotitolo `FRASI TEMPLATE_GLOBAL_SHOW`.
- `/campagne prompt status` renderizzato come titolo `ADMIN` e sottotitolo `CAMPAGNE PROMPT STATUS`.
- `/qna limits_show parameter:base` renderizzato con duplicazione del top-level nel sottotitolo.

### Dopo

- `/frasi template_global_show`
  - titolo: `💬 FRASI`
  - sottotitolo: `ℹ️ TEMPLATE_GLOBAL_SHOW`
- `/qna limits_show parameter:base`
  - titolo: `❓ QNA`
  - sottotitolo: `ℹ️ LIMITS_SHOW BASE`
- `/qna bonus_show user:@Mario`
  - titolo: `❓ QNA`
  - sottotitolo: `ℹ️ BONUS_SHOW MARIO`
- `/resocontocanale status`
  - titolo: `📓 RESOCONTOCANALE`
  - sottotitolo: `ℹ️ STATUS`
- `/resocontoserver status`
  - titolo: `📓 RESOCONTOSERVER`
  - sottotitolo: `ℹ️ STATUS`
- `/riassunto ultimi quantita:30 unita:minuti`
  - titolo: `🗒️ RIASSUNTO`
  - sottotitolo: `✅ ULTIMI 30 MINUTI`
- `/riassunto ultimi quantita:1 unita:ore`
  - titolo: `🗒️ RIASSUNTO`
  - sottotitolo: `ℹ️ ULTIMA ORA`
- `/attivita ultimi quantita:7 unita:giorni`
  - titolo: `📈 ATTIVITA`
  - sottotitolo: `✅ ULTIMI 7 GIORNI`
- `/attivita ultimi quantita:1 unita:minuti`
  - titolo: `📈 ATTIVITA`
  - sottotitolo: `ℹ️ ULTIMO MINUTO`
- `/resocontocanale ultimi quantita:1 unita:giorni`
  - titolo: `📓 RESOCONTOCANALE`
  - sottotitolo: `ℹ️ ULTIMO GIORNO`
- `/riassunto range da:20/03/2026 10:15 a:21/03/2026 11:45`
  - titolo: `🗒️ RIASSUNTO`
  - sottotitolo: `ℹ️ DAL 20/03 10:15 AL 21/03 11:45`
- `/campagne prompt status`
  - titolo: `📣 CAMPAGNE`
  - sottotitolo: `ℹ️ PROMPT STATUS`
- `/moderazione users tempban_list`
  - titolo: `🛠️ MODERAZIONE`
  - sottotitolo: `ℹ️ USERS TEMPBAN_LIST`
- `/admin retention on`
  - titolo: `🫛 ADMIN`
  - sottotitolo: `ℹ️ RETENTION ON`

## Implementazione

Il comportamento è centralizzato in `app/shared/discord/command_embeds.py` tramite la normalizzazione del contesto visuale del comando.

In pratica:

- `top_level` può restare il namespace tecnico interno quando serve.
- `visual_top_level` definisce il top-level visuale reale da mostrare nel titolo.
- `subtitle_args` è l'API esplicita e centralizzata per aggiungere parametri runtime significativi al sottotitolo.
- `relevant_parameters` resta supportato per retrocompatibilità, ma i nuovi call site devono preferire `subtitle_args`.
- `build_command_embeds(...)` e `send_standard_response(...)` condividono la stessa logica finale di rendering.
- La grammatica italiana delle finestre temporali usa la logica comune di `time_windows` per produrre forme corrette come `ULTIMO MINUTO`, `ULTIMA ORA`, `ULTIMO GIORNO`, `ULTIMA SETTIMANA`, oltre ai plurali corretti per quantità > 1.
- I renderer standardizzati deduplicano nel body i campi identitari già promossi nel sottotitolo (`user`, `tier`, `quantity`, `unit`, `scope`, `schedule_id`, ecc.) quando non aggiungono nuovo contesto.
- I bullet narrativi di primo livello usano frasi pulite: il tono arriva da colore/icona/tipo embed, non da etichette testuali.
- Se una riga body arriva con la stessa emoji del sottotitolo (per esempio `✅` in un embed `success`), il builder la ripulisce centralmente per evitare duplicazioni visive.
- Le intestazioni di sezione passano tutte dalla stessa deduplica centrale: le emoji specializzate già sensate restano intatte se diverse dal sottotitolo, ma non è mai consentito un header sezione con la stessa faccina del sottotitolo.

## Footer centralizzato

Quando è disponibile `FooterService`, gli embed standardizzati non devono fermarsi a versione/minimal footer: devono usare la pipeline footer comune e quindi includere, quando disponibili, tutti i segmenti nell’ordine:

1. versione bot;
2. frase del footer service;
3. parte tecnica finale `Dati elaborati con ...` solo quando esistono davvero contributor/provider/model da dichiarare; se non ci sono contributor, il segmento tecnico non compare.

Esempi:

- prima: `Barcellometro dev6 · Dati elaborati con gpt-4o · In via di sviluppo.`
- dopo: `Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o`

Se la frase del footer non esiste, il footer resta ben formato e concatena solo gli elementi disponibili, senza separatori doppi.

La frase legacy `Dati elaborati` + ` in loco` è abolita in tutto il progetto, così come la coda `e fallback` + ` locale`: non devono più comparire in codice, test, documentazione, configurazioni versionate, override locali o footer renderizzati. Questo vale anche per eventuali campi config come `footer`, `fallback_footer` o template equivalenti. Per output non-AI non si mostra alcuna frase tecnica finale; per output AI si usa solo `Dati elaborati con ...` quando esistono davvero contributor/provider/model da dichiarare. Il flag `used_local_processing` resta metadata interno e non aggiunge testo visibile al footer.

## Quali input entrano nel sottotitolo

Entrano nel sottotitolo gli input che cambiano l'identità semantica della richiesta, per esempio:

- tier (`BASE`, `ROLE2`, ecc.);
- utenti/ruoli/canali quando il comando opera su un target preciso;
- `quantita + unita` per comandi come `ultimi`;
- `schedule_id`, `id`, `id_or_name`, `template_name`, `scope`, `duration` e simili quando il comando mostra/modifica una singola entità.
- finestre temporali normalizzate (`ULTIMA ORA`, `ULTIMI 30 MINUTI`, `DAL 20/03 10:15 AL 21/03 11:45`) per i comandi `oggi`, `ieri`, `ultimi`, `range`.

Non devono invece sporcare il sottotitolo:

- template/testi lunghi;
- JSON, blob, prompt estesi;
- payload tecnici o oggetti Python raw.

Non devono neppure essere ristampati senza valore aggiunto nel body subito dopo il sottotitolo.

## Normalizzazione degli input

La normalizzazione del sottotitolo è centralizzata in `app/shared/discord/command_embeds.py`:

- stringhe: trim + uppercase finale;
- choice/enum: usa il valore leggibile (`base`, `role2`, `minuti`, `giorni`) e lo rende stabile;
- utenti Discord: preferisce `display_name`, `global_name` o `name` invece delle mention grezze quando l'oggetto è disponibile;
- canali/ruoli: usa il nome leggibile quando possibile;
- finestre temporali: se il comando termina con `ultimi` o `range`, il sottotitolo viene ricomposto centralmente con grammatica italiana corretta invece di concatenare banalmente `quantita + unita`;
- valori troppo lunghi o chiaramente tecnici vengono scartati dal sottotitolo e restano in bullet/sections.

## Bullet iniziali: regole di pulizia

Per le righe primarie del body:

- `("dettaglio", "Ti ho inviato il riassunto in DM.")` → `• Ti ho inviato il riassunto in DM.`
- `("warning", "Phrase entry #1 not found.")` → `• Phrase entry #1 not found.`
- `("result", "updated")` → `• Updated.`
- `("error", "Qualcosa è andato storto.")` → `• Qualcosa è andato storto.`

Il builder standardizzato non deve più produrre le etichette grezze `Dettaglio:`, `Warning:`, `Result:`, `Results:`, `Error:` nelle prime righe.

## Indicazioni per i wrapper locali

Quando un wrapper inoltra un comando non-admin verso il renderer standardizzato:

- deve passare il `subcommand_path` con il namespace visuale corretto;
- deve valorizzare `visual_top_level` se il `top_level` tecnico non coincide con quello visuale;
- deve usare `subtitle_args` per parametri che devono comparire nel sottotitolo;
- non deve concatenare manualmente gli argomenti runtime dentro `subcommand_path`.
- non deve usare top-level semantici troppo generici (`resoconto`) quando il comando reale esposto è più specifico (`resocontocanale`, `resocontoserver`).

Non introdurre renderer paralleli o embed manuali per aggirare questo standard.
