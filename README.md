# StructSearch

Structure-aware code search and vulnerability-pattern discovery for Python repositories.

StructSearch searches a source-code repository for functions. It ranks them by combining three kinds of evidence and explains every result:

| signal | what it captures | how |
|---|---|---|
| **text** | names, identifiers, docstrings, comments, code words | BM25 over four weighted fields |
| **structure** | control flow and shape of a function (try inside a loop, SQL built before `execute`, ...) | features and tree fragments from the Python AST |
| **call graph** | relationships between functions (calls, recursion, validation before database access) | explicit call edges plus API/database markers |

Plain keyword search finds code that contains the words of a query. It cannot tell a function that *validates and then queries* from one that merely mentions both. Combining the three signals, and showing the evidence behind each rank, is what this project builds and measures.

A bounded **security demo** lists candidate paths from input to SQL text construction. Its results are candidates for human review, never confirmed vulnerabilities (there is no data-flow analysis).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements-ui.txt         # core dependencies + Streamlit
python -m pytest -q                        # about 700 tests, no network needed

python -m structsearch search "queries that run without checking their input" --mode text_ast_graph
python -m streamlit run structsearch/interface/streamlit_app.py
```

The default corpus is the small fixture in `tests/fixtures/sample_corpus` (15 functions plus one file that does not parse). Point `--corpus PATH` at any Python repository to search it. Always run commands from the repository root (the index folder and default paths are relative).

Optional extras: `pip install -r requirements-tolerant.txt` (recover functions from files with syntax errors, `--tolerant`), and a local [Ollama](https://ollama.com) for the dense-embedding mode and LLM-written explanations. Nothing else needs a network.

## How it works

```
repository → functions (stable ids, line ranges)
           → text records      → BM25 index ────────────────┐
           → AST features + tree fragments → structure score ├→ score fusion → ranked results
           → call graph + markers → graph score ─────────────┘     + evidence + explanation
```

1. **Ingestion** splits every Python file into function and method units with ids like `db.py::get_user`. A file that does not parse is kept as one text-searchable unit instead of being dropped.
2. **Text**: an identifier-aware tokenizer (snake_case, camelCase) feeds a four-field BM25 index.
3. **Structure**: 33 AST features plus tree-fragment terms ("a `Try` inside a `For`", "an `If` that ends before a `Call:execute`"). A small pattern language and a query-to-constraints mapper turn wording such as "exception handling inside a loop" into requirements.
4. **Call graph**: functions are nodes; explicit calls are edges. A short documented list of operations (`execute`, `open`, validation-style names) becomes marker edges. Scoring reads relationships such as *validation before database access*, *database access without validation* and *recursion* from the edges, with factual evidence like `edge: get_user -> validate_user_input (call, line 12)`.
5. **Fusion**: each signal is normalized, weighted and summed. A signal with nothing to say about the query (or with weight 0) is dropped and the others are rescaled, so a missing signal never lowers a score. Each result starts with its arithmetic: `fusion: text 0.74x0.50 + graph 1.00x0.50 = 0.868`.

## Search modes

| mode | signals | needs |
|---|---|---|
| `bm25` | text (the baseline) | |
| `structural` | AST structure only | |
| `like` | structure similar to a code snippet (query by example) | |
| `text_ast` | text + structure | |
| `text_graph` | text + call graph | |
| **`text_ast_graph`** | **text + structure + call graph (the full model)** | |
| `dense` | embeddings only | Ollama |
| `hybrid` | text + dense + structure + graph | Ollama |

Weights are in `configs/default.yaml`; they were tuned on the development queries only.

## Commands

```bash
python -m structsearch search "<query>" --mode text_ast_graph -k 5          # ranked results with evidence
python -m structsearch search "<query>" --mode text_ast_graph --explain --json
python -m structsearch search "<query>" --mode text_graph --intent recursive   # fix the graph relationship
python -m structsearch search "<query>" --mode text_ast --weight structural=0.5

python -m structsearch graph                       # the call graph (all edges)
python -m structsearch graph db.py::get_user       # calls, callers and markers of one function
python -m structsearch graph --markers             # the API/database/validation marker table
python -m structsearch security                    # SQL-construction candidates, for human review
python -m structsearch profile "<query>"           # how the query is read structurally
python -m structsearch features trees.py::factorial   # AST features of a function
python -m structsearch fragments db.py::find_user_unsafe --kind ord
python -m structsearch index <corpus> [--tolerant]    # build the indexes

python -m structsearch benchmark check             # validate the benchmark and its freeze lock
python -m structsearch experiment --queries Q --labels L --variants bm25,text_ast_graph --ks 1,3,5 --out results
```

Status messages go to stderr, so `--json` output on stdout stays clean. Exit codes: 0 ok, 2 bad argument or missing corpus, 3 embedding backend problem.

## The app

`python -m streamlit run structsearch/interface/streamlit_app.py` opens a browser page with four tabs:

- **Search**: how the query was understood (the relationship found and the words that triggered it), a stacked bar of what each signal contributed to each result, the evidence graph the ranking used (red edges, with line numbers), and the code with its evidence. The sidebar has example queries, each with the answer expected from the code.
- **Security candidates**: the SQL-construction scan with its source, sink and validation notes.
- **Call graph**: the whole graph grouped by file, with a card per function.
- **Results**: the experiment, interactively: the variants compared, the ablations, a query-by-query comparison with BM25, where the full model improves or fails, and a per-query inspector (test split by default).

## Evaluation

A fixed benchmark of 34 queries (20 development, 14 test; 14 lexical and 20 relationship queries, with paraphrase groups) is judged against all 16 functions of the sample corpus. The labelling protocol, the review sheet and the freeze lock are in `experiments/benchmark/`. Weights were tuned on the development queries only; the test split was run once.

Test split, 14 queries (nDCG@3; K = 1 and 5, MRR, precision and recall are in `experiments/runs/final/report.md`):

| variant | all (14) | lexical (6) | relationship (8) |
|---|---|---|---|
| BM25 | 0.787 | 0.939 | 0.673 |
| text + AST | 0.831 | 0.939 | 0.750 |
| text + graph | 0.896 | 0.939 | 0.865 |
| **text + AST + graph** | **0.952** | 0.939 | **0.962** |
| full minus graph | 0.831 | 0.939 | 0.750 |
| full minus structure | 0.924 | 0.939 | 0.913 |

On the 8 relationship queries the full model beats BM25 on 4 and ties on 4, with no losses. Eight queries cannot reach statistical significance (the smallest possible sign-test p-value is 0.125), so read the counts, not a p-value. Lexical queries are unaffected by the extra signals. The dense and LLM-mapper variants were implemented and unit-tested but not evaluated (no local Ollama was available).

Reproduce:

```bash
experiments/run_experiments.sh tune     # weight grids on the development split (experiments/runs/tuning/)
experiments/run_experiments.sh dev      # all variants and ablations on the development split
experiments/run_experiments.sh final    # the test split, once; refuses to run twice
```

Set `PYTHON=.venv/bin/python` if `python` is not the project environment.

## Limits

- Structure is syntactic and per function: "A before B" means position in the syntax tree, not execution order or data flow. A match is a candidate, not proof.
- The call graph is partial: only explicit calls and a short list of operations. Aliases, dynamic dispatch, calls on other objects and calls into other packages are not modelled.
- Relationship queries are read by a word list: a paraphrase without the usual words gets only a broader relationship, and some words trigger a relationship whatever they mean (for example "file" in "same file").
- The security demo is a syntax-level scan: it cannot tell whether a validation is effective or whether a validated value is the one that reaches the query.
- The benchmark is small (one 16-function corpus, 34 queries) and was written by the authors of the signals. Treat the results as a controlled demonstration, not as evidence about arbitrary code.
- Python only. No learned ranking.

## Repository layout

```
structsearch/
  ingestion/    function segmentation, stable ids, error-tolerant recovery
  indexing/     tokenizer, BM25, dense embeddings
  parsing/      AST features, tree fragments, tolerant parsing
  retrieval/    structural scoring, patterns, query by example, score fusion
  graph/        call graph, markers, graph scoring
  security/     SQL-construction candidate scan
  evaluation/   metrics, benchmark validation and freezing
  experiments/  experiment runner and report tables
  interface/    CLI, search service, explanations, Streamlit app
  llm/          optional Ollama client
configs/        fusion weights and settings (default.yaml)
experiments/    benchmark/ (queries, labels, protocol), runs/ (tuning, dev, final results),
                security_demo/, run_experiments.sh
tests/          unit and integration tests, fixture corpora
```

## Step-by-step documentation

Each implementation step has its own README with commands and design notes.

| step | topic |
|---|---|
| [0](README_STEP0.md) | scaffold, shared record formats, test corpus |
| [1](README_STEP1.md) | ingestion |
| [2](README_STEP2.md) | text index (BM25) |
| [3](README_STEP3.md), [3b](README_STEP3B.md) | search command; dense baseline |
| [4](README_STEP4.md) | AST features |
| [5](README_STEP5.md) | structural retrieval, patterns, query by example |
| [6](README_STEP6.md) | score fusion |
| [7](README_STEP7.md) | interface and explanations |
| [8](README_STEP8.md) | experiment harness |
| [9](README_STEP9.md) | error-tolerant parsing |
| [10](README_STEP10.md) | setup and decisions for the graph and evaluation work |
| [11](README_STEP11.md) | evaluation metrics |
| [12](README_STEP12.md) | call-graph construction |
| [13](README_STEP13.md) | API/database markers |
| [14](README_STEP14.md) | graph scoring |
| [15](README_STEP15.md) | graph in search (`text_graph`, `hybrid`) |
| [16](README_STEP16.md) | benchmark: queries, labels, protocol, freeze |
| [17](README_STEP17.md) | security demo |
| [18](README_STEP18.md) | experiments: tuning, comparison, ablations, test results |
| [19](README_STEP19.md) | Streamlit app: search, security and call-graph tabs |
| [20](README_STEP20.md) | Results tab: experiments inside the app |
