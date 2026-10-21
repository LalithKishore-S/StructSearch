# Step 13: API/database markers

## Added
- `structsearch/graph/markers.py`: the marker table (`DEFAULT_MARKERS`), `match_markers`, `describe_markers`.
- `uses_api` edges in the graph: a unit that calls a marked operation gets an edge `unit -> marker label` with the call-site line and the callee as written (`detail`).
- `CodeGraph.markers_of(unit)` and `CodeGraph.units_with_marker(label)`; `GraphEdge.detail` (optional field, also filled for `calls` edges); graph version 2 (older `graph.json` caches are rebuilt).
- `build_graph(units, markers=DEFAULT_MARKERS)`: a different table can be passed in.
- CLI: `graph --markers` lists the table; `graph UNIT` shows marker edges next to call edges; the overview counts both.
- `tests/test_graph_markers.py`.

## Run
    python -m pytest tests/test_graph_markers.py -q
    python -m structsearch graph --markers
    python -m structsearch graph db.py::get_user

    db.py::get_user
      calls:
        -> db.py::validate_user_input  (calls, line 12, ast_call_name)  via validate_user_input
        -> validation:validate  (uses_api, line 12, ast_marker_call)  via validate_user_input
        -> db:execute  (uses_api, line 13, ast_marker_call)  via db.execute

## Marker set
Label is `<category>:<name>`; edge relation `uses_api`, method `ast_marker_call`.

| label | matches | meaning |
|---|---|---|
| `db:execute` | `x.execute(...)`, `x.executemany(...)`, `x.executescript(...)` | run SQL |
| `db:cursor` | `x.cursor(...)` | open a cursor |
| `db:commit` | `x.commit(...)` | commit a transaction |
| `file:open` | `open(...)` as a plain call | open a file |
| `validation:validate` | a call whose function name contains one of: validate, valid, validation, validator, sanitize, sanitise, sanitizer, verify, verification, check, escape | validation-style step |

Name words are split at `_` and case changes: `is_valid`, `sanitizeHtml`, `form.validate`, `InputValidator` match; `checksum`, `invalidate`, `cleanup`, `escalate`, `validated`, `isinstance` do not.

Sample corpus: 7 marker edges (`db:execute` in `get_user`, `find_user_unsafe`, `count_rows`; `file:open` in `read_config_safe`, `write_log`, `read_lines`; `validation:validate` at line 12 of `get_user`). In `get_user` the validation marker (line 12) comes before `db:execute` (line 13); `find_user_unsafe` has `db:execute` and no validation marker.

## Rules
- Matching is by name, from syntax. The receiver of `x.execute(...)` is not checked: any object with such a method counts.
- `open` is a marker only as a plain call and only when `open` is not a parameter or assigned name of the function; `img.open()` is not.
- `db:` and `file:` markers are added only for calls that did not resolve to a function of the corpus (a corpus function named `open` gives a `calls` edge). Validation markers are added either way, so a call to a corpus validator has a `calls` edge and a `validation:validate` marker at the same line.
- Calls inside nested functions and lambdas count for the enclosing unit; failed units have no edges.

## Limits
- A `validation:validate` marker means the call is named like validation, not that the input is validated or that the check is effective.
- Line numbers give an order of call sites inside a unit, not an execution order: branches, loops and early returns are not modelled.
- Operations reached through aliases, wrappers or other packages with different names are not seen.
- No data flow: nothing says that a validated value is the one passed to `execute`.

## Next
Step 14: graph scoring: map queries to relationships over these edges and export `unit_id -> score` with factual evidence.
