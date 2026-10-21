# Labelling protocol

Corpus: `tests/fixtures/sample_corpus` (15 function/method units plus the file-level unit of the file that does not parse: 16 units).
Files: `queries.json` (34 queries), `labels.jsonl` (one label per query and unit: 544 rows), `split.lock` (freeze hashes).

## Pool
Every query is judged against **all 16 units**. A unit is relevant (1) or not relevant (0); there are no unjudged units, so Recall@K has an exact denominator. The file-level unit of the unparseable file is never relevant.

## Judging
Judge from the code of the unit, never from a ranking. Do not run a search before labelling a query.

| category | a unit is relevant when |
|---|---|
| `lexical` | its code does what the query describes (the query names the task, not the structure) |
| `relationship` | its code has the structure or relationship the query asks for, as written in the source |

Rules for relationship queries:
- *validate before database access*: the unit calls a validation step and then runs the SQL statement itself (or calls a function that does). A validator alone, or a database function without a validation step, is not relevant.
- *database access without validation*: the unit runs SQL built from its arguments and no validation step precedes it.
- *recursive*: the unit calls itself. *Tree traversal* additionally requires walking a tree.
- *file access with / without error handling*: the unit opens a file inside / outside a `try` that catches exceptions.
- Structure only counts as written. Behaviour that depends on runtime values (what a caller passes in) is not judged.
- When unsure, mark not relevant and add a note; both reviewers settle it before the freeze.

## Paraphrases
Queries with the same `group` ask for the same thing in different wording and have identical labels. Paraphrases stay in the same split. Some paraphrases deliberately avoid the usual keywords (R04) to measure how well the query reading copes with wording.

## Splits
Fixed before any experiment: 20 dev queries (tuning allowed), 14 test queries (reported once). Both splits contain lexical and relationship queries. Never move a query between splits after looking at results.

## Review and freeze
1. Both reviewers read `notes` in `queries.json` and independently re-judge a sample of queries (at least a third, including every paraphrase group) against the code.
2. Disagreements are settled by editing `labels.jsonl` (and `notes`).
3. `python -m structsearch benchmark check` must report 0 problems.
4. `python -m structsearch benchmark freeze` writes `split.lock`. After the freeze, `check` reports any change to queries, splits or labels. Re-freeze only before tuning starts; once weights are tuned on dev, labels stay as they are.
