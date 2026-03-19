# Stato finale della suite test

Data verifica: 2026-03-19.

## Stato della suite

- Collection completa eseguita con `pytest --collect-only -q`: **355 test raccolti**, senza errori di import o di collection.
- Esecuzione completa eseguita con `pytest -q`: **355 test passati**.
- Stato finale: **suite completamente verde** al momento di questa verifica finale.

## Cluster sistemati nella bonifica progressiva

Dalla cronologia recente del repository risultano già chiusi i seguenti cluster principali:

- Aura test cluster.
- Footer/meta/status tests.
- Resoconto/Riassunto regressions.
- QnA engine AI fallback handling.
- Voice sessions cleanup tests.
- Barcello event-driven recovery tests.
- AI web search test cluster.
- Campaign content scheduler trigger tests.
- Fragile modular command tests.
- Isolamento degli stub temporanei di modulo.

Questa PR finale non apre nuovi perimetri: verifica l'esito complessivo della bonifica e consolida la configurazione pytest.

## Cleanup prudente eseguito in questa PR

- Aggiunta la direttiva `testpaths = tests` in `pytest.ini` per rendere esplicito il perimetro di collection della suite ed evitare collection accidentali fuori dalla cartella `tests/`.
- Verificata la coerenza tra `pytest.ini` e `tests/conftest.py`:
  - `pytest.ini` gestisce solo il bootstrap minimo (`pythonpath = .`) e ora delimita anche la collection.
  - `tests/conftest.py` non applica override globali persistenti/autouse: gli stub opzionali passano tramite fixture e `monkeypatch`, quindi vengono ripristinati a fine test.
- Verificato che non restano override globali persistenti introdotti centralmente nella suite:
  - il fixture `stub_optional_dependencies` usa override reversibili di `sys.modules`;
  - il fixture `import_fresh` pulisce solo i prefissi richiesti prima dell'import mirato.

## Workaround tecnici ancora presenti

I seguenti workaround restano presenti ma non sono stati rimossi perché il beneficio immediato è basso rispetto al rischio di toccare test oggi verdi:

- `tests/_sqlite_stub.py` resta come helper condiviso per i test che simulano `aiosqlite`.
- Alcuni file mantengono caricamento manuale del modulo tramite `spec_from_file_location(...)` / `exec_module(...)`:
  - `tests/test_audio_notes_transcribe.py`
  - `tests/test_campaign_content_command_behaviors.py`
  - `tests/test_daily_activity_sorting.py`
- Diversi file usano ancora stub locali di `sys.modules` a livello file per dipendenze opzionali (`aiosqlite`, `openai`, `httpx`, `discord`). Al momento non impediscono la stabilità della suite, quindi non sono stati rifattorizzati in questa PR finale.

## Failure residui

- Nessun failure residuo rilevato nella suite completa durante questa verifica.

## Raccomandazioni per mantenere la suite affidabile

- Conservare `pytest.ini` come punto unico di bootstrap e collection della suite.
- Preferire fixture locali o condivise con `monkeypatch` rispetto a override permanenti di `sys.modules`.
- Quando si introduce un nuovo test su moduli con dipendenze opzionali, centralizzare gli stub riutilizzabili in helper/fixture invece di copiarli a livello file.
- Evitare nuovi test source-based se è disponibile un test di comportamento osservabile.
- Ridurre progressivamente i casi di import manuale (`spec_from_file_location`) solo in PR dedicate e a perimetro ristretto.
