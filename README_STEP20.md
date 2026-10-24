# Step 20: Results tab (experiments inside the app)

The app's fourth tab, **Results**, shows the experiment of Step 18 interactively: the variants compared, what each signal contributes, how the full model differs from BM25 query by query, and a per-query inspector. It reads the files the experiment runner wrote (`experiments/runs/final/`) and the frozen benchmark; nothing is recomputed from scratch except the metrics of a single query at another K, which are derived from its stored ranking.

## Run
    python -m streamlit run structsearch/interface/streamlit_app.py      # then open the "Results" tab

## The tab
Controls: **Queries** (test split, or the development split whose weights were tuned, so its numbers are optimistic), **K** (1, 3, 5), **Query type** (all, lexical, relationship), **Metric** (nDCG@K, MRR, Precision@K, Recall@K, Hit@K). A line states whether the split was used for tuning, and whether the benchmark still matches the one the run was made on (a mismatch is shown as an error).

1. **Variants compared**: a bar per variant (BM25, Text + AST, Text + Graph, Full, and the three ablations) with a table of all metrics.
2. **What each signal contributes (ablation)**: the full model against the full model with the text, the AST structure or the graph removed, with the change for each.
3. **Query by query against BM25**: per variant, how many queries ranked better, the same or worse, the mean nDCG change and the exact sign-test p-value (with a note that few queries give little power).
4. **Where the full model improves or fails**: queries grouped into improved over BM25, worse than BM25, already right with BM25, and not fully solved, each with the rank of its first correct answer under BM25 and under the full model.
5. **Inspect one query**: the query, its group and the correct answers, and for every variant its top-K results marked `[correct]` or `[wrong]` with the rank of the first correct one.

## What to look at (test split, K = 3)
- Variants: full 0.952 nDCG, BM25 0.787; on relationship queries 0.962 against 0.673.
- Ablation (relationship): without the graph 0.750, without the AST structure 0.913, without the text 0.869.
- Query by query (relationship, 8 queries): the full model is better on 4, the same on 4, worse on none.
- Improved: R13 and R14 (SQL built by concatenation, and its paraphrase), R16 and R17 (opening files without error handling, and its paraphrase). In R17, BM25 returns no correct answer in its top 5; the full model puts the first at rank 2.
- Not fully solved: L12 ("create a tree node with left and right children"): the correct function is at rank 2 for every variant.
- Switch to the development split to see R12 ("calls another function defined in the same file"), which no variant solves.

## Code and tests
- `structsearch/interface/results_data.py` (new): `load_results`, `metric_rows`, `ablation_rows`, `paired_rows`, `query_outcomes`, `error_analysis`, `query_detail`, `split_note`; plain functions with no Streamlit dependency.
- `structsearch/interface/streamlit_app.py`: the Results tab.
- `tests/test_results_data.py` (14) checks the tables against the documented numbers, the win/tie/loss counts, the inspector and the missing-run and changed-benchmark cases. `tests/test_streamlit_app.py` gains 6 tests for the tab. Suite: 733 passed, 1 skipped.

## Limits
- The tab shows a completed run; it does not run experiments. To refresh it, rerun `experiments/run_experiments.sh` (the test split run is allowed once) and reload.
- Only the sample-corpus benchmark (34 queries) is available, so the figures are as small-scale as the evaluation itself; the dense and LLM variants are not shown because they were not evaluated.
