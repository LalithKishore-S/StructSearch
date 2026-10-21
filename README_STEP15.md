# Step 15: graph integration (search modes, CLI, runner)

One command now runs query -> fused Top-K with call-graph evidence.

## Added / changed
- `interface/service.py`: new mode `text_graph` (BM25 + graph); `hybrid` now also uses the graph (BM25 + dense + structure + graph); `SearchRequest.intents`; `graph_inputs()` builds/loads the graph, scores the query and reports the relationships found. `text_ast` is unchanged (no graph), so the required comparisons stay separate.
- `configs/default.yaml` + `config.py`: `text_graph_weights` (text 0.7, graph 0.3), validated on load; falls back to those values if absent.
- CLI: `--mode text_graph`, `--intent NAME` (repeatable) to fix the relationships instead of reading them from the query, `--weight` works for the new mode, graph notes on stderr, graph evidence in text and JSON output (`graph_score`, `graph.intents`).
- `interface/explain.py`: the template explanation quotes the graph evidence lines (`edge:`, `marker:`, `order:`, `structure:`).
- `experiments/runner.py`: variant `text_graph`; queries may carry `"intents": [...]`; `tune_weights` supports `text_ast`, `text_graph` and `hybrid` (hybrid now tunes graph too; the hard-coded `graph=0` is gone).
- `tests/test_graph_integration.py` (23 tests); one expectation in `tests/test_fusion.py` updated (the hybrid query "validate user input" now has a graph signal).

## Run
    python -m structsearch search "validate user input before database access" --mode text_graph
    python -m structsearch search "validate user input before database access" --mode hybrid --explain
    python -m structsearch search "tree" --mode text_graph --intent recursive --json
    python -m structsearch search "..." --mode text_graph --weight graph=0.5      # or graph=0 to switch the graph off
    python -m structsearch experiment --queries Q --labels L --variants bm25,text_ast,text_graph,hybrid --out results
    python -m structsearch experiment --queries Q --labels L --tune text_graph                        # dev only
    python -m pytest -q                                                                               # 569 passed, 1 skipped

Example (`--mode text_graph`, "database access without validation"):

    1. db.py::find_user_unsafe   score 1.000
       - fusion: text 1.00x0.70 + graph 1.00x0.30 = 1.000
       - marker: db:execute at line 19 (db.execute)
       - order: no validation step before database access (line 19)

## Rules
- A query with no relationship the graph can express has no graph signal: the graph is left out and `text_graph` ranks exactly like BM25 (stderr note, `graph.intents` empty). `hybrid` then equals BM25 + dense + structure.
- `--intent` and `"intents"` in a queries file replace the reading of the query text; several intents are averaged. Unknown names are rejected (exit code 2).
- `--weight graph=0` removes the graph signal (ablation; fusion drops any signal whose weight is 0, unless every weight is 0); `--weight text=0 --weight graph=1` ranks by the graph alone.
- Structural validators (callees with guard clauses that raise) count as validation steps in graph modes, using the cached AST features.
- Exit criterion of the plan: `search ... --mode hybrid` runs query -> BM25 + dense + structure + graph -> Top-K with evidence.

## Observation for the experiments
With the starting weights (text 0.7, graph 0.3), "database access without validation" ranks `find_user_unsafe` first, then `get_user` (a text match on "database" that does validate) above `count_rows` (an unvalidated access with no text match). The graph evidence is right; the weights decide how far it can reorder text matches. This is what weight tuning on the dev split (Step 18) is for, so the starting values are not final.

## Next
Step 16: the benchmark: labelling protocol, 20-40 queries with paraphrases, relevance labels, fixed dev/test split.
