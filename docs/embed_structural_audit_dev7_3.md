# Audit strutturale embed — Barcellometro-dev7.3

Data audit: 2026-03-26.
Scope: renderer, command modules, services e shared helpers che costruiscono o impattano embed runtime.

## Metodo usato
- Scansione statica dei moduli target con ricerca di `discord.Embed`, `embed.description`, `add_field`, `set_author`, `set_footer`.
- Ispezione manuale dei blocchi di rendering embed per distinguere:
  - intro narrativa in description (ammessa)
  - sezioni strutturali in description (non ammessa)
  - field names/title centralizzati vs hardcoded.
- Esecuzione del validatore statico esistente per cross-check di pattern legacy/non enforcing.

---

## A) Servizi pienamente conformi (struttura standard rispettata)

### Famiglia Attività
1. `app/renderers/activity_report_renderer.py` — **conforme**
   - Usa `format_standard_title`, `format_standard_description`, `format_standard_field_name`.
   - Le sezioni principali sono tutte in field (`Periodo`, `Stato attività`, `Punti`, `Trend`, `Statistiche`, `Consigli`).
   - Footer/author/images metadata applicati in modo centralizzato.
   - Esempio: `overview.add_field(name=format_standard_field_name("Trend", emoji="📈"), ...)`.

2. `app/renderers/user_activity_report_renderer.py` — **conforme**
   - Description breve introduttiva; sezioni importanti rese via field.
   - Titoli/field names standardizzati con helper canonicali.

3. `app/renderers/activity_dm_report_renderer.py` — **conforme** (con minima nota di rigidità)
   - Status embed: description breve, sezioni in field.
   - Dettagli paginati in field chunked, con metadata centrali.

### Famiglia Resoconto canale/server
4. `app/renderers/channel_summary.py` — **conforme**
   - Cover con intro breve in description.
   - Tutte le sezioni sostanziali (momenti, quote, dinamiche, interazioni, consigli, proverbio) in field.

5. `app/renderers/server_activity_report_renderer.py` — **conforme**
   - Stessa architettura del channel summary: intro corta + fields strutturali + metadata.

### Famiglia Comandi
6. `app/plugins/commands_modular/resoconto.py` — **conforme**
   - Costruzione embed con titolo/description standard e sezioni in field.
   - Nessun heading strutturale hardcoded in description nei blocchi analizzati.

7. `app/plugins/commands_modular/barcello.py` — **conforme** (quasi pieno)
   - Embed principali (`stato`, `no data`, `dettagli`) rispettano pattern intro + field.
   - Uso consistente di `format_standard_title` e field chunking.

---

## B) Servizi parzialmente conformi (ibridi)

1. `app/renderers/aura_renderer.py` — **parzialmente conforme**
   - Architettura a field presente e solida.
   - Ma alcune sezioni/label sono gestite con helper locale `_standard_field(...)` + stringhe hardcoded (es. `"🏆 Classifica"`, `"📜 Missioni"`) invece di naming completamente centralizzato.
   - Problema: centralizzazione incompleta dei nomi sezione.

2. `app/plugins/commands_modular/attivita.py` — **parzialmente conforme**
   - Flow principale conforme.
   - Fallback di errore DM (HTTP 400/50035) costruisce un embed con **description usata come corpo dati** multi-sezione (`Periodo`, `ATTIVITÀ`, `PUNTI`, `Trend`) invece di field.
   - Pattern ibrido runtime/fallback.

3. `app/services/campaign_content_formatter.py` — **parzialmente conforme**
   - News/Weather/Horoscope: molte sezioni sono in field.
   - Tuttavia overview e alcune pagine usano description molto ricca (anche con blocchi informativi estesi), con duplicazione parziale di contenuto già nei field.
   - È più vicino a standard editoriale ibrido che a schema rigidamente strutturale.

4. `app/plugins/audio_notes_transcribe.py` — **parzialmente conforme**
   - Builder corrente con sections in field è allineato.
   - Ma permane helper legacy `_build_audio_note_output(...)` che costruisce corpo testuale con heading hardcoded (`**✍️ Trascrizione:**`, `**🇮🇹 Traduzione:**`, `⏲️ **Riassunto:**`) da usare in description/plain text.
   - Infrastruttura mista (nuovo + vecchio pattern).

5. `app/shared/discord/footer_status_renderer.py` — **parzialmente conforme (infrastruttura status)**
   - Usa title/field standardizzati.
   - Description pagina include heading formattato (`**ℹ️ ...**`) e blocchi descrittivi semi-strutturati; non è grave ma non è enforcement forte del modello “description solo intro minimale”.

---

## C) Servizi non conformi (fuori standard strutturale)

1. `app/plugins/commands_modular/riassunto.py` — **non conforme**
   - Status embed legacy costruito con description contenente blocchi strutturali (`🕒 ...` + `ALLERTA ...`) al posto di field dedicati per quelle sezioni.
   - Title hardcoded non centralizzato nel punto legacy (`title = "🫛 RESOCONTO BARCELLO ..."`).
   - Pattern ibrido presente in un punto molto centrale del servizio.

2. `app/renderers/detail_embeds.py` — **non conforme**
   - Titolo embed dettagli hardcoded (`"🗒️ DETTAGLI RIASSUNTO — ..."`) senza helper canonicale.
   - Field names sezionali hardcoded (`"🏷️ TEMI"`, `"💬 FRASI ICONICHE"`, etc.) non passano da formatter standard.
   - In coda, modalità DM forza titolo in bold manuale (`embed.title = f"**{base_title}**"`).

3. `app/services/triggers_service.py` (path frasi iconiche) — **non conforme**
   - Embed “FRASI ICONICHE” usa `description=rendered_text` come corpo principale del contenuto, senza trasformare la sezione principale in field strutturato.
   - È un caso chiaro di description come contenitore dati.

4. `app/services/inactive_members_moderation.py` — **non conforme**
   - In `build_serverwide_inactive_embeds`, il blocco utenti inattivi è riversato in `embed.description = chunk` (contenuto operativo principale), con field usati solo per contatori/metadata.
   - Anche `build_action_embed` costruisce riepilogo operativo via description multiline.

5. `app/services/member_flow_notifications.py` — **non conforme (layout legacy esplicito)**
   - Embed evento costruito con `title=copy.event_label` e `description=copy.narrative` come corpo principale (senza fields strutturali per sezioni semantiche).
   - Il validatore stesso impone questo layout come eccezione legacy, quindi architetturalmente fuori standard generale ma “voluto” per quel canale.

6. `app/services/message_scheduler.py` — **non conforme**
   - `send_campaign_embed` pagina testo campagne direttamente in `description=page`, senza sezione a field per blocchi principali.
   - Titolo anche non sempre passato da formattazione standard del body contract.

7. `app/shared/discord/author_status_renderer.py` — **non conforme (status embed builder)**
   - Titolo pagina hardcoded (`"📦 EMBED"`) non in formato `__**UPPERCASE**__`.
   - Description usata per molte informazioni strutturali (`overview_lines`, `Author status · ...`, paginazione), non come semplice intro.

---

## D) Helper / infrastruttura non enforcing

1. `app/shared/discord/command_embeds.py` — **infrastruttura non enforcing**
   - Builder standard command usa description come contenitore primario di blocchi (`description_blocks` + section headers renderizzati in testo), invece che field Discord per sezioni.
   - Le sezioni passate in input vengono convertite in heading testuali in description (`section_header + section_value`).
   - È il collo di bottiglia più grande per gli embed comando/admin.

2. `app/shared/discord/report_embeds.py` — **infrastruttura non enforcing**
   - `build_report_cover_embed` accetta description libera senza imporre intro-only.
   - Non applica body helpers enforcing (`apply_standard_body_helpers`).

3. `app/shared/discord/embed_rendering.py` — **infrastruttura non enforcing**
   - Il body enforcing è opzionale (`body_format_options`): se non passato, title/description/field names non vengono normalizzati.

4. `app/services/discord_embed_utils.py` — **infrastruttura non enforcing**
   - Helper generici (`safe_set_description`, `safe_add_field`) fanno solo truncate; non impongono standard strutturale.

5. `validate_embed_standards.py` — **infrastruttura di audit parzialmente enforcing**
   - Controlla bene pattern letterali hardcoded.
   - Ma contiene eccezioni esplicite legacy (es. greetings live layout) e non può garantire enforcement semantico completo sui path dinamici.

6. `tests/test_embed_body_global_standard.py` — **audit test utile ma non completo**
   - Individua heading sospetti in description e uso intensivo di Embed senza helper.
   - È comunque statico/euristico: non copre tutti i flussi runtime complessi.

---

## Elenco file-per-file (giudizio + motivo sintetico)

### Renderer
- `app/renderers/channel_summary.py` → **conforme** (intro breve + sezioni in fields + metadata).
- `app/renderers/server_activity_report_renderer.py` → **conforme** (schema coerente standard).
- `app/renderers/activity_report_renderer.py` → **conforme**.
- `app/renderers/activity_dm_report_renderer.py` → **conforme**.
- `app/renderers/user_activity_report_renderer.py` → **conforme**.
- `app/renderers/aura_renderer.py` → **parzialmente conforme** (naming sezioni non totalmente centralizzato globalmente).
- `app/renderers/detail_embeds.py` → **non conforme** (title/field names hardcoded non canonical helper).

### Command modules
- `app/plugins/commands_modular/attivita.py` → **parzialmente conforme** (fallback embed a description-corpo dati).
- `app/plugins/commands_modular/barcello.py` → **conforme**.
- `app/plugins/commands_modular/resoconto.py` → **conforme**.
- `app/plugins/commands_modular/riassunto.py` → **non conforme** (status legacy con blocchi strutturali in description).
- `app/plugins/commands_modular/embed.py` → **parzialmente conforme** per dipendenza da `command_embeds` non enforcing.

### Services
- `app/services/triggers_service.py` → **non conforme** (path frasi iconiche: description come corpo).
- `app/services/campaign_content_formatter.py` → **parzialmente conforme** (editoriale ibrido, description ricca).
- `app/services/inactive_members_moderation.py` → **non conforme** (description come corpo operativo in più punti).
- `app/services/member_flow_notifications.py` → **non conforme** (layout legacy esplicitamente fuori standard strutturale).
- `app/plugins/audio_notes_transcribe.py` → **parzialmente conforme** (builder nuovo ok + helper legacy testuale).
- `app/services/message_scheduler.py` → **non conforme** (paginazione campagne in sola description).

### Shared / Helpers / Audit
- `app/shared/discord/embed_body.py` → **conforme** (helper canonici corretti).
- `app/shared/discord/embed_rendering.py` → **infrastruttura non enforcing** (normalizzazione body opzionale).
- `app/shared/discord/report_embeds.py` → **infrastruttura non enforcing**.
- `app/shared/discord/command_embeds.py` → **infrastruttura non enforcing critica**.
- `app/shared/discord/footer_status_renderer.py` → **parzialmente conforme** (status pages con description semi-strutturata).
- `app/shared/discord/author_status_renderer.py` → **non conforme** (status embeds fuori formato titolo/body).
- `validate_embed_standards.py` → **infrastruttura non enforcing (parziale, con eccezioni)**.
- `tests/test_embed_body_global_standard.py` → **audit utile, non bloccante completo**.

---

## Esempi concreti (snippet/pattern rappresentativi)

- `app/plugins/commands_modular/riassunto.py`
  - `title = "🫛 RESOCONTO BARCELLO ..."`
  - `description = "\n".join([window_label, "", alert_line])`

- `app/renderers/detail_embeds.py`
  - `discord.Embed(title=f"🗒️ DETTAGLI RIASSUNTO — {tier_label}", ...)`
  - `sections_map["quotes"] = [("💬 FRASI ICONICHE", ...)]`

- `app/services/triggers_service.py`
  - `discord.Embed(title=..., description=rendered_text, ...)` (frasi iconiche)

- `app/services/inactive_members_moderation.py`
  - `embed.description = chunk` (lista inattivi chunkata)

- `app/services/member_flow_notifications.py`
  - `discord.Embed(title=copy.event_label, description=copy.narrative[:4096], ...)`

- `app/services/message_scheduler.py`
  - `discord.Embed(title=title, description=page, ...)`

- `app/shared/discord/command_embeds.py`
  - `description = subtitle_line ... + "\n".join(description_blocks)`
  - `description_blocks.append(f"{section_header}\n{section_value}")`

- `app/plugins/commands_modular/attivita.py`
  - fallback: `fallback.description = "🕒 ... ATTIVITÀ ... PUNTI ... TREND ..."`

- `app/plugins/audio_notes_transcribe.py`
  - helper legacy: `"**✍️ Trascrizione:**"`, `"**🇮🇹 Traduzione:**"`, `"⏲️ **Riassunto:**"`

---

## Classifica priorità fix futuri

### PRIORITÀ ALTA (bloccano uniformità globale)
1. `app/shared/discord/command_embeds.py`
2. `app/plugins/commands_modular/riassunto.py`
3. `app/renderers/detail_embeds.py`
4. `app/services/triggers_service.py` (path frasi iconiche)
5. `app/services/inactive_members_moderation.py`
6. `app/services/message_scheduler.py`

### PRIORITÀ MEDIA (quasi a posto ma ibridi)
1. `app/renderers/aura_renderer.py`
2. `app/plugins/commands_modular/attivita.py` (fallback)
3. `app/services/campaign_content_formatter.py`
4. `app/plugins/audio_notes_transcribe.py` (residuo legacy helper testuale)
5. `app/shared/discord/embed_rendering.py`
6. `app/shared/discord/report_embeds.py`

### PRIORITÀ BASSA (marginali / status admin / eccezioni)
1. `app/shared/discord/footer_status_renderer.py`
2. `app/shared/discord/author_status_renderer.py` (admin/status)
3. `app/services/member_flow_notifications.py` (legacy voluto: da migrare solo se si ridefinisce il contratto greetings)
4. `app/services/discord_embed_utils.py`

---

## Mappa per famiglia di servizio

- **Attività**: buono stato generale; criticità solo fallback in `attivita.py`.
- **Aura**: renderer quasi standard, con residue scelte locali sui nomi sezione.
- **Channel Summary / Resoconto**: sostanzialmente standard.
- **Trigger / Frasi / QnA**: QnA quasi standard; frasi iconiche ancora description-centric.
- **Audio Notes**: pipeline nuova standardizzata, ma resta helper legacy testuale.
- **Campaign / Editorial**: formato ibrido (editoriale + struttura), più grave lato scheduler.
- **Moderazione/Inattivi**: fuori standard per uso description come corpo operativo.
- **Embed admin/status**: renderer status non pienamente allineati al formato title/description canonico.
- **Helper/shared infrastructure**: vero collo di bottiglia in `command_embeds.py`, poi `report_embeds.py` / `embed_rendering.py` opzionale.

---

## Conclusioni architetturali

1. **Collo di bottiglia principale**: infrastruttura shared non enforcing, soprattutto `app/shared/discord/command_embeds.py`.
2. **Servizi davvero già standard**: activity renderers principali, channel/server summary renderer, barcello/resoconto runtime principali.
3. **Servizi ancora ibridi**: aura renderer, campaign formatter, attivita fallback, audio notes legacy helper.
4. **Servizi fuori standard**: riassunto (path legacy), detail_embeds, triggers frasi iconiche, inattivi moderation, message scheduler, member_flow_notifications (eccezione legacy).
5. **Dove intervenire prima (in futuro refactor)**: prima shared helper enforcing, poi renderer/servizi che oggi serializzano sezioni dentro description.
