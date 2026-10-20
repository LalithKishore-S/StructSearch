# Step 2: Text IR (BM25) + Step 1 change (failed files stay searchable)

Unzip into the repo root. Files with the same name are replaced (ingestion, config, default.yaml,
expected_units.json, test_ingestion.py, test_config.py, `indexing/__init__.py`).

## Run
```bash
source .venv/bin/activate
pip install -r requirements.txt            # no new dependencies
pytest -q                                  # expect: 76 passed
python -m structsearch.indexing --query "read file" -k 3        # ingest + build + search the fixture corpus
python -m structsearch.indexing --load --query "recursive tree traversal"   # reuse the saved index
python -m structsearch.indexing path/to/your/repo --index-dir .structsearch_index --query "validate input"
```
`--skip-failed` leaves unparseable files out. The index folder (git-ignored) holds `units.jsonl`,
`failed_files.json` and `bm25_index.json`.

## Step 1 change
Files that do not parse are no longer dropped. Each becomes one file-level unit
(`path.py::<module>`, `parse_status="failed"`) so it can be found by text search. The error message and
line are saved in `failed_files.json` and shown in the ingestion summary. Fixture corpus: 15 function
units + 1 failed-file unit = 16. Python's own compiler (`python -m py_compile file.py`) remains the
authority on the exact syntax error; per-function splitting of broken files is planned as Step 9
(tree-sitter).

## How the text index works
- **Tokenizer:** snake_case, camelCase, PascalCase and acronyms split into lowercase subwords;
  stopwords, single characters and numbers dropped; query-only words (find, functions, ...) dropped
  from queries. No stemming ("validate" does not match "validation").
- **Fields:** `name` (Class.method), `identifiers` (names used in the code, from the AST),
  `doc` (docstring + comments), `code` (every word in the source, including words in strings).
- **Scoring:** BM25 per field (Lucene-style idf so tiny corpora still score), weighted sum with
  `bm25.field_weights` in `configs/default.yaml` (name 3, identifiers 2, doc 1.5, code 1).
  Ties are broken by `unit_id`.
- **Persistence:** tokenized fields are stored as JSON and BM25 statistics are rebuilt on load, so a
  reloaded index gives identical scores. A fingerprint of `units.jsonl` triggers an automatic rebuild
  if the units changed.

## Python API
```python
from structsearch.indexing import build_all, load_all
result, index = build_all("path/to/repo", ".structsearch_index")
hits = index.search("read file", k=5)            # Hit(unit_id, score, field_scores)
index.explain("read file", hits[0].unit_id)      # matched query terms per field
scores = index.score_all("read file")            # aligned with index.unit_ids (used by fusion later)
```

## Known limits
- `rank-bm25` loops over documents in Python, so a query takes a fraction of a second on ~100k
  functions; fine for this project, and a faster BM25 library can be swapped in behind `BM25Index`.
- "recursive tree traversal" also ranks `count_nodes` second because its docstring says "not
  recursive". That is exactly the keyword weakness the AST step is meant to fix.
