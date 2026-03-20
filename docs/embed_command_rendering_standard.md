# Standard centralizzato per il rendering degli embed comando

## Regola obbligatoria

Tutti gli embed prodotti dai percorsi standardizzati (`send_standard_response`, `send_legacy_standard_response`, `build_command_embeds` e wrapper locali che li delegano) devono seguire questa regola:

- **Titolo** = top-level visuale reale del comando mostrato all'utente.
- **Sottotitolo** = soli sotto-comandi + eventuali parametri rilevanti.
- Gli input runtime rilevanti devono comparire nel sottotitolo in forma leggibile e stabile.
- Il top-level **non va mai ripetuto** nel sottotitolo.
- Wrapper tecnici o namespace interni (per esempio `admin`) **non devono comparire nel titolo** se il comando visuale appartiene a un altro namespace.
- Footer, colori e metadata restano quelli centralizzati esistenti.

## Esempi

### Prima

- `/frasi template_global_show` renderizzato come titolo `ADMIN` e sottotitolo `FRASI TEMPLATE_GLOBAL_SHOW`.
- `/campagne prompt status` renderizzato come titolo `ADMIN` e sottotitolo `CAMPAGNE PROMPT STATUS`.
- `/qna limits_show parameter:base` renderizzato con duplicazione del top-level nel sottotitolo.

### Dopo

- `/frasi template_global_show`
  - titolo: `💬 FRASI`
  - sottotitolo: `🛠️ TEMPLATE_GLOBAL_SHOW`
- `/qna limits_show parameter:base`
  - titolo: `❓ QNA`
  - sottotitolo: `🛠️ LIMITS_SHOW BASE`
- `/qna bonus_show user:@Mario`
  - titolo: `❓ QNA`
  - sottotitolo: `🛠️ BONUS_SHOW MARIO`
- `/riassunto ultimi quantita:30 unita:minuti`
  - titolo: `🗒️ RIASSUNTO`
  - sottotitolo: `✅ ULTIMI 30 MINUTI`
- `/attivita ultimi quantita:7 unita:giorni`
  - titolo: `📈 ATTIVITA`
  - sottotitolo: `✅ ULTIMI 7 GIORNI`
- `/campagne prompt status`
  - titolo: `📣 CAMPAGNE`
  - sottotitolo: `🛠️ PROMPT STATUS`
- `/moderazione users tempban_list`
  - titolo: `🛠️ MODERAZIONE`
  - sottotitolo: `🛠️ USERS TEMPBAN_LIST`
- `/admin retention on`
  - titolo: `🫛 ADMIN`
  - sottotitolo: `🛠️ RETENTION ON`

## Implementazione

Il comportamento è centralizzato in `app/shared/discord/command_embeds.py` tramite la normalizzazione del contesto visuale del comando.

In pratica:

- `top_level` può restare il namespace tecnico interno quando serve.
- `visual_top_level` definisce il top-level visuale reale da mostrare nel titolo.
- `subtitle_args` è l'API esplicita e centralizzata per aggiungere parametri runtime significativi al sottotitolo.
- `relevant_parameters` resta supportato per retrocompatibilità, ma i nuovi call site devono preferire `subtitle_args`.
- `build_command_embeds(...)` e `send_standard_response(...)` condividono la stessa logica finale di rendering.

## Quali input entrano nel sottotitolo

Entrano nel sottotitolo gli input che cambiano l'identità semantica della richiesta, per esempio:

- tier (`BASE`, `ROLE2`, ecc.);
- utenti/ruoli/canali quando il comando opera su un target preciso;
- `quantita + unita` per comandi come `ultimi`;
- `schedule_id`, `id`, `id_or_name`, `template_name`, `scope`, `duration` e simili quando il comando mostra/modifica una singola entità.

Non devono invece sporcare il sottotitolo:

- template/testi lunghi;
- JSON, blob, prompt estesi;
- payload tecnici o oggetti Python raw.

## Normalizzazione degli input

La normalizzazione del sottotitolo è centralizzata in `app/shared/discord/command_embeds.py`:

- stringhe: trim + uppercase finale;
- choice/enum: usa il valore leggibile (`base`, `role2`, `minuti`, `giorni`) e lo rende stabile;
- utenti Discord: preferisce `display_name`, `global_name` o `name` invece delle mention grezze quando l'oggetto è disponibile;
- canali/ruoli: usa il nome leggibile quando possibile;
- valori troppo lunghi o chiaramente tecnici vengono scartati dal sottotitolo e restano in bullet/sections.

## Indicazioni per i wrapper locali

Quando un wrapper inoltra un comando non-admin verso il renderer standardizzato:

- deve passare il `subcommand_path` con il namespace visuale corretto;
- deve valorizzare `visual_top_level` se il `top_level` tecnico non coincide con quello visuale;
- deve usare `subtitle_args` per parametri che devono comparire nel sottotitolo;
- non deve concatenare manualmente gli argomenti runtime dentro `subcommand_path`.

Non introdurre renderer paralleli o embed manuali per aggirare questo standard.
