#!/usr/bin/env bash
# Reproduces the Step 18 experiments.
#   experiments/run_experiments.sh tune    weight grids on the DEV split (logs in experiments/runs/tuning/)
#   experiments/run_experiments.sh dev     all variants and ablations on DEV with the weights in configs/default.yaml
#   experiments/run_experiments.sh final   the TEST split as well, once; weights must already be frozen
# Choose weights from the tuning logs and write them to configs/default.yaml between `tune` and `dev`.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
CORPUS=tests/fixtures/sample_corpus
QUERIES=experiments/benchmark/queries.json
LABELS=experiments/benchmark/labels.jsonl
INDEX=${INDEX_DIR:-.structsearch_index_runs}
VARIANTS="bm25,text_ast,text_graph,text_ast_graph,text_ast_graph-text,text_ast_graph-structural,text_ast_graph-graph"
KS=1,3,5

run() { "$PY" -m structsearch experiment --queries "$QUERIES" --labels "$LABELS" --corpus "$CORPUS" --index-dir "$INDEX" "$@"; }

# the benchmark must be valid and frozen (exit code 2 stops the script)
report=$("$PY" -m structsearch benchmark check --corpus "$CORPUS") || { echo "$report"; echo "benchmark check failed"; exit 2; }
echo "$report" | grep -q '^frozen: yes' || { echo "benchmark is not frozen (run: $PY -m structsearch benchmark freeze)"; exit 2; }

case "${1:-}" in
  tune)
    for mode in text_ast text_graph text_ast_graph; do
      run --out experiments/runs/tuning --tune "$mode" -k 3 --step 0.25                    # free grid (diagnostic)
      run --out experiments/runs/tuning --tune "$mode" -k 3 --step 0.25 --min-weight 0.25  # every signal kept (selected)
    done ;;
  dev)
    run --out experiments/runs/dev --variants "$VARIANTS" --ks "$KS" --baseline bm25 ;;
  final)
    if [ -e experiments/runs/final/run.json ]; then
      echo "the test split was already run (experiments/runs/final/run.json); it is run once. Delete that folder only if the benchmark or weights were deliberately changed and the change is reported."
      exit 1
    fi
    read -r -p "Run the TEST split now? Weights must be frozen and labels reviewed [type 'yes']: " answer
    [ "$answer" = "yes" ] || { echo "not run"; exit 1; }
    run --out experiments/runs/final --variants "$VARIANTS" --ks "$KS" --baseline bm25 --final ;;
  *)
    echo "usage: $0 tune|dev|final"; exit 2 ;;
esac
