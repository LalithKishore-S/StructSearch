# Step 8: experiment harness

## Added
- `structsearch/experiments/metrics.py`: stub evaluator (P@k, R@k, MRR, nDCG@k, hit@k). Pass Member 2's function as `metric_fn` (signature `(ranking, relevance, k) -> {metric: value}`) to replace it.
- `structsearch/experiments/runner.py`: loads queries + labels, runs variants, writes `summary.csv`, `per_query.csv`, `failures.json`, `results.md`.
- CLI `experiment`. Sample data in `experiments/sample/` (6 queries on the fixture corpus: smoke test only, not evidence).

## File formats
Queries (json/jsonl/csv): `query_id, query, category (lexical|relationship), split (dev|test)`, optional `patterns` list.
Labels (json/jsonl/csv): `query_id, unit_id, relevance, query_category, split` (Member 2's EvaluationLabel).
Queries with no relevant label are skipped and listed.

## Run
    python -m pytest -q
    python -m structsearch experiment --queries Q --labels L --corpus <corpus> --variants bm25,dense,text_ast,hybrid --out results
    python -m structsearch experiment ... --variants text_ast,text_ast+llm      # rules vs Ollama mapper (needs ollama)
    python -m structsearch experiment ... --tune text_ast                        # weight grid, dev only
    python -m structsearch experiment ... --final                                # adds the test split: run once, last
Try it offline: add `--embedder hashing` and the sample files in `experiments/sample/`.
Ollama (real runs): `ollama pull nomic-embed-text`, `ollama pull qwen2.5-coder:7b`, `ollama serve`.

## Rules baked in
- Only dev queries run unless `--final`. `--tune` never touches test. Tune first, then run `--final` once with the chosen weights in `configs/default.yaml`.
- Variants: bm25, dense, structural, like, text_ast, hybrid; suffix `+llm` maps the query with Ollama (falls back to rules).
- Failures: "no relevant result in top-k" and "top-1 not relevant", with the missing relevant units.

## Observed on the sample (smoke only)
The rules mapper finds no structure in "function that opens a file without closing it", so text_ast equals BM25 there. That is the paraphrase brittleness the `+llm` variant is meant to be compared against.
