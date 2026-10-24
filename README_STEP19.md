# Step 19: Streamlit app

A browser front end that shows not only the ranking but how it was produced: how the query was read, what each signal contributed, and the call-graph edges that served as evidence.

## Run
    pip install -r requirements-ui.txt           # Streamlit (Altair is included)
    streamlit run structsearch/interface/streamlit_app.py

Open the address Streamlit prints (usually http://localhost:8501). It runs from the repository root and uses the corpus and index folder in `configs/default.yaml` (editable in the sidebar). Everything except the dense/hybrid modes and `llm` explanations works offline.

## The page
Sidebar: **Example queries** (fills the query and shows the answer expected from the code), result count, corpus and index folder. The app always ranks with the full model (`text_ast_graph`: BM25 text + AST structure + call graph, the best variant on the benchmark) and shows the template "why" summary per result. The other modes (`bm25`, `text_ast`, `text_graph`, `dense`, `hybrid`), the relationship override, custom weights, Ollama mapping and `llm` explanations stay available in the CLI.

**Search tab**, for one query:
1. *How the query was understood*: the relationship(s) found with the words that triggered them, the structure asked for (AST), the signals in the ranking and their weights, and a note when the graph is left out because the query names no relationship.
2. *Ranking and score breakdown*: a stacked bar per result (weight x signal score for text, structure, graph) that adds up to the final score, with the arithmetic of the top result.
3. *Evidence graph*: the returned functions and the graph edges the ranking used (red), with line numbers; diamonds are API/validation markers; optional grey context edges; a selector highlights one result's evidence.
4. *Results*: code, evidence lines and the explanation for each result.

**Security candidates tab**: the SQL-construction scan with level, source and sink, code and evidence, the "candidate for human review, not confirmed" notice, and what is not modelled.

**Call graph tab**: the whole graph grouped by file, with a per-function card (calls, callers, markers).

## What changed in the code
- `graph/scoring.py`: `GraphResult.edges` (the graph edges behind each unit's evidence, recorded where the evidence lines are produced, so the picture and the text cannot differ) and `graph_intent_trace(query)` (which words triggered which part of the reading; `graph_intents` now uses it).
- `interface/service.py`: `SearchResponse.graph_result` (kept out of `extra`, so the CLI JSON is unchanged).
- `interface/ui_data.py` (new): the data behind each panel as plain functions: `understand_query`, `score_breakdown`, `evidence_graph_dot`, `full_graph_dot`, `unit_card`, `candidate_rows`, and `DEMO_QUERIES`.
- `interface/streamlit_app.py`: the page; `search_rows` is kept for compatibility.
- Tests: `tests/test_ui_data.py` (32), `tests/test_streamlit_app.py` (15, drives the page without a browser through Streamlit's `AppTest`), and 16 new tests for the scorer and service. Suite: 713 passed, 1 skipped.

## Queries to try and what to expect
Pick them from the *Example queries* menu; the app shows the expectation and checks the top result against it. `tests/test_ui_data.py` runs every one of them against the real ranking, so these answers cannot drift.

| query | correct answer (from the code) | what to see |
|---|---|---|
| queries that run without checking their input | `find_user_unsafe`, `count_rows` | BM25 alone would put `validate_user_input` first (it never queries); the full model does not |
| function that calls itself | `factorial`, `inorder_traverse` | BM25 alone returns nothing; the graph shows the self-call edges |
| validate user input before database access | `get_user` | red edges: call to the validator (line 12), `db:execute` (line 13) |
| database access without validation | `find_user_unsafe`, `count_rows` | `get_user` is not an answer: it validates first |
| which functions touch the database | `get_user`, `find_user_unsafe`, `count_rows` | BM25 alone finds only `get_user` |
| sanitize the input and then run a sql query | `get_user` | paraphrase, same relationship |
| opens a file without error handling | `read_lines`, `write_log` | `read_config_safe` has a try/except, so it is not an answer |
| exception handling around file access | `read_config_safe` | structure and text agree |
| function with a while loop | `count_nodes` | no relationship: the graph stays out |
| convert camel case name to snake case | `camel_to_snake` | ranked exactly like BM25 |
| append a message to a log file / read a json file and handle bad json | `write_log` / `read_config_safe` | plain functionality |
| make sure the argument is acceptable before it reaches the database layer | `get_user` | right top result, but read only as plain database access, so all three database functions are listed |
| function that calls another function defined in the same file | `get_user` | **known limitation**: every mode misses it (the word "file" is read as file access) |
| payment gateway timeout retry | nothing | the system returns nothing |

Things to check by hand: select different results in *Highlight the evidence of*; tick *Show the other calls and markers*; open the Security tab (two candidates, both `high`) and the Call graph tab (inspect `db.py::get_user`). To see the BM25 comparison, run the same query from the command line with `--mode bm25`.

## Limits
- The evidence graph shows only the returned functions and the edges the graph signal used (plus, if asked, their other edges as grey context).
- The graph signal depends on the word-list query reading, which the first panel makes visible; wrong readings (for example "same file" read as file access) are shown, not hidden.
- The app does not use dense embeddings or LLM explanations (they need Ollama and were not run).

## Next
Step 20: the Results tab (see README_STEP20.md).
