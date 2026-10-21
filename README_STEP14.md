# Step 14: graph scoring

## Added
- `structsearch/graph/scoring.py`: `graph_intents(query)` (query -> relationships), `score_graph(graph, query | intents, ast_records=None)` -> `GraphResult(scores, evidence, intents)`, plus `INTENTS`, `INTENT_DOC`, `DECAY`.
- Fusion hook: `graph_signal(scores, evidence=None)` and `fused_search(..., graph_evidence=...)` in `retrieval/fusion.py` (existing callers unchanged). Graph evidence lines now appear in a result's `evidence`.
- `tests/test_graph_scoring.py` (33 tests).

## Use
    from structsearch.graph import build_graph, score_graph
    result = score_graph(graph, "validate user input before database access")
    fused_search(query, units_by_id, bm25_index, weights, k, graph_scores=result.scores, graph_evidence=result.evidence)

`score_graph` returns only positive scores; an empty result (no relationship in the query) means "no graph signal", and fusion leaves the graph out. Pass `ast_records` (from `extract_all`) to let callee functions with guard clauses that raise count as validation steps.

## Relationships
| intent | asks for | score |
|---|---|---|
| `validated_db` | validation step before database access | 1.0 validation strictly before the access; 0.4 validation present but not before; 0.25 access without validation |
| `unvalidated_db` | database access with no validation step before it | 1.0, else absent |
| `db_access` | database access | 1.0 |
| `calls_validator` | calls something named like a validation step | 1.0 |
| `file_access` | opens a file | 1.0 |
| `recursive` | calls itself or is in a call cycle | 1.0 self call; 0.8 cycle of at most 4 calls |

Database/file access found through callees is multiplied by 0.7, 0.5, 0.35 for 1, 2, 3 calls down (deeper: ignored). When a query names several relationships, their scores are averaged.

Query mapping is rule based (`graph_intents`): validation words (valid-, sanitiz-/sanitis-, verif-, check, escap-), database words (database, db, sql, query, execute, ...), file words (file, open, ...), negation words (without, missing, weak, unsafe, ...), `inject-`, `recurs-`, `itself`. Examples:

| query | intents |
|---|---|
| validate user input before database access | `validated_db` |
| database access without validation / sql injection | `unvalidated_db` |
| functions that query the database | `db_access` |
| opens a file | `file_access` |
| recursive directory walk that opens files | `file_access`, `recursive` |
| convert camel case name to snake case | none |

## Sample corpus
"validate user input before database access":

    1.00 db.py::get_user
         edge: get_user -> validate_user_input (call, line 12)
         marker: validation:validate at line 12 (validate_user_input)
         marker: db:execute at line 13 (db.execute)
         order: validation (line 12) is before database access (line 13)
    0.25 db.py::count_rows        marker: db:execute at line 24 ... order: no validation step in count_rows
    0.25 db.py::find_user_unsafe  marker: db:execute at line 19 ... order: no validation step in find_user_unsafe

`validate_user_input` itself gets no graph score: it never touches the database, which is the case text and AST evidence could not separate.

## Limits
- Database access means a `db:execute` marker; validation means a call named like validation (or, with `ast_records`, a callee with guard clauses that raise). Neither shows that data is validated, that the check is effective, or that the validated value reaches the query.
- "Before" compares line numbers inside one unit: not execution order. A validation step on the same line as the access does not count as before. For access through callees the whole call chain counts: validation in the caller before the call, or in a callee before its own access, makes the access validated (a wrapper of a validating function is not reported as unvalidated).
- Evidence is partial in the sense of the graph: calls through aliases, other objects or other packages are not seen.
- The query mapper is a word list. Paraphrases without those words get no graph signal or only the broader one ("make sure the argument is acceptable before it reaches the database layer" is read as plain database access), and bare words trigger relationships whatever they mean: on the dev set, "calls another function defined in the same file" was read as `file_access` because of the word "file"; "query" in a non-database sense triggers `db_access` the same way. The relationships it finds are always real edges of the graph, so such a mistake adds noise to the ranking rather than false evidence.

## Next
Step 15: integration: a `text_graph` search mode (and graph in `hybrid`), graph evidence in CLI/JSON output, runner variants.
