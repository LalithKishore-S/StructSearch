# Step 18: experiments (tuning, comparison, ablations)

Status: **done.** Weights were tuned and frozen on the dev split; the test split was then run once (`experiments/runs/final/`). The label review took place before the test run and changed no label (the freeze lock matched at the time of the run).

## Added
- Mode `text_ast_graph`: BM25 + AST structure + call graph, the plan's full hybrid without dense embeddings (`text_ast_graph_weights` in the config). `hybrid` (BM25 + dense + structure + graph) stays as the extended variant.
- Ablation variants: `<mode>-<signal>` removes a signal, e.g. `text_ast_graph-graph`, `text_ast_graph-structural`, `text_ast_graph-text`.
- `structsearch/experiments/report.py`: metrics at several K from one run, paired comparison against a baseline (wins / ties / losses per query, mean difference, exact sign test), `report.md`, `summary_by_k.csv`, `paired.csv`.
- CLI `experiment`: `--ks 1,3,5`, `--baseline`, `--min-weight` (with `--tune`), a tuning log per run, `run.json` (variants, weights, benchmark lock hashes).
- `experiments/run_experiments.sh tune|dev|final`: the whole procedure; `final` asks for confirmation and requires a valid, frozen benchmark.
- `experiments/runs/tuning/` (weight grids) and `experiments/runs/dev/` (dev tables), both reproduced identically by the script.
- `tests/test_experiment_suite.py` (21 tests); three tests in `test_fusion.py` and `test_graph_integration.py` now read the weights from the config.

## Method (fixed before the numbers were looked at, except where stated)
- Tuning on the 20 dev queries only; the test queries are not read (a test removes all test labels and checks tuning is unaffected).
- Grid step 0.25 over the signal weights of a mode, selection metric nDCG@3, ties on nDCG and MRR go to the more text-heavy weights.
- **Added after seeing the first dev results:** every signal of a fused mode keeps a weight of at least 0.25 (`--min-weight 0.25`). Without it the optimum of the full mode gives the structure signal weight 0, so the "full" variant would be Text+Graph under another name and the structure ablation would be empty. Both grids are kept in `experiments/runs/tuning/`.
- Metrics at K = 1, 3, 5. With 16 units K = 10 would cover most of the corpus.
- Baseline of every comparison: BM25. A test checks that the other modes with their extra signals removed rank exactly like BM25 on every dev query.

## A defect found and fixed during this step
Removing a signal with weight 0 did not always remove it: when BM25 matched nothing, fusion's "equal weights if all active weights are 0" fallback gave the zero-weighted signal full weight, so `text=1, structural=0` ranked by structure for such queries. The first tuning rows with a zero weight were contaminated (text-only looked better than BM25, 0.862 vs 0.812). Fusion now drops signals whose weight is 0 (unless every weight is 0); tests cover it, and all tuning and dev numbers here were produced after the fix.

## Frozen weights (`configs/default.yaml`)
| mode | weights | dev nDCG@3 |
|---|---|---|
| `text_ast` | text 0.75, structural 0.25 | 0.856 |
| `text_graph` | text 0.5, graph 0.5 | 0.950 |
| `text_ast_graph` | text 0.25, structural 0.25, graph 0.5 | 0.950 |
| `hybrid` | text 0.4, dense 0.3, structural 0.2, graph 0.1 (not tuned: no Ollama embeddings available) | not run |

## Dev results (20 queries; the weights were tuned on these queries, so the numbers are optimistic)
nDCG@3 / MRR, K = 3:

| variant | all (n=20) | lexical (n=8) | relationship (n=12) |
|---|---|---|---|
| bm25 | 0.812 / 0.850 | 1.000 / 1.000 | 0.687 / 0.750 |
| text_ast | 0.856 / 0.850 | 1.000 / 1.000 | 0.760 / 0.750 |
| text_graph | 0.950 / 0.950 | 1.000 / 1.000 | 0.917 / 0.917 |
| text_ast_graph (full) | 0.950 / 0.950 | 1.000 / 1.000 | 0.917 / 0.917 |
| full minus text | 0.900 / 0.883 | 0.938 / 0.917 | 0.875 / 0.861 |
| full minus structural | 0.950 / 0.950 | 1.000 / 1.000 | 0.917 / 0.917 |
| full minus graph | 0.828 / 0.825 | 1.000 / 1.000 | 0.714 / 0.708 |

Paired against BM25, relationship queries (n=12), nDCG@3: text_graph and the full mode win on 5 queries, tie on 7, lose on 0 (sign test p = 0.0625); text_ast wins 3, ties 7, loses 2 (p = 1.0). At K = 1 the graph variants win 3 and lose 0; text_ast wins 1 and loses 2.

What this suggests, on dev only:
- The call-graph signal accounts for the gain on relationship queries; removing it returns the full mode to roughly the AST-only level.
- The AST structure signal alone helps recall at K = 3 and 5 (R@3 0.71 -> 0.88) but hurts the top rank (K = 1: nDCG 0.667 -> 0.583).
- With the graph present, structure adds nothing on dev: the full mode and "full minus structural" are identical.
- Lexical queries are saturated (BM25 already scores 1.000), so they cannot separate the variants; only removing the text signal costs anything there.
- One dev relationship query stays unsolved by every variant (R12, "calls another function defined in the same file"): BM25 does not find it, and the graph mapper reads the word "file" as `file_access`, a spurious relationship that happens to change nothing here.
- The graph gain comes from the queries whose wording the mapper recognises (R02, R05, R06, R07, R08 are the five wins). R04, the paraphrase with none of the validation words, is read as plain database access: no loss, no gain.

## Not evaluated
- `dense` and `hybrid` (and `+llm` mapper variants): they need a local Ollama server, which was not available. They are implemented and unit-tested against fakes only, and are reported as not evaluated.

## Test results (14 queries, run once with the frozen weights)
nDCG@3 / MRR at K = 3 (K = 1 and K = 5 in `experiments/runs/final/report.md`):

| variant | all (n=14) | lexical (n=6) | relationship (n=8) |
|---|---|---|---|
| bm25 | 0.787 / 0.821 | 0.939 / 0.917 | 0.673 / 0.750 |
| text_ast | 0.831 / 0.857 | 0.939 / 0.917 | 0.750 / 0.812 |
| text_graph | 0.896 / 0.881 | 0.939 / 0.917 | 0.865 / 0.854 |
| text_ast_graph (full) | **0.952 / 0.929** | 0.939 / 0.917 | **0.962 / 0.938** |
| full minus text | 0.851 / 0.786 | 0.826 / 0.750 | 0.869 / 0.812 |
| full minus structural | 0.924 / 0.893 | 0.939 / 0.917 | 0.913 / 0.875 |
| full minus graph | 0.831 / 0.857 | 0.939 / 0.917 | 0.750 / 0.812 |

Paired against BM25 (nDCG@3, relationship queries, n = 8): full mode 4 wins / 4 ties / 0 losses (mean +0.288); text_graph 4 / 4 / 0 (+0.192); text_ast 2 / 6 / 0 (+0.077). No variant loses to BM25 on any test query. With 8 queries the smallest possible sign-test p-value is 0.125 (4 wins, 0 losses), so no comparison can be called significant at 0.05 however clean the sweep; the counts are the evidence.

Where it changes (nDCG@5, per query): R13 (SQL by concatenation) BM25 0.61 -> text_ast / full 1.00; R14 (its paraphrase) 0.39 -> graph variants 1.00, so the graph reaches the paraphrase that BM25 and the AST signal miss; R16 / R17 (opens a file without error handling and its paraphrase) BM25 0.62 / 0.00 -> full 1.00 / 0.69; R15, R18, R19, R20 and all lexical queries except L12 are already at 1.00 for every variant. L12 (create a tree node with left and right children) is 0.63 for every variant: the relevant unit is found at rank 2 by all of them.

What this suggests:
- The direction seen on dev holds on held-out queries: the full text + AST + graph model is best, BM25 alone is worst on relationship queries, and lexical queries are unaffected by the extra signals.
- Removing the graph costs the most (0.962 -> 0.750 on relationship queries); removing structure costs less (0.962 -> 0.913); removing text costs on lexical queries (0.939 -> 0.826), as expected.
- Unlike on dev, structure contributes on the test queries (R13, R16): dev had shown it adding nothing once the graph was present. With a handful of queries that difference can be one or two queries, so neither result should be read as a stable property of the signal.
- At K = 1 the full mode is still best (nDCG 0.857 vs 0.714 for BM25).

Not unbiased in one respect: the test queries are paraphrase groups and relationship types written by the same people who built the signals; they test generalization to other wording and other queries of those types, not to other code.

## Reproduce
    experiments/run_experiments.sh tune     # logs in experiments/runs/tuning/
    experiments/run_experiments.sh dev      # experiments/runs/dev/
    experiments/run_experiments.sh final    # test split, once: refuses to run twice (experiments/runs/final/run.json exists)

## Limits
- 20 dev and 14 test queries on 16 units: differences of one or two queries are not meaningful; the paired tables show counts for that reason.
- The dev numbers were tuned on the same queries and are optimistic; the test numbers are the estimate, and with 14 queries (8 relationship) it is a coarse one.
- The graph mapper is a word list and the benchmark was written by the same people who built the graph relationships, so the relationship queries partly reflect what the graph can express. The paraphrase groups (including one wording without validation words) are the check on that, to be analysed in Step 19.

## Next
Step 19: error analysis, plots and the report sections, using `experiments/runs/final/`.
