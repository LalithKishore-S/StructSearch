# Step 4 — AST feature extraction

No Ollama or extra packages needed. Pure standard library (`ast`).

## What it does
For every function/method unit it computes a vector of **33 named structural features**
(`if_count`, `try_count`, `max_depth`, `self_call`, `guard_clause_count`, `bare_except_count`, ...)
plus a sparse histogram of AST node types (`node:If`, `node:Call`, ...).
Failed (unparseable) files get an empty record with `parse_status="failed"`, so they stay searchable by text
but never match structural queries.
Saved to `.structsearch_index/ast_features.jsonl`, refreshed automatically when units change.

Design notes: iterative traversal (no stack overflow), `elif` chains do not add depth, recursion is
detected via bare name (functions) or `self.`/`cls.`/`ClassName.` (methods), 3.9-compatible.

## Apply
Unzip `step4.zip` over your repo root (same folder as `structsearch/`), keeping paths.

New: `structsearch/parsing/{__init__,features,store}.py`, `tests/test_features.py`, `tests/test_features_store_cli.py`, `README_STEP4.md`
Changed: `structsearch/interface/cli.py` (new `features` command), `structsearch/__main__.py` (quiet on `| head`)

## Run
```bash
python -m pytest -q                                   # expect 153 passed (1 may skip on Python 3.11)
python -m structsearch features                       # table for all units in the corpus
python -m structsearch features trees.py::factorial   # all non-zero features of one unit (partial ids work)
python -m structsearch features factorial --json
```
Defaults use `corpus_path` from `configs/default.yaml`; override with `--corpus PATH`.

## Next
Step 5: structural retrieval (query -> feature constraints -> ranking). Needs Ollama
`qwen2.5-coder:7b` (optional; rule-based fallback works without it).
