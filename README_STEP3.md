# Step 3: baseline search CLI (BM25)

Unzip into the repo root (same-name files are replaced: `ingestion/__init__.py`, `ingestion/corpus.py`,
`indexing/__init__.py`, `indexing/builder.py`, `retrieval/__init__.py`, `interface/__init__.py`).

## Run (from the repo root)
```bash
source .venv/bin/activate
pytest -q                                                   # expect: 93 passed
python -m structsearch search "read file" -k 3              # builds the index on first use
python -m structsearch search "recursive tree traversal" --lines 4
python -m structsearch search "validate user input" -k 2 --json
python -m structsearch index path/to/your/repo              # build/refresh an index explicitly
python -m structsearch search "send email" --corpus path/to/your/repo -k 5
```
Options for `search`: `-k N`, `--lines N` (excerpt length), `--json`, `--corpus PATH`, `--index-dir DIR`,
`--rebuild`, `--skip-failed`, `--query-id ID`, `--mode bm25` (more modes arrive in later steps).
Defaults come from `configs/default.yaml` (`corpus_path`, `index_dir`, `top_k`).

## What a result shows
Rank, `unit_id`, score, file path and line range, why it matched (query terms found in the name,
identifiers, docstring/comments and code), and an excerpt with real file line numbers. Files that did
not parse are flagged `[parse failed]`. Results are `RankedResult` records (`text_score`,
`structural_score=0`, `graph_score=None`, `final_score=text_score`, `evidence`), the same format the
later Text+AST and hybrid variants will fill in.

## Index freshness
`search` rebuilds the index automatically when it is missing, when the corpus path or `--skip-failed`
setting changed, or when the Python files changed on disk (checked by path, size and modification
time). The reason is printed on stderr. `--json` output on stdout is always clean JSON.

## Notes
- Messages and errors go to stderr; exit code 2 means a bad argument or missing corpus path.
- Run from the repo root, since `.structsearch_index/` and the default corpus path are relative.
- A query made only of stopwords ("find all the functions") returns no results and prints a note.
