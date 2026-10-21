# Step 10: setup and decisions for the graph, evaluation and security work

No library code in this step. It fixes the corpus, the settings every variant shares, and the contracts the next steps build against.

## Setup check
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m pytest -q                      # 424 passed, 2 skipped (the skips need optional dependencies)
    python -m structsearch search "validate user input before database query" --mode text_ast --explain

## Decisions

### Corpus
`tests/fixtures/sample_corpus` stays the corpus for all experiments (`corpus_path` in `configs/default.yaml` already points to it).
- 4 parseable files give 15 function/method units; `broken_syntax.py` adds one file-level unit (`broken_syntax.py::<module>`, `parse_status=failed`). Total: 16 units.
- `tests/fixtures/expected_units.json` pins this unit list, so the fixture files are not edited. If more material is needed later it goes in a new directory, never into this one.
- Consequence for evaluation: with 16 units, Top-10 covers most of the corpus, so P@10 and R@10 say little. Report K = 1, 3, 5 (MRR is unaffected) and state the corpus size next to every table.
- Labels refer to the unit ids produced by `ingest_corpus` on this corpus, e.g. `db.py::get_user`.

### Settings shared by every variant
- `--tolerant` off: no partial units appear; the failed file is the single file-level unit.
- Same `--index-dir` per experiment run, `--embedder` fixed for all dense/hybrid variants, `--rebuild` after any corpus change.
- Weights tuned on the dev split only (`--tune`); `--final` is run once after the weights are frozen in `configs/default.yaml`.

### Variants to evaluate
`bm25`, `dense`, `text_ast`, `text_graph`, `hybrid` (plus `+llm` where a mapper comparison is needed). `text_graph` is added in Step 15.

### Graph record (built in Step 12)
Nodes: one per code unit, keyed by `unit_id`, with `name`, `file_path`, `parse_status`, and the API/DB markers found in its body (Step 13). Failed units get a node and no edges.

Edges: `source` (unit_id), `target` (unit_id or marker label), `relation`, `method`, `line`.

| relation | meaning | target |
|---|---|---|
| `calls` | the source calls another unit of the corpus | unit_id |
| `uses_api` | the source calls a listed API/DB operation (`execute`, `open`, ...) | marker label, e.g. `db:execute` |

`method` records how the edge was found (e.g. `ast_call_name`), so evidence can say what was observed.

Call resolution (explicit calls only):
- `name(...)` resolves to a unit with that name in the same file, otherwise to the only unit with that name in the corpus. Several candidates: no edge.
- `self.name(...)` resolves to a method of the same class.
- `obj.name(...)` creates an edge only when `name` is a listed marker. Aliases, dynamic dispatch, indirect calls and calls into other packages are not modelled, so graph evidence is partial.

### Graph score hook (Step 14 and 15)
The graph module returns `scores: unit_id -> non-negative float` and `evidence: unit_id -> list[str]`. `graph_signal()` in `retrieval/fusion.py` gets an optional `evidence` argument (existing callers unchanged). Evidence lines are factual, e.g. `edge: get_user -> validate_user_input (call)`. Missing or all-zero graph scores leave the graph out, as today.

### Metric function (Step 11)
`metric_fn(ranking, relevance, k) -> {"P@k", "R@k", "MRR", "nDCG@k", "hit@k"}`, the signature `run_experiment` already accepts. Queries without a relevant label are skipped and listed, as today.

## Baseline observation that motivates the graph
For "validate user input before database query" (`text_ast`), `db.py::validate_user_input` ranks first and `db.py::get_user` second. `get_user` is the function that actually validates and then queries; the validator alone has no database access. Text and AST evidence cannot express "calls a validator, then executes", while a call edge to `validate_user_input` plus a `db:execute` marker can. The graph steps are built to be checked against this case.

## Next
Step 11: metrics module in `structsearch/evaluation/`.
