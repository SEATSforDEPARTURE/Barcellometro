# Standard ufficiale dei comandi

Questo documento definisce il vocabolario canonico e le regole normative per i comandi di Barcellometro.

Fa fede per:

- naming delle action esposte all'utente;
- semantica delle famiglie di comandi;
- aspettative su parametri, output, default e storage;
- interpretazione dei report inventariali e del rendering standard.

Il report inventariale in `docs/command_tree_report.md` descrive l'albero reale dei comandi; questo documento ne definisce il significato normativo. Per i vincoli di rendering si applica anche `docs/embed_command_rendering_standard.md`.

## 1. Vocabolario ufficiale delle action

Le sole action standard supportate e documentate sono:

- `on`
- `off`
- `status`
- `set`
- `show`
- `reset`
- `add`
- `edit`
- `remove`
- `list`
- `run`

`test` **non** è una action standard del progetto e non deve comparire come verbo canonico nella documentazione degli standard.

### 1.1 Action composte

Nel repository esistono anche action composte costruite sullo stesso vocabolario canonico, per esempio `config_set`, `config_show`, `config_reset`, `schedule_add`, `schedule_edit`, `schedule_remove`, `schedule_list`, `template_global_set`.

Regola normativa:

- il suffisso operativo deve restare uno dei verbi canonici elencati sopra;
- il prefisso (`config`, `schedule`, `template_global`, `entry`, ecc.) identifica il dominio o lo scope della risorsa;
- la semantica del suffisso non cambia quando l'action è composta.

## 2. Semantica ufficiale

### 2.1 Stato di feature

- `on` abilita una feature o un comportamento.
- `off` disabilita una feature o un comportamento.
- `status` mostra lo stato corrente della feature.

### 2.2 Configurazione singola o override

- `set` imposta o aggiorna una configurazione singola oppure un override.
- `show` mostra la configurazione attiva o l'override effettivo.
- `reset` rimuove l'override e riporta il comportamento al default o allo standard del dominio.

### 2.3 Collezioni o record multipli

- `add` crea un elemento in una collezione.
- `edit` modifica un elemento esistente.
- `remove` elimina un elemento, un record o un'associazione.
- `list` elenca gli elementi disponibili o persistiti.

### 2.4 Esecuzione manuale

- `run` avvia manualmente un'azione, un processo o un'operazione.

`run` descrive un'esecuzione esplicita; non introduce una nuova configurazione persistente per il solo fatto di essere invocato.

## 3. Differenza normativa tra `reset` e `remove`

`reset` e `remove` **non sono sinonimi**.

- `reset` rimuove un override, un valore derivato o uno stato reimpostabile e ripristina il default o il comportamento standard.
- `remove` elimina un'entità distinta, un record persistente o una relazione esplicita.

Uso corretto:

- se il sistema continua ad avere un valore implicito di riferimento dopo l'operazione, usare `reset`;
- se l'operazione cancella un elemento autonomo che prima esisteva come record o associazione, usare `remove`.

## 4. Regola concettuale principale

La scelta tra famiglie di action segue questa regola:

- se esiste un solo valore o una sola configurazione attiva per quello scope, usare `set` / `show` / `reset`;
- se esistono più elementi indipendenti, usare `add` / `edit` / `remove` / `list`.

Questa distinzione vale anche per action composte come `config_*`, `template_*`, `entry_*`, `schedule_*` e simili.

## 5. Regole sui parametri

### 5.1 Regola generale

Tutti i parametri devono essere opzionali salvo quando strettamente necessari per identificare una risorsa o per rendere possibile l'operazione richiesta.

### 5.2 Regole per famiglia

- `reset` può accettare solo parametri identificativi o di scope.
- `reset` non deve accettare parametri di valore.
- `set` accetta scope e valori.
- `show`, `list` e `status` devono esporre parametri coerenti con il tipo di risorsa mostrata.

Per i comandi di configurazione template/override, `set` deve inoltre supportare **update parziali**: se più campi sono modificabili nello stesso scope, il comando deve poter aggiornare solo i campi passati senza sovrascrivere implicitamente gli altri. Un rifiuto esplicito tipo `No changes provided` è corretto solo quando non viene passato alcun valore utile.

### 5.3 Coerenza semantica

- un parametro di targeting (`user`, `role`, `channel`, `schedule_id`, `scope`, ecc.) serve a selezionare la risorsa o il contesto;
- un parametro di valore serve a impostare il contenuto di `set`;
- `list` e `status` non devono richiedere valori di configurazione quando stanno solo osservando lo stato;
- `reset` non deve diventare un alias implicito di `set default`.

## 6. Output standard

Tutti i comandi devono usare il rendering standard centralizzato del progetto.

Regole obbligatorie:

- usare il rendering standard centralizzato per response, embed e footer;
- usare gli embed standard dove previsti dalle linee guida del progetto;
- applicare sempre il footer centrale obbligatorio;
- evitare output raw non standard salvo eccezioni esplicitamente documentate.

Per i dettagli operativi del rendering si applica `docs/embed_command_rendering_standard.md`.

## 7. Default e storage

I default devono vivere nei servizi e nelle source of truth del dominio.

Regole obbligatorie:

- il default appartiene al dominio applicativo, non al layer di persistenza come duplicazione preventiva;
- il database deve rappresentare override, record persistenti o relazioni esplicite;
- il database non deve duplicare inutilmente i default già determinabili dal dominio;
- `reset` deve normalmente tradursi nella rimozione dell'override persistito, non nella scrittura ridondante del valore di default.

## 7.1 Canonical timeline per GREETINGS / INGRESSI & USCITE

Per il dominio GREETINGS la persistenza segue una separazione normativa esplicita:

- `moderation_actions` è il ledger **raw di audit** delle azioni osservate o prodotte dal runtime;
- `member_flow_events` è la **timeline canonica** consumata dal runtime GREETINGS per rendering live, conteggi per occorrenza, deduplica delle uscite e backfill storico.

Regole obbligatorie:

- il runtime live di GREETINGS deve leggere la timeline canonica e non reinterpretare direttamente il ledger raw;
- la moderazione nativa Discord (`kick` / `ban` UI, audit log) deve confluire nello stesso contratto canonico della moderazione del bot, senza drift semantico tra record backend e feed live;
- il layout visuale live deve esporre author `🚪 INGRESSI & USCITE`, titolo = label evento, narrativa in description, thumbnail avatar quando disponibile e nessun field separato `Evento`;
- i conteggi di ricorrenza devono essere per `user + event_type_key`;
- il backfill storico deve essere idempotente sulla coppia `source + source_ref`;
- gli eventi di inattività (`inactive_*`) restano semanticamente distinti dagli eventi manuali omologhi;
- `grace` e `inactive_grace` condividono l'emoji `🛟`, ma devono mantenere label e copy distinti;
- il wording user-facing deve mostrare `allontanamento` dove l'action tecnica interna resta `kick`.
- se un evento moderativo porta una motivazione user-facing, il feed GREETINGS la espone solo nel blocco finale `👇 La moderazione aggiunge`, non come duplicazione inline nel corpo principale.

## 8. Eccezioni consentite

Sono consentite eccezioni mirate quando la semantica resta chiara e coerente, in particolare:

- reset di stato runtime;
- reset di record target-specifici.

Anche in questi casi:

- `reset` deve continuare a significare ripristino del comportamento standard per quel target;
- `remove` deve continuare a significare eliminazione di un'entità distinta.

## 9. Criteri editoriali per la documentazione

Chi aggiorna la documentazione dei comandi deve rispettare queste regole:

- usare soltanto il vocabolario canonico definito qui;
- non introdurre action speculative o sinonimi non adottati dal repository;
- descrivere le action composte come estensioni di quelle canoniche, non come verbi nuovi;
- allineare eventuali esempi, tabelle e classificazioni al comportamento reale del progetto.
