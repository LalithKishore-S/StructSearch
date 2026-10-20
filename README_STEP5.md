# Step 5 — Structural retrieval (counts + tree fragments + patterns + query by example)

Works with no Ollama. Ollama only adds an optional smarter query mapper.

## Apply
Unzip `step5.zip` over your repo root (a clean Step 4 commit), keeping paths. 
New: `structsearch/parsing/fragments.py`, `structsearch/retrieval/{patterns,structural,like}.py`,
`structsearch/llm/{__init__,ollama}.py`, `tests/test_{structural,structural_cli,fragments,patterns,like_cli}.py`
Changed: `structsearch/parsing/{__init__,store}.py`, `structsearch/retrieval/__init__.py`,
`structsearch/interface/cli.py`, `structsearch/config.py` (llm validation), `MEMBER1_PLAN.md`

## Run
```bash
python -m pytest -q                      # expect 331 passed (330 + 1 skip possible on Python 3.11)

# 1. what does the query mean structurally?
python -m structsearch profile "read a file without a context manager"
python -m structsearch profile "retry loop that catches exceptions"

# 2. structural search (counts + patterns), on the fixture corpus or --corpus PATH
python -m structsearch search "sql injection" --mode structural
python -m structsearch search "recursive traversal" --mode structural
python -m structsearch search "x" --mode structural --pattern "BinOp:Add=>Call:execute"

# 3. query by example: find code shaped like a snippet (inline or @file)
python -m structsearch search "q = 'select ' + name
return db.execute(q)" --mode like -k 3
python -m structsearch search "@my_snippet.py" --mode like

# 4. look at a function's structure
python -m structsearch fragments db.py::find_user_unsafe --kind ord
```

## What is stored (in `.structsearch_index/`)
`ast_features.jsonl` (Step 4 counts) and `fragments.jsonl` (new). Both refresh automatically when units change.

## Fragments: how structure is represented
The syntax tree is reduced to a skeleton of meaningful nodes (If, For, Try, With, Call, BinOp, ...). Each
node has a base label and optional specific labels (`Call:open`, `Call:os.system`, `BinOp:Add`,
`ExceptHandler:bare`, `Raise:ValueError`). A function becomes a bag of relation terms:

| term | meaning |
|---|---|
| `ad:For//Try` | a For contains a Try at any depth |
| `pc:For>Try` | a Try is a direct child of a For |
| `ch3:For>If>Try` | three-node chain |
| `ord:If=>Call:execute` | an If ends before a Call:execute starts (and does not contain it) |
| `u:Call:open` | the function has such a node (count) |

So "try inside a loop" and "try after a loop" are different (`ad:For//Try` vs `ord:For=>Try`).

## Patterns
`A//B` contains, `A>B` direct child, `A=>B` before, `!p` must not hold, `p1 or p2`, `A|B` either label,
`c1 and c2` all clauses. Examples:
`For|While//Try`  ·  `Call:open and !With//Call:open`  ·  `BinOp:Add|BinOp:Mod|JoinedStr=>Call:execute`
Natural-language queries map to patterns by rules (try/except in a loop, open without `with`, SQL built by
string formatting, eval/exec, return in a loop) or by the Ollama mapper; `--pattern` adds your own.
Each pattern is one requirement; the unit score is the weighted average of all count constraints and patterns.

## Query by example (`--mode like`)
The snippet becomes the same kind of terms; functions are ranked by BM25 over fragment terms, so rare shared
relations count more. Evidence lists the shared relations (e.g. "BinOp:Add before Call:execute").
Scores are BM25 values (comparable within one query only); fusion in Step 6 normalizes them.

## Limits (be honest in the report)
- Relations are per function, not per variable: "string built before execute" does not prove the string
  reaches execute (no data flow). Treat results as candidates, not confirmed vulnerabilities.
- "Absent" requirements match most small functions; they are useful only combined with a positive part
  (`Call:open and !With//Call:open`) or with text relevance.
- Rule phrases are a fixed list; paraphrases need the LLM mapper. Failed (unparseable) files never match structurally.
- Cross-function relations (caller/callee) belong to Member 2's graph.

## Optional: local LLM mapper (Ollama)
```bash
ollama pull qwen2.5-coder:7b          # or the lighter: ollama pull qwen2.5-coder:3b
ollama serve                          # if not already running
python -m structsearch profile "functions that retry inside a loop and never leave a file open" --use-llm
python -m structsearch search "recursive traversal" --mode structural --use-llm
```
The model must return JSON with `constraints` (checked against the real feature names) and `patterns`
(checked by the pattern parser). Anything invalid, an empty answer, or Ollama being down falls back to the
rules, and a `note:` on stderr says why. `mapper:` in `profile` output shows rules vs `llm:<model>`.
The client is tested against a fake local server only — please run the commands above once and send me the output.

## Next
Step 6: fusion (BM25 + structural, optional dense/graph).
