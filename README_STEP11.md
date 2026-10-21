# Step 11: evaluation metrics

## Added
- `structsearch/evaluation/metrics.py`: `precision_at_k`, `recall_at_k`, `reciprocal_rank`, `ndcg_at_k`, `evaluate_ranking` (all metrics for one query), `mean_metrics` (average over queries; MRR becomes the mean reciprocal rank).
- `structsearch/evaluation/__init__.py`: exports the above and `METRICS`.
- `tests/test_evaluation_metrics.py`: 16 tests with hand-computed values, graded relevance, duplicates, bounds on random rankings, and the `metric_fn` contract.

## Changed
- `structsearch/experiments/metrics.py` now re-exports the evaluation module (one implementation, no copy). `experiments/runner.py` imports from `structsearch.evaluation.metrics`. Existing imports keep working.

## Conventions
A ranking is a list of unit_ids (best first); `relevance` maps unit_id -> grade (0 = not relevant, unlabelled = not relevant).
- Only the first K entries count; a unit listed twice counts once, at its first position.
- P@K divides by K, also when fewer than K results are returned.
- R@K divides by the number of relevant units labelled for the query (0 when there are none).
- MRR: reciprocal rank of the first relevant unit inside the top K, 0 if none.
- NDCG@K: gain 2^grade - 1, discount log2(rank + 1), normalized by the ideal ordering of the labelled relevant units (binary NDCG for 0/1 labels).
- hit@K: 1 if any relevant unit is in the top K.
- `k` must be a positive integer (`ValueError` otherwise).

## Run
    python -m pytest tests/test_evaluation_metrics.py -q
    python -m pytest -q                       # 440 passed, 2 skipped

Plug in (the default already is this function): `run_experiment(..., metric_fn=evaluate_ranking)`; signature `(ranking, relevance, k) -> {"P@k", "R@k", "MRR", "nDCG@k", "hit@k"}`.

## Notes for later steps
- With a 16-unit corpus, report K = 1, 3, 5 (see Step 10).
- `tune_weights` in `experiments/runner.py` varies only `text`, `dense` and `structural` and fixes `graph=0`; it is extended with the graph signal in Steps 15 and 18.

## Next
Step 12: graph construction in `structsearch/graph/`.
