# Standard centralizzato per il rendering degli embed comando

## Regola obbligatoria

Tutti gli embed prodotti dai percorsi standardizzati (`send_standard_response`, `send_legacy_standard_response`, `build_command_embeds` e wrapper locali che li delegano) devono seguire questa regola:

- **Titolo** = top-level visuale reale del comando mostrato all'utente.
- **Sottotitolo** = soli sotto-comandi + eventuali parametri rilevanti.
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
- `relevant_parameters` permette di aggiungere parametri significativi al sottotitolo senza sporcare il titolo.
- `build_command_embeds(...)` e `send_standard_response(...)` condividono la stessa logica finale di rendering.

## Indicazioni per i wrapper locali

Quando un wrapper inoltra un comando non-admin verso il renderer standardizzato:

- deve passare il `subcommand_path` con il namespace visuale corretto;
- deve valorizzare `visual_top_level` se il `top_level` tecnico non coincide con quello visuale;
- deve usare `relevant_parameters` per parametri che devono comparire nel sottotitolo.

Non introdurre renderer paralleli o embed manuali per aggirare questo standard.
