# Standard centralizzato per il rendering degli embed comando

Per il vocabolario canonico delle action e la loro semantica normativa si applica anche `docs/command_standards.md`.

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
- Footer, author, colori e metadata devono passare dalla pipeline centralizzata.

## Standard ufficiale tipo embed → icona / colore

Per tutti gli embed standardizzati:

- `success` → sottotitolo `✅`, colore verde (`0x57F287`);
- `warning` → sottotitolo `⚠️`, colore giallo (`0xFEE75C`);
- `error` → sottotitolo `❌`, colore rosso (`0xED4245`);
- `info` → sottotitolo `ℹ️`, colore azzurro (`0x3498DB`).

Questo mapping è centralizzato in `app/shared/discord/command_embeds.py` e vale anche per percorsi `status/show/list/set/reset/run` e per le relative action composte di configurazione quando transitano dal builder standard.

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

## Pipeline centralizzata `/embed`: footer + author

Il namespace canonico per l'amministrazione del rendering embed è `/embed`, non `/admin`.

Regole obbligatorie:

- `/embed footer ...` è il comando standard corrente per il dominio footer;
- `/embed author ...` è il comando standard corrente per il dominio author;
- `footer` e `author` sono due domini distinti ma centralizzati e condividono la stessa pipeline finale di rendering;
- il footer controlla brand/versione/frase/contributor tecnici;
- l'author controlla l'intestazione visuale del servizio;
- le thumbnail di footer e author sono indipendenti e non devono essere derivate una dall'altra;
- i renderer standardizzati devono passare metadata sufficienti a entrambe le pipeline e lasciare la decisione finale ai servizi centrali del dominio.

## Footer centralizzato

Non esiste più un output finale `minimal`: tutti gli embed standardizzati devono passare dalla stessa pipeline footer comune e includere, quando disponibili, tutti i segmenti nell’ordine:

1. `Barcellometro <versione>`, sempre presente;
2. frase del footer service, solo quando esiste davvero una frase configurata e non vuota;
3. parte tecnica finale `Dati elaborati con ...`, solo quando esistono davvero contributor/provider/model/strumenti esterni da dichiarare.

`attach_minimal_footer(...)` sopravvive solo come shim di compatibilità interna: non decide più il testo finale del footer e non può bypassare `FooterService.apply(...)`. Se la frase non è configurata, il footer mostra soltanto la brand/versione e, se applicabile, il segmento tecnico finale.

Se `footer_service` non è disponibile (`None`), la pipeline standard non lascia mai l'embed senza footer: usa comunque il fallback base dello stesso contratto unico e rende almeno `Barcellometro <versione>`. La versione arriva dal valore centralizzato del footer quando il service esiste; se il service manca del tutto, la pipeline usa il fallback runtime condiviso (`BARCELLOMETRO_VERSION` oppure `dev`) invece di inventare una frase. In questo scenario la seconda parte non compare, mentre la terza parte `Dati elaborati con ...` continua a comparire quando i metadata hanno contributor reali.

Vale esplicitamente per **tutti** i percorsi del repo: admin legacy, action canoniche `status/show/list/set/reset/run`, relative action composte di configurazione, embed campagne, renderer aura/report, finalize helpers, delivery helpers e qualunque invio che passi da `send_legacy_standard_response(...)`, `send_standard_response(...)`, `finalize_embed(...)`, `finalize_embeds(...)` o metadata footer condivisi. Se la frase globale o di servizio esiste, non sono ammesse eccezioni silenziose che mostrano solo `Barcellometro <version>`.

Di conseguenza, i renderer locali non devono usare `embed.set_footer(...)` con stringhe custom per bypassare il contratto centrale: devono invece allegare footer metadata e lasciare che la pipeline comune renderizzi sempre `versione → frase configurata → eventuale parte tecnica`.

Per `/riassunto` questo requisito copre esplicitamente il path runtime completo di consegna: build dettagli, normalize/sanitize, `apply_standard_report_style(...)`, `finalize_embeds(...)`, `send_dm_or_followup(...)` ed eventuale fallback DM negato → followup ephemeral. Se `summary.ai_status.used_ai_output == True` e `used_display_model` è presente, tutte le pagine finali devono mantenere la terza parte `Dati elaborati con <used_display_model>` senza perderla durante split, retry o fallback.

Gli embed persistiti e poi ricostruiti con `discord.Embed.from_dict(...)` devono sempre essere reidratati nel footer contract centralizzato prima di qualsiasi `edit_message(...)`, `send_message(...)` o `followup.send(...)`: non basta conservare il footer già renderizzato, vanno riattaccati metadata/footer context e, se necessario, rifinalizzata la pipeline standard.

Semantica dei contributor/provider:

- i comandi puramente informativi o configurativi (`status`, `show`, `list`, `set`, `reset`, relative action composte di configurazione, admin locale, ecc.) **non** mostrano mai la terza parte se non usano davvero strumenti esterni per elaborare dati;
- i servizi AI o pipeline ibride **devono** dichiarare i contributor reali che hanno elaborato i dati, anche quando girano in locale;
- per esempio audio notes deve poter mostrare contributor come `faster-whisper`, `argos` e `llama3.2` nello stesso footer quando STT, traduzione e summary hanno tutti partecipato all’elaborazione;
- i contributor vengono deduplicati e mostrati con nomi display puliti, nell’ordine semantico raccolto dal servizio.

## Grammatica visuale condivisa tra `/riassunto` e `/resocontocanale`

I dettagli di `/riassunto` devono seguire la stessa grammatica visuale del renderer di `/resocontocanale` quando i dati equivalenti sono disponibili:

- `🏷️ TEMI` usa hashtag espliciti (`#settimana, #video_grafici, #progetto`);
- `📌 MOMENTI SALIENTI` mostra un prefisso speciale composto da timestamp/link in forma di bolded masked link (`**[HH:MM](jump_url)**`), eventuale pallino colore Barcello del momento e score in grassetto prima del testo;
- in tutte le sezioni a bullet con timestamp (`MOMENTI SALIENTI`, frasi iconiche, dinamiche, `CHI DEGRADA`, `CHI RINVIGORISCE`) il timestamp è trattato come masked link markdown e, quando è bolded, l'intero blocco `**[label](url)**` deve restare intatto e cliccabile quando esiste un messaggio sorgente valido, anche dopo render della linea, split, truncation, normalize e pagination degli embed;
- per i `MOMENTI SALIENTI` la pipeline link-aware deve preservare senza spezzarlo il prefisso completo `**[HH:MM](jump_url)** 🟢 **64** — ` (con emoji/score opzionali ma atomici per il layout), così il link del timestamp non perde mai il closing markdown;
- il `primary_ref` dei bullet summary serve come ancoraggio cliccabile del momento: può puntare al messaggio migliore del cluster anche quando il testo finale del bullet descrive il contesto della scena e non parafrasa letteralmente quel singolo messaggio;
- i `MOMENTI SALIENTI` devono descrivere cosa succede davvero nel bucket/segmento, con tema e taglio concreti quando esistono, e non ridursi a keyword soup o parole isolate prese dal messaggio di riferimento;
- i nomi/nickname noti vengono resi in grassetto in momenti, frasi iconiche, dinamiche e sezioni analoghe con approccio conservativo;
- nelle sezioni MOD `🔥 CHI DEGRADA` e `🌿 CHI RINVIGORISCE` i motivi devono essere chiari, leggibili e non tecnici: una frase breve che descrive il comportamento osservato e perché è utile ai MOD;
- il dettaglio MOD di `/riassunto` può integrare i punti Aura nella finestra temporale richiesta, mostrando almeno il saldo Aura nel periodo e, quando utile, il totale Aura della finestra senza appesantire il layout;
- la mappa `moment -> barcello snapshot` deve riusare la stessa logica di finestra locale ±30 minuti già usata dal canale summary, per evitare divergenze tra `/riassunto` e `/resocontocanale`.

La regressione deve essere coperta anche lato test sul percorso reale di invio, includendo DM riusciti, fallback followup/ephemeral, persistenza dei masked links dopo split/truncation/pagination e coerenza multipagina del footer AI.

Esempi:

- nessuna frase, nessun contributor: `Barcellometro dev6`
- frase presente, nessun contributor: `Barcellometro dev6 · Sempre acceso.`
- nessuna frase, contributor presente: `Barcellometro dev6 · Dati elaborati con gpt-4o`
- frase presente, contributor presente: `Barcellometro dev6 · Sempre acceso. · Dati elaborati con gpt-4o`

Se la frase del footer non esiste, la pipeline centralizzata non aggiunge placeholder, non aggiunge sezioni vuote e non produce separatori doppi. Il flag `used_local_processing` resta metadata interno per profiling/persistenza e non genera testo visibile da solo.

## Thumbnail footer e frase

La configurazione del footer separa in modo esplicito la **frase** dalla **thumbnail**:

- `footer.global_phrase` e `footer.service_phrase.<service>` controllano solo il testo;
- `footer.global_thumbnail` e `footer.service_thumbnail.<service>` controllano solo l'icona del footer;
- i comandi embed `/embed footer template_global_set` e `/embed footer template_service_set` accettano un parametro opzionale `thumbnail`.

Il parametro `thumbnail` supporta soltanto:

1. custom emoji Discord statica `<:name:id>` → normalizzata in `https://cdn.discordapp.com/emojis/<id>.png`;
2. custom emoji Discord animata `<a:name:id>` → normalizzata in `https://cdn.discordapp.com/emojis/<id>.gif`;
3. URL immagine remoto `http://` o `https://`.

La frase del footer **non** viene più usata come sorgente implicita per la thumbnail:

1. le custom emoji presenti nella frase restano testo della frase e non vengono promosse automaticamente a `icon_url`;
2. le emoji Unicode normali restano nel testo;
3. la pipeline non prova a “ripulire” la frase per ricavarne l'icona configurativa.

L'ordine di precedenza finale per l'icona del footer è:

1. `footer_icon_url` esplicito già allegato nei metadata runtime;
2. thumbnail configurata per il servizio;
3. thumbnail globale configurata;
4. nessuna icona (`None`).

La precedenza standard del dominio footer per i valori amministrabili è:

1. override di servizio;
2. template globale;
3. fallback del dominio footer.

Regole di reset footer:

- `template_service_reset` rimuove l'override di servizio e fa riespandere template globale oppure fallback footer;
- `template_global_reset` rimuove il template globale e lascia solo il fallback del dominio per i servizi senza override;
- il reset del footer non deve materializzare nel database un valore arbitrario persistito come falso default.

La frase legacy `Dati elaborati` + ` in loco` è abolita in tutto il progetto, così come la coda `e fallback` + ` locale`: non devono più comparire in codice, test, documentazione, configurazioni versionate, override locali o footer renderizzati. Questo vale anche per eventuali campi config come `footer`, `fallback_footer` o template equivalenti. Per output non-AI non si mostra alcuna frase tecnica finale; per output AI si usa solo `Dati elaborati con ...` quando esistono davvero contributor/provider/model da dichiarare. Il flag `used_local_processing` resta metadata interno e non aggiunge testo visibile al footer.

## Author centralizzato

La sezione `author` degli embed ha ora un servizio dedicato separato dal footer (`app/services/author.py`) e segue un contratto distinto:

- `author.enabled` abilita/disabilita il rendering centralizzato della sezione author;
- `author.version`, `author.global_phrase`, `author.global_thumbnail` definiscono il template globale;
- `author.service_phrase.<service>` e `author.service_thumbnail.<service>` definiscono override per singolo servizio;
- il fallback puro non usa brand/versione Barcellometro: rende sempre `emoji servizio + nome servizio` e non usa thumbnail di default;
- la `version` author ha semantica sobria: viene appesa solo quando esiste una `phrase` globale o di servizio, quindi il fallback puro resta leggibile (`🗒️ Riassunto`, non `🗒️ Riassunto · dev`).

Ordine di precedenza author:

1. override di servizio (`phrase` / `thumbnail`);
2. template globale;
3. fallback semantico `emoji + nome servizio`;
4. nessuna thumbnail se non configurata.

Questo equivale alla regola normativa generale `override servizio > globale > fallback`. Se un renderer imposta un author custom per una ragione forte di dominio, quell'override runtime deve essere esplicitamente documentato e prevale solo per quel renderer; non ridefinisce il contratto standard per gli altri servizi.

Regole di fallback e reset:

- il fallback author per servizio è sempre `emoji del servizio + nome servizio`;
- la thumbnail author del fallback è separata dal footer e resta assente se non esiste un template del dominio;
- `template_service_reset` rimuove l'override di servizio e fa riespandere template globale oppure fallback author;
- `template_global_reset` rimuove il template globale e fa riespandere il fallback author per tutti i servizi che non hanno override locale;
- il reset non deve mai riesumare un valore arbitrario persistito fuori contratto.

Il namespace `/embed author` replica il modello amministrativo del footer con i comandi:

- `/embed author on|off|status`;
- `/embed author template_global_set|show|reset`;
- `/embed author template_service_set|show|reset`.

Lo status author usa una vista multipagina navigabile parallela a quella del footer, ma mostra solo dati author: stato, template globale, regola versione, author effettivo e thumbnail effettiva per servizio.

## Status amministrativo multipagina per `/embed footer` e `/embed author`

Lo status del footer usa una vista amministrativa compatta e navigabile: la prima pagina mostra una overview sintetica, mentre le pagine successive sono raggruppate per famiglie di servizi (`Standard services`, `Editorial campaigns`, `Prompt campaigns`, `Timer campaigns`, più eventuali gruppi coerenti aggiuntivi). La navigazione avviene sempre sullo stesso messaggio tramite bottoni `INIZIO`, `INDIETRO` e `AVANTI`, senza inviare raffiche di embed scollegati.

Lo status author segue la stessa regola multipagina quando la lista dei servizi è lunga: overview nella prima pagina, pagine successive per gruppi coerenti di servizi e nessuna esplosione di una lista lunga in un unico embed.

Regole obbligatorie per gli status:

- la paginazione di status è parte del contratto amministrativo del namespace `/embed`;
- la riga pagina (`Pagina x/y`) appartiene alla description amministrativa della pagina corrente e non al footer Discord renderizzato manualmente;
- ogni pagina deve mostrare il valore effettivo del dominio e la sua sorgente di precedenza (`service`, `global`, `fallback`, più eventuali override runtime già documentati);
- i blocchi per servizio devono restare leggibili: footer o author effettivo, thumbnail effettiva, sorgente effettiva, conteggio varianti e sintesi compatta;
- i dettagli tecnici grezzi (`label`, alias duplicati, dump piatti di `key` / `origin` / `updated`) non devono dominare la UI.

Tutto il namespace `/embed` segue la stessa grammatica visuale: titolo fisso `📦 EMBED`, sottotitolo in description con il path funzionale (`FOOTER STATUS`, `AUTHOR STATUS`, `FOOTER TEMPLATE_GLOBAL_SHOW`, `AUTHOR TEMPLATE_SERVICE_SET <service>`, ecc.), sezioni compatte uppercase con emoji coerenti e nessuna paginazione nel titolo. Anche i comandi `show`, `set`, `reset`, `on` e `off` devono passare dal builder standard condiviso invece di usare renderer legacy o titoli narrativi separati.

## Quali input entrano nel sottotitolo

Entrano nel sottotitolo gli input che cambiano l'identità semantica della richiesta, per esempio:

- tier (`BASE`, `ROLE2`, ecc.);
- utenti/ruoli/canali quando il comando opera su un target preciso;
- `quantita + unita` per comandi come `ultimi`;
- `schedule_id`, `id`, `id_or_name`, `type`, `scope`, `duration` e simili quando il comando mostra/modifica una singola entità.
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

## Appendice: standard runtime per `🚪 INGRESSI & USCITE`

Il feed GREETINGS / `🚪 INGRESSI & USCITE` segue inoltre un contratto visivo fisso, distinto dagli embed comando standardizzati:

- il renderer live usa sempre author fisso `🚪 INGRESSI & USCITE`;
- il titolo dell'embed coincide con la label evento (`event_label`);
- la narrativa occupa la `description` principale dell'embed;
- non esiste più il field separato `Evento`;
- non esiste più un timestamp custom nel footer/testo tipo `Oggi alle ...`;
- la thumbnail dell'embed deve usare l'avatar dell'utente quando disponibile;
- i placeholder dinamici renderizzati nel testo finale restano evidenziati in **grassetto**;
- la palette cromatica distingue ingressi/stati non terminali vs uscite/enforcement;
- il payload visualizzato deve provenire dalla **timeline canonica** `member_flow_events`;
- il file `settings/greetings_trigger.example.json` / relativo override runtime `settings/greetings_trigger.json` è la source of truth editoriale unica per frasi, fallback e override mood/time/barcello/count;
- non esiste più un campo separato `Stato barcello "<server>"`: ogni riferimento al Barcello va integrato direttamente nella narrativa quando il template JSON lo rende naturale;
- non è ammesso un doppio embed di uscita per la stessa sequenza tecnica (per esempio `inactive_kick` assorbito da `inactive_tempban`, oppure `leave` gateway successivo a una departure esplicita già visibile);
- i label user-facing devono mostrare `ALLONTANAMENTO` / `ALLONTANAMENTO PER INATTIVITÀ` e non il termine raw `KICK`.
