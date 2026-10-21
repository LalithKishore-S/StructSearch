# Step 12: code graph construction

## Added
- `structsearch/graph/model.py`: `GraphNode`, `GraphEdge`, `AmbiguousCall`, `CodeGraph` (queries and JSON round trip).
- `structsearch/graph/builder.py`: `build_graph(units)`.
- `structsearch/graph/store.py`: `ensure_graph(units, index_dir)` caches `graph.json` next to the other index files (graph version + unit fingerprint; rebuilt when either changes).
- CLI `graph`: the call graph of the corpus, or the calls and callers of one unit.
- `tests/test_graph.py`: known edges of the sample corpus, every resolution rule, persistence and the CLI.

## Run
    python -m pytest tests/test_graph.py -q
    python -m structsearch graph                                  # all edges
    python -m structsearch graph db.py::get_user                  # calls and callers of one unit
    python -m structsearch graph --json
Options as for `features`/`fragments`: `--corpus`, `--index-dir`, `--skip-failed`, `--tolerant`, `--rebuild`.

On the sample corpus the graph has 16 nodes and 4 edges:

    db.py::get_user            -> db.py::validate_user_input   (line 12)
    trees.py::factorial        -> trees.py::factorial          (line 21)
    trees.py::inorder_traverse -> trees.py::inorder_traverse   (lines 12 and 14)

## Schema
Node: one per code unit (including failed file-level units), keyed by `unit_id`.

| field | meaning |
|---|---|
| `unit_id` | the stable unit id from ingestion |
| `name`, `qualname` | function name; `Class.method` or `function` |
| `file_path` | relative path |
| `parse_status` | `ok`, `partial` or `failed` |

Edge: one per call site.

| field | meaning |
|---|---|
| `source` | unit_id of the caller |
| `target` | unit_id (relation `calls`) or marker label (relation `uses_api`, Step 13) |
| `relation` | `calls` or `uses_api` |
| `method` | how the edge was found, see below |
| `line` | 1-based file line of the call site |

Edge methods for `calls`:

| method | written as | resolves to |
|---|---|---|
| `ast_call_name` | `name(...)` | a function with that name: same file first, else the only one in the corpus |
| `ast_constructor_call` | `ClassName(...)` | `ClassName.__init__`, resolved like a function name |
| `ast_self_method` | `self.name(...)`, `cls.name(...)` | method `name` of the same class |
| `ast_class_method` | `ClassName.name(...)` | method `name` of a class defined in the same file |

`CodeGraph` queries: `edges_from(unit, relation=None)` (call-site order), `edges_to`, `callees`, `callers`, `has_edge`. Calls whose name matches several units create no edge and are kept in `graph.ambiguous`.

## What is and is not modelled
The graph is partial: an edge is something observed in the code, a missing edge is not evidence of absence.

Modelled: explicit calls as listed above, including recursion (an edge from a unit to itself) and calls inside nested functions and lambdas of a unit (attributed to the unit). Local names (parameters, assigned names, imports, nested definitions) are not treated as calls to a corpus function of the same name, so a callback parameter such as `visit` creates no edge; variables of a comprehension stay inside it and do not shadow calls elsewhere in the unit.

Not modelled:
- `obj.method(...)` on any other object, `super().method(...)`, inherited methods
- aliases and rebinding (`g = f; g()`, `import x as y`), dynamic dispatch, callbacks passed as arguments, `getattr`/`eval`
- calls into the standard library and other packages (the listed API/database/validation operations are `uses_api` edges, see Step 13)
- ambiguous names (several candidates): no edge, listed in `graph.ambiguous`
- calls in decorators and default values (not part of the unit body)
- data flow and execution order beyond the call-site line

Units that did not parse get a node and no edges and are never an edge target (so a file named like a called function cannot attract edges). Partial units (`--tolerant`) contribute the calls of their surviving lines; their line numbers are approximate when repaired lines were skipped.

## Next
Step 13: API/database markers (`uses_api` edges).

Step 13 adds an optional edge field `detail` (the callee as written) and raises the graph version to 2; older `graph.json` caches are rebuilt automatically.
