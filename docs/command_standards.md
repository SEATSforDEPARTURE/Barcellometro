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

### 4.1 Namespace amministrativi canonici

I namespace amministrativi fanno parte del contratto utente e vanno documentati come tali.

Regole obbligatorie:

- `/embed footer ...` è il namespace canonico per amministrare il dominio footer centralizzato;
- `/embed author ...` è il namespace canonico per amministrare il dominio author centralizzato;
- `/admin footer ...` **non** deve essere presentato come standard corrente, comando canonico o namespace raccomandato;
- eventuali riferimenti a percorsi legacy o wrapper interni devono essere descritti solo come compatibilità tecnica e mai come superficie utente preferita.

Questa regola non contraddice i command standards esistenti: `footer` e `author` restano domini amministrativi che usano le stesse action canoniche `on/off/status`, `template_*_set/show/reset` e la stessa semantica generale di override.

Per i toggle globali vale una semantica forte: `author off` deve sopprimere qualsiasi author visibile negli embed standard del progetto e `footer off` deve sopprimere qualsiasi footer visibile negli embed standard del progetto, non solo evitare nuove aggiunte.

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

### 5.4 Domini centralizzati `footer` e `author`

Per il namespace `/embed` valgono anche queste regole specifiche:

- `footer` e `author` sono domini distinti ma centralizzati;
- `footer` controlla brand/versione/frase/contributor tecnici del footer renderizzato;
- `author` controlla intestazione visuale del servizio nell'embed;
- `thumbnail` author e `thumbnail` footer sono configurazioni separate e non devono essere dedotte una dall'altra;
- i comandi `template_global_set` e `template_service_set` possono aggiornare in modo parziale i campi del proprio dominio (`phrase`, `thumbnail`, altri metadata previsti) senza resettare implicitamente quelli non passati;
- `reset` deve sempre riportare al fallback del dominio, non a un valore arbitrario persistito o a un ultimo valore memoizzato fuori contratto.

## 6. Output standard

Tutti i comandi devono usare il rendering standard centralizzato del progetto.

Regole obbligatorie:

- usare il rendering standard centralizzato per response, embed, footer e author quando previsti dal dominio;
- usare gli embed standard dove previsti dalle linee guida del progetto;
- applicare sempre la pipeline centrale obbligatoria del dominio coinvolto;
- evitare output raw non standard salvo eccezioni esplicitamente documentate.

Per i dettagli operativi del rendering si applica `docs/embed_command_rendering_standard.md`.

## 7. Default e storage

I default devono vivere nei servizi e nelle source of truth del dominio.

Regole obbligatorie:

- il default appartiene al dominio applicativo, non al layer di persistenza come duplicazione preventiva;
- il database deve rappresentare override, record persistenti o relazioni esplicite;
- il database non deve duplicare inutilmente i default già determinabili dal dominio;
- `reset` deve normalmente tradursi nella rimozione dell'override persistito, non nella scrittura ridondante del valore di default.

### 7.1 Override e fallback per domini centralizzati

Per `footer` e `author` la cascata standard di risoluzione è:

1. override di servizio;
2. configurazione globale del dominio;
3. fallback del dominio.

Regole obbligatorie:

- la precedenza `servizio > globale > fallback` deve valere per il testo e per la thumbnail del dominio, salvo override runtime espliciti del renderer già documentati nel contratto del dominio;
- il fallback del footer appartiene al dominio footer centralizzato;
- il fallback author appartiene al dominio author centralizzato e deve restare `emoji servizio + nome servizio` quando non esistono override o template globali;
- un `reset` di servizio rimuove l'override di servizio e lascia riespandere il globale o il fallback;
- un `reset` globale rimuove il template globale e lascia riespandere il fallback del dominio.

Se un renderer imposta un author custom per ragioni forti di dominio, questa scelta deve essere documentata come eccezione esplicita al flusso standard e non può ridefinire silenziosamente la gerarchia generale di precedenza.

## 7.2 Canonical timeline per GREETINGS / INGRESSI & USCITE

Per il dominio GREETINGS la persistenza segue una separazione normativa esplicita:

- `moderation_actions` è il ledger **raw di audit** delle azioni osservate o prodotte dal runtime;
- `member_flow_events` è la **timeline canonica** consumata dal runtime GREETINGS per rendering live, conteggi per occorrenza, deduplica delle uscite e backfill storico.

Regole obbligatorie:

- il runtime live di GREETINGS deve leggere la timeline canonica e non reinterpretare direttamente il ledger raw;
- la moderazione nativa Discord (`kick` / `ban` / `unban` UI, audit log) deve confluire nello stesso contratto canonico della moderazione del bot, senza drift semantico tra record backend e feed live;
- il layout visuale live deve esporre author `🚪 INGRESSI & USCITE`, titolo = label evento, narrativa in description, thumbnail avatar quando disponibile e nessun field separato `Evento`;
- i conteggi di ricorrenza devono essere per `user + event_type_key`;
- il backfill storico deve essere idempotente sulla coppia `source + source_ref`;
- gli eventi di inattività (`inactive_*`) restano semanticamente distinti dagli eventi manuali omologhi;
- `grace` e `inactive_grace` condividono l'emoji `🛟`, ma devono mantenere label e copy distinti;
- il wording user-facing deve mostrare `allontanamento` dove l'action tecnica interna resta `kick`.
- se un evento moderativo porta una motivazione user-facing, il feed GREETINGS la espone solo nel blocco finale `👇 La moderazione aggiunge`, non come duplicazione inline nel corpo principale.
- `unban` deve essere persistito nel ledger raw e nel mirror canonico per coerenza audit/backfill, ma resta nascosto nel feed GREETINGS salvo override espliciti di visibilità.

## 8. Eccezioni consentite

Sono consentite eccezioni mirate quando la semantica resta chiara e coerente, in particolare:

- reset di stato runtime;
- reset di record target-specifici;
- renderer con author custom imposto per forte ragione di dominio già documentata.

Anche in questi casi:

- `reset` deve continuare a significare ripristino del comportamento standard per quel target;
- `remove` deve continuare a significare eliminazione di un'entità distinta;
- le eccezioni di rendering non devono far decadere la regola generale di precedenza né trasformare `/admin footer` in namespace canonico.

## 9. Criteri editoriali per la documentazione

Chi aggiorna la documentazione dei comandi deve rispettare queste regole:

- usare soltanto il vocabolario canonico definito qui;
- non introdurre action speculative o sinonimi non adottati dal repository;
- descrivere le action composte come estensioni di quelle canoniche, non come verbi nuovi;
- allineare eventuali esempi, tabelle e classificazioni al comportamento reale del progetto;
- per i domini `footer` e `author`, usare `/embed ...` come riferimento canonico e trattare eventuali residui admin solo come dettaglio storico o tecnico quando indispensabile.
