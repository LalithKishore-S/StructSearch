# Step 17: bounded vulnerability-pattern demonstration

The scan lists **candidates for human review**: functions where input appears to reach the text of an executed SQL statement. It does not show that a vulnerability exists. It uses syntax and the call graph only; there is no data-flow analysis.

Pattern (`PATTERN_QUERY`): *possible paths from external input to SQL query construction with weak or missing validation.*

## Added
- `structsearch/security/sql_candidates.py`: `scan_sql_candidates(units, graph)`, `candidates_to_results`, `level_of`, `PATTERN_QUERY`, `DISCLAIMER`, `NOT_MODELLED`.
- CLI `security`: ranked candidates with evidence (text or `--json`), `-k`, `--min-level`, `--lines`.
- `experiments/security_demo/app.py`: a module that is only parsed, one function per shape the scan reports or leaves out.
- `tests/test_security.py` (28 tests).

## Run
    python -m structsearch security                                   # sample corpus (configured corpus_path)
    python -m structsearch security --corpus experiments/security_demo --min-level medium
    python -m structsearch security --json -k 5
    python -m pytest -q                                               # 621 passed, 1 skipped

Sample corpus (2 candidates, the same two units the benchmark judges relevant for "sql query built by string concatenation"):

    1. db.py::count_rows        score 0.800  level: high
       - source: parameter 'table_name' of count_rows
       - construction: string concatenation at line 24 uses 'table_name'
       - sink: db:execute at line 24 (db.execute) receives the built text directly
       - validation: no validation step before the query
    2. db.py::find_user_unsafe  score 0.800  level: high
       - source: parameter 'username' of find_user_unsafe
       - construction: string concatenation at line 18 uses 'username'
       - sink: db:execute at line 19 (db.execute) receives the built text via variable 'query'
       - validation: no validation step before the query

`db.py::get_user` is not reported: its query text is a constant with a `?` placeholder, and it validates first.

## What is modelled
| element | recognised as |
|---|---|
| source | a parameter of the function (the caller is unknown), or an external-input expression: `input(...)`, `request.*`, `sys.argv`, `os.environ` |
| carrying | a local assigned from an expression that uses a source (`b = a.strip()`); a source-free assignment clears it |
| construction | SQL text built by `+`, `%`, an f-string or `.format()` where a string constant contains an SQL keyword (select, insert, update, delete, drop, create, alter, where, from, values); `q += value` on a local holding SQL text |
| sink | a `db:execute` marker call (execute, executemany, executescript) whose first argument is the built text (directly or through a local), or a parameter / carrier executed as is |
| validation | a `validation:validate` marker before the sink, or a built value that comes from the result of a call named like validation |
| path | a function that passes its own input (positional or keyword argument) to a candidate function, up to 2 calls up; each hop is a call-graph edge |

## Score and level
| case | score |
|---|---|
| external source | 1.0 |
| parameter | 0.8 |
| parameter executed as is | x0.6 |
| built value came through a validation call | x0.3 |
| otherwise a validation step precedes the sink | x0.5 |
| each call hop | x0.7 (x0.5 more if the caller validates before the call) |

Level: high >= 0.7, medium >= 0.35, low below. Validation lowers the rank but never removes a candidate: whether a check is effective is not assessed, and the evidence says so.

Demo module (`experiments/security_demo`): high: `cli_lookup`, `search_by_name` (external source, 1.0), `search_format`, `search_fstring`, `search_percent` (0.8); medium: `lookup` (path, 0.56), `run_query` (0.48), `search_validated_first` (0.40), `endpoint` (two hops, 0.39); low: `handler` (0.34), `search_validated_value` (0.24). Not reported: `search_parameterized` (placeholder), `constant_query` (no input), `validate_name`.

## What is NOT modelled
- data flow across statements beyond simple assignment; loops and branches are not followed (a validation in one branch counts as a validation step); for an expression written directly inside the execute call the state at the end of the function is used
- whether a validation step is effective, or covers the path to the query
- parameterized queries built in another function or by a library; SQL assembled with join/append, ORMs or helper functions
- input arriving through attributes, containers, `*args`/`**kwargs` or callbacks
- aliases, dynamic dispatch, indirect calls; sources other than the listed ones; languages other than Python
- `execute` is recognised by method name on any object (the same name-based rule as the `db:execute` marker)

Every result ends with: `note: candidate for human review, not confirmed; syntax-level evidence only, no data-flow analysis`. The output header and JSON `disclaimer` say the same; the code never uses the word "vulnerable" for a result.

## Next
Step 18: experiments: tune weights on the dev split, run each variant on dev and test (once), ablations, per-category tables.
