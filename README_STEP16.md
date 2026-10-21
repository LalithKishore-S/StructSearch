# Step 16: benchmark (queries, labels, protocol, freeze)

## Added
- `experiments/benchmark/queries.json`: 34 queries on `tests/fixtures/sample_corpus`, each with category, split, optional paraphrase `group` and a `notes` line saying why the labels are what they are.
- `experiments/benchmark/labels.jsonl`: 544 labels, every query judged against all 16 units (EvaluationLabel fields).
- `experiments/benchmark/PROTOCOL.md`: labelling protocol, paraphrase and split rules, review and freeze procedure.
- `experiments/benchmark/REVIEW.md`: review sheet generated from the two files (corpus code, every query with its proposed answer, columns for two reviewers).
- `experiments/benchmark/split.lock`: hashes of the queries (text, category, split) and the labels, written by `benchmark freeze`.
- `structsearch/evaluation/labels.py`: `read_records`, `check_benchmark`, `freeze_benchmark` (also used by the experiment runner for reading files).
- CLI: `benchmark check` and `benchmark freeze`.
- `tests/test_benchmark_labels.py` (validator, 15 tests), `tests/test_benchmark_data.py` (the shipped benchmark, 8 tests).

## Run
    python -m structsearch benchmark check              # structure, pool, groups, freeze lock; exit code 2 on problems
    python -m structsearch benchmark freeze             # only for a benchmark without problems
    python -m structsearch experiment --queries experiments/benchmark/queries.json \
        --labels experiments/benchmark/labels.jsonl --variants bm25,text_ast,text_graph --out results -k 3
    python -m pytest -q                                 # 593 passed, 1 skipped

## The benchmark
| | lexical | relationship | total |
|---|---|---|---|
| dev (tuning allowed) | 8 | 12 | 20 |
| test (reported once) | 6 | 8 | 14 |

- Relationship queries cover validation before database access, database access without validation, recursion, file access with and without error handling, SQL built by concatenation, loops, raising, calls inside a file, and tree traversal. 7 paraphrase groups hold 2-4 wordings of the same intent; one wording (R04) avoids the usual validation words on purpose.
- Paraphrase groups are kept in one split, so a reworded dev query cannot leak into test; the validator enforces this, together with identical labels inside a group.
- The split was fixed before any experiment was run.

## What `check` verifies
Required fields, unique ids and texts, known categories and splits; one label per (query, unit) with integer relevance, category and split equal to the query's; at least one relevant unit per query; a complete pool (all 16 units judged for every query); paraphrase-group consistency; and, if `split.lock` exists, that nothing changed since the freeze. Warnings: size outside 20-40, a split without both categories, no freeze.

## Judgements checked against the code
`tests/test_benchmark_data.py` compares the hand judgements with facts read from the code: the recursion queries are exactly the units whose AST has a self call; file queries split the `file:open` units by presence of a `try`; "validate before database access" is the unit whose validation marker precedes `db:execute`, "without validation" the other `db:execute` units; the loop and raise queries match `while_count` and `raise_count`. These checks guard against typos and drift. They do not replace review: the labels are judgements, and they were written by reading the code, not by a second person.

## Limits
- 16 units: lexical queries are near-saturated for BM25 (a single obvious function per query), so lexical results will not discriminate between variants; the relationship queries carry the comparison. Metrics at K = 1, 3, 5.
- 34 queries and 8 paraphrase groups: differences between variants of a few queries are not statistically meaningful; report counts next to the means.
- Labels for relationship queries follow the written protocol (structure as written, not runtime behaviour). A different reading of "validates before querying" would change them.

## Review still to do
Two reviewers should re-judge at least a third of the queries, including every paraphrase group, following `PROTOCOL.md`, then edit `labels.jsonl` if needed, run `benchmark check` and re-freeze. This must happen before tuning starts.

## Next
Step 17: the bounded vulnerability-pattern demonstration in `structsearch/security/`: candidates for review, never confirmed vulnerabilities.
