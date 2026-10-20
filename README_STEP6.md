# Step 6 — Fusion (BM25 + structure [+ dense] [+ graph])

No Ollama needed except for `--mode hybrid` with the real embedder (`ollama pull nomic-embed-text`,
as in Step 3b) and the optional `--use-llm` query mapper.

## Apply
Unzip `step6.zip` over your repo root (a clean Step 5 commit), keeping paths.
New: `structsearch/retrieval/fusion.py`, `tests/test_fusion.py`, `README_STEP6.md`
Changed: `structsearch/retrieval/structural.py` (evidence helper made public), `structsearch/interface/cli.py`,
`structsearch/config.py`, `configs/default.yaml` (`hybrid_weights`), `MEMBER1_PLAN.md`

## Run
```bash
python -m pytest -q                                   # expect 383 passed (382 + 1 skip possible on Python 3.11)

# BM25 + structure ("recursive" becomes a structural requirement)
python -m structsearch search "recursive tree traversal" --mode text_ast

# BM25 + dense + structure (real embeddings; add --embedder hashing to try it offline)
python -m structsearch search "check credentials before querying" --mode hybrid

# tune weights on the fly, add your own structural pattern, JSON for scripts
python -m structsearch search "find user" --mode text_ast --pattern "BinOp:Add=>Call:execute" --weight structural=0.5
python -m structsearch search "recursive tree traversal" --mode text_ast --json
```
stderr shows the structural profile and the effective weights; each result starts with the arithmetic:
`fusion: text 1.00x0.67 + structural 1.00x0.33 = 1.000`.

## How the score is built
1. Signals: **text** (BM25), **dense** (cosine, hybrid only), **structural** (fraction of requirements met by the
   count constraints and patterns), **graph** (Member 2, optional).
2. A signal is **active** only if it carries information for the query. A query without structural wording has no
   structural signal; an all-zero BM25 vector is dropped; no graph scores means no graph signal.
3. Each active signal is scaled to [0, 1] over all units: text and graph by their maximum (BM25 has a real zero;
   min-max would wipe out the weakest matching unit), dense by min-max (cosines sit in a narrow band),
   structural as is.
4. Weights come from `weights` (text_ast) or `hybrid_weights` (hybrid) in `configs/default.yaml`, are restricted
   to the active signals and rescaled to sum to 1. Missing signals never lower a score.
5. `final = sum(weight x normalized score)`; ties break by unit_id. RankedResult stores the normalized per-signal
   scores (`text_score`, `structural_score`, `dense_score`, `graph_score`), so `final_score` can be recomputed.

Files that did not parse keep their text/dense scores (still searchable) but get structural score 0 and the
"file did not parse" evidence line.

## For Member 2
`fused_search(..., graph_scores={unit_id: score})` accepts graph scores; absent graph scores are renormalized away.
Evaluation variants to add: `text_ast`, `hybrid` (and `dense`); `dense_score` is set only when dense took part.

## Also included: generic "X before / after / inside / containing Y" reading
`structural.py` now reads queries of the form `<code part> <relation word> <code part>` from a vocabulary
(`VOCAB`, `RELATION_WORDS`), so "call before execute", "validation before query", "try inside a loop",
"loop containing a call", "string concatenation before execute" become patterns without a per-sentence rule.
It runs before the older phrase rules; negation works ("no call before execute" -> `!Call=>Call:execute...`).
This was added to the working tree after `step5.zip` was delivered (not by me in this session); I reviewed it,
its tests are in `tests/test_patterns.py`, and it is part of this zip. One expected-value in the old tests
changed ("exception handling inside a for loop" now maps to the more specific `For//Try`).

## Notes
- With rules only, many queries have no structural wording; `text_ast` then equals plain BM25 (the CLI says so).
  Better query-to-structure mapping is planned (see "Deferred" in MEMBER1_PLAN.md).
- Weights are untuned defaults; tune them on dev queries only (Step 8).

## Next
Step 7: interface polish and grounded explanations (optional Streamlit, optional Ollama explanation from evidence only).
