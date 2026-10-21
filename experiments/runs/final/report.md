# Report

Variants: bm25, text_ast, text_graph, text_ast_graph, text_ast_graph-text, text_ast_graph-structural, text_ast_graph-graph.  K = 1, 3, 5.  Metrics are recomputed from the rankings of one run.

## dev / all (n = 20)

K = 1

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.800 | 0.750 | 0.800 | 0.800 | 0.800 |
| text_ast | 0.750 | 0.675 | 0.750 | 0.750 | 0.750 |
| text_graph | 0.950 | 0.850 | 0.950 | 0.950 | 0.950 |
| text_ast_graph | 0.950 | 0.850 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-text | 0.850 | 0.750 | 0.850 | 0.850 | 0.850 |
| text_ast_graph-structural | 0.950 | 0.850 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-graph | 0.750 | 0.675 | 0.750 | 0.750 | 0.750 |

K = 3

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.300 | 0.825 | 0.850 | 0.812 | 0.900 |
| text_ast | 0.367 | 0.925 | 0.850 | 0.856 | 0.950 |
| text_graph | 0.383 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph | 0.383 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-text | 0.383 | 0.950 | 0.883 | 0.900 | 0.950 |
| text_ast_graph-structural | 0.383 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-graph | 0.350 | 0.875 | 0.825 | 0.828 | 0.900 |

K = 5

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.180 | 0.825 | 0.850 | 0.812 | 0.900 |
| text_ast | 0.220 | 0.925 | 0.850 | 0.856 | 0.950 |
| text_graph | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-text | 0.230 | 0.950 | 0.883 | 0.900 | 0.950 |
| text_ast_graph-structural | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-graph | 0.210 | 0.875 | 0.825 | 0.828 | 0.900 |

## dev / lexical (n = 8)

K = 1

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_graph | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-text | 0.875 | 0.875 | 0.875 | 0.875 | 0.875 |
| text_ast_graph-structural | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-graph | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

K = 3

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_graph | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-text | 0.333 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-structural | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-graph | 0.333 | 1.000 | 1.000 | 1.000 | 1.000 |

K = 5

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_graph | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-text | 0.200 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-structural | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-graph | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |

## dev / relationship (n = 12)

K = 1

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.667 | 0.583 | 0.667 | 0.667 | 0.667 |
| text_ast | 0.583 | 0.458 | 0.583 | 0.583 | 0.583 |
| text_graph | 0.917 | 0.750 | 0.917 | 0.917 | 0.917 |
| text_ast_graph | 0.917 | 0.750 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-text | 0.833 | 0.667 | 0.833 | 0.833 | 0.833 |
| text_ast_graph-structural | 0.917 | 0.750 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-graph | 0.583 | 0.458 | 0.583 | 0.583 | 0.583 |

K = 3

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.278 | 0.708 | 0.750 | 0.687 | 0.833 |
| text_ast | 0.389 | 0.875 | 0.750 | 0.760 | 0.917 |
| text_graph | 0.417 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph | 0.417 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-text | 0.417 | 0.917 | 0.861 | 0.875 | 0.917 |
| text_ast_graph-structural | 0.417 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-graph | 0.361 | 0.792 | 0.708 | 0.714 | 0.833 |

K = 5

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.167 | 0.708 | 0.750 | 0.687 | 0.833 |
| text_ast | 0.233 | 0.875 | 0.750 | 0.760 | 0.917 |
| text_graph | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-text | 0.250 | 0.917 | 0.861 | 0.875 | 0.917 |
| text_ast_graph-structural | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-graph | 0.217 | 0.792 | 0.708 | 0.714 | 0.833 |

## test / all (n = 14)

K = 1

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.714 | 0.643 | 0.714 | 0.714 | 0.714 |
| text_ast | 0.786 | 0.679 | 0.786 | 0.786 | 0.786 |
| text_graph | 0.786 | 0.679 | 0.786 | 0.786 | 0.786 |
| text_ast_graph | 0.857 | 0.714 | 0.857 | 0.857 | 0.857 |
| text_ast_graph-text | 0.571 | 0.464 | 0.571 | 0.571 | 0.571 |
| text_ast_graph-structural | 0.786 | 0.679 | 0.786 | 0.786 | 0.786 |
| text_ast_graph-graph | 0.786 | 0.679 | 0.786 | 0.786 | 0.786 |

K = 3

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.333 | 0.821 | 0.821 | 0.787 | 0.929 |
| text_ast | 0.357 | 0.857 | 0.857 | 0.831 | 0.929 |
| text_graph | 0.429 | 0.964 | 0.881 | 0.896 | 1.000 |
| text_ast_graph | 0.452 | 1.000 | 0.929 | 0.952 | 1.000 |
| text_ast_graph-text | 0.452 | 1.000 | 0.786 | 0.851 | 1.000 |
| text_ast_graph-structural | 0.452 | 1.000 | 0.893 | 0.924 | 1.000 |
| text_ast_graph-graph | 0.357 | 0.857 | 0.857 | 0.831 | 0.929 |

K = 5

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.214 | 0.857 | 0.821 | 0.804 | 0.929 |
| text_ast | 0.229 | 0.893 | 0.857 | 0.848 | 0.929 |
| text_graph | 0.271 | 1.000 | 0.881 | 0.915 | 1.000 |
| text_ast_graph | 0.271 | 1.000 | 0.929 | 0.952 | 1.000 |
| text_ast_graph-text | 0.271 | 1.000 | 0.786 | 0.851 | 1.000 |
| text_ast_graph-structural | 0.271 | 1.000 | 0.893 | 0.924 | 1.000 |
| text_ast_graph-graph | 0.229 | 0.893 | 0.857 | 0.850 | 0.929 |

## test / lexical (n = 6)

K = 1

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.833 | 0.750 | 0.833 | 0.833 | 0.833 |
| text_ast | 0.833 | 0.750 | 0.833 | 0.833 | 0.833 |
| text_graph | 0.833 | 0.750 | 0.833 | 0.833 | 0.833 |
| text_ast_graph | 0.833 | 0.750 | 0.833 | 0.833 | 0.833 |
| text_ast_graph-text | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| text_ast_graph-structural | 0.833 | 0.750 | 0.833 | 0.833 | 0.833 |
| text_ast_graph-graph | 0.833 | 0.750 | 0.833 | 0.833 | 0.833 |

K = 3

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.389 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast | 0.389 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_graph | 0.389 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph | 0.389 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-text | 0.389 | 1.000 | 0.750 | 0.826 | 1.000 |
| text_ast_graph-structural | 0.389 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-graph | 0.389 | 1.000 | 0.917 | 0.938 | 1.000 |

K = 5

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_graph | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-text | 0.233 | 1.000 | 0.750 | 0.826 | 1.000 |
| text_ast_graph-structural | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-graph | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |

## test / relationship (n = 8)

K = 1

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.625 | 0.562 | 0.625 | 0.625 | 0.625 |
| text_ast | 0.750 | 0.625 | 0.750 | 0.750 | 0.750 |
| text_graph | 0.750 | 0.625 | 0.750 | 0.750 | 0.750 |
| text_ast_graph | 0.875 | 0.688 | 0.875 | 0.875 | 0.875 |
| text_ast_graph-text | 0.625 | 0.438 | 0.625 | 0.625 | 0.625 |
| text_ast_graph-structural | 0.750 | 0.625 | 0.750 | 0.750 | 0.750 |
| text_ast_graph-graph | 0.750 | 0.625 | 0.750 | 0.750 | 0.750 |

K = 3

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.292 | 0.688 | 0.750 | 0.673 | 0.875 |
| text_ast | 0.333 | 0.750 | 0.812 | 0.750 | 0.875 |
| text_graph | 0.458 | 0.938 | 0.854 | 0.865 | 1.000 |
| text_ast_graph | 0.500 | 1.000 | 0.938 | 0.962 | 1.000 |
| text_ast_graph-text | 0.500 | 1.000 | 0.812 | 0.869 | 1.000 |
| text_ast_graph-structural | 0.500 | 1.000 | 0.875 | 0.913 | 1.000 |
| text_ast_graph-graph | 0.333 | 0.750 | 0.812 | 0.750 | 0.875 |

K = 5

| variant | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|
| bm25 | 0.200 | 0.750 | 0.750 | 0.703 | 0.875 |
| text_ast | 0.225 | 0.812 | 0.812 | 0.780 | 0.875 |
| text_graph | 0.300 | 1.000 | 0.854 | 0.898 | 1.000 |
| text_ast_graph | 0.300 | 1.000 | 0.938 | 0.962 | 1.000 |
| text_ast_graph-text | 0.300 | 1.000 | 0.812 | 0.869 | 1.000 |
| text_ast_graph-structural | 0.300 | 1.000 | 0.875 | 0.913 | 1.000 |
| text_ast_graph-graph | 0.225 | 0.812 | 0.812 | 0.783 | 0.875 |

## Paired comparison against bm25

Per query, difference in nDCG@K to the baseline (wins: better than the baseline). p is a two-sided sign test over wins and losses; with this few queries it has little power.

| variant | split | category | k | n | wins | ties | losses | mean_diff | p_value |
|---|---|---|---|---|---|---|---|---|---|
| text_ast | dev | all | 1 | 20 | 1 | 17 | 2 | -0.050 | 1.000 |
| text_ast | dev | lexical | 1 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast | dev | relationship | 1 | 12 | 1 | 9 | 2 | -0.083 | 1.000 |
| text_ast | test | all | 1 | 14 | 1 | 13 | 0 | +0.071 | 1.000 |
| text_ast | test | lexical | 1 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast | test | relationship | 1 | 8 | 1 | 7 | 0 | +0.125 | 1.000 |
| text_graph | dev | all | 1 | 20 | 3 | 17 | 0 | +0.150 | 0.250 |
| text_graph | dev | lexical | 1 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_graph | dev | relationship | 1 | 12 | 3 | 9 | 0 | +0.250 | 0.250 |
| text_graph | test | all | 1 | 14 | 1 | 13 | 0 | +0.071 | 1.000 |
| text_graph | test | lexical | 1 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_graph | test | relationship | 1 | 8 | 1 | 7 | 0 | +0.125 | 1.000 |
| text_ast_graph | dev | all | 1 | 20 | 3 | 17 | 0 | +0.150 | 0.250 |
| text_ast_graph | dev | lexical | 1 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph | dev | relationship | 1 | 12 | 3 | 9 | 0 | +0.250 | 0.250 |
| text_ast_graph | test | all | 1 | 14 | 2 | 12 | 0 | +0.143 | 0.500 |
| text_ast_graph | test | lexical | 1 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph | test | relationship | 1 | 8 | 2 | 6 | 0 | +0.250 | 0.500 |
| text_ast_graph-text | dev | all | 1 | 20 | 3 | 15 | 2 | +0.050 | 1.000 |
| text_ast_graph-text | dev | lexical | 1 | 8 | 0 | 7 | 1 | -0.125 | 1.000 |
| text_ast_graph-text | dev | relationship | 1 | 12 | 3 | 8 | 1 | +0.167 | 0.625 |
| text_ast_graph-text | test | all | 1 | 14 | 2 | 8 | 4 | -0.143 | 0.688 |
| text_ast_graph-text | test | lexical | 1 | 6 | 0 | 4 | 2 | -0.333 | 0.500 |
| text_ast_graph-text | test | relationship | 1 | 8 | 2 | 4 | 2 | +0.000 | 1.000 |
| text_ast_graph-structural | dev | all | 1 | 20 | 3 | 17 | 0 | +0.150 | 0.250 |
| text_ast_graph-structural | dev | lexical | 1 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph-structural | dev | relationship | 1 | 12 | 3 | 9 | 0 | +0.250 | 0.250 |
| text_ast_graph-structural | test | all | 1 | 14 | 1 | 13 | 0 | +0.071 | 1.000 |
| text_ast_graph-structural | test | lexical | 1 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph-structural | test | relationship | 1 | 8 | 1 | 7 | 0 | +0.125 | 1.000 |
| text_ast_graph-graph | dev | all | 1 | 20 | 1 | 17 | 2 | -0.050 | 1.000 |
| text_ast_graph-graph | dev | lexical | 1 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph-graph | dev | relationship | 1 | 12 | 1 | 9 | 2 | -0.083 | 1.000 |
| text_ast_graph-graph | test | all | 1 | 14 | 1 | 13 | 0 | +0.071 | 1.000 |
| text_ast_graph-graph | test | lexical | 1 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph-graph | test | relationship | 1 | 8 | 1 | 7 | 0 | +0.125 | 1.000 |
| text_ast | dev | all | 3 | 20 | 3 | 15 | 2 | +0.044 | 1.000 |
| text_ast | dev | lexical | 3 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast | dev | relationship | 3 | 12 | 3 | 7 | 2 | +0.073 | 1.000 |
| text_ast | test | all | 3 | 14 | 2 | 12 | 0 | +0.044 | 0.500 |
| text_ast | test | lexical | 3 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast | test | relationship | 3 | 8 | 2 | 6 | 0 | +0.077 | 0.500 |
| text_graph | dev | all | 3 | 20 | 5 | 15 | 0 | +0.138 | 0.062 |
| text_graph | dev | lexical | 3 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_graph | dev | relationship | 3 | 12 | 5 | 7 | 0 | +0.230 | 0.062 |
| text_graph | test | all | 3 | 14 | 4 | 10 | 0 | +0.109 | 0.125 |
| text_graph | test | lexical | 3 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_graph | test | relationship | 3 | 8 | 4 | 4 | 0 | +0.192 | 0.125 |
| text_ast_graph | dev | all | 3 | 20 | 5 | 15 | 0 | +0.138 | 0.062 |
| text_ast_graph | dev | lexical | 3 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph | dev | relationship | 3 | 12 | 5 | 7 | 0 | +0.230 | 0.062 |
| text_ast_graph | test | all | 3 | 14 | 4 | 10 | 0 | +0.165 | 0.125 |
| text_ast_graph | test | lexical | 3 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph | test | relationship | 3 | 8 | 4 | 4 | 0 | +0.288 | 0.125 |
| text_ast_graph-text | dev | all | 3 | 20 | 5 | 13 | 2 | +0.088 | 0.453 |
| text_ast_graph-text | dev | lexical | 3 | 8 | 0 | 7 | 1 | -0.062 | 1.000 |
| text_ast_graph-text | dev | relationship | 3 | 12 | 5 | 6 | 1 | +0.188 | 0.219 |
| text_ast_graph-text | test | all | 3 | 14 | 4 | 6 | 4 | +0.064 | 1.000 |
| text_ast_graph-text | test | lexical | 3 | 6 | 0 | 4 | 2 | -0.113 | 0.500 |
| text_ast_graph-text | test | relationship | 3 | 8 | 4 | 2 | 2 | +0.196 | 0.688 |
| text_ast_graph-structural | dev | all | 3 | 20 | 5 | 15 | 0 | +0.138 | 0.062 |
| text_ast_graph-structural | dev | lexical | 3 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph-structural | dev | relationship | 3 | 12 | 5 | 7 | 0 | +0.230 | 0.062 |
| text_ast_graph-structural | test | all | 3 | 14 | 4 | 10 | 0 | +0.137 | 0.125 |
| text_ast_graph-structural | test | lexical | 3 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph-structural | test | relationship | 3 | 8 | 4 | 4 | 0 | +0.240 | 0.125 |
| text_ast_graph-graph | dev | all | 3 | 20 | 3 | 14 | 3 | +0.016 | 1.000 |
| text_ast_graph-graph | dev | lexical | 3 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph-graph | dev | relationship | 3 | 12 | 3 | 6 | 3 | +0.027 | 1.000 |
| text_ast_graph-graph | test | all | 3 | 14 | 2 | 12 | 0 | +0.044 | 0.500 |
| text_ast_graph-graph | test | lexical | 3 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph-graph | test | relationship | 3 | 8 | 2 | 6 | 0 | +0.077 | 0.500 |
| text_ast | dev | all | 5 | 20 | 3 | 15 | 2 | +0.044 | 1.000 |
| text_ast | dev | lexical | 5 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast | dev | relationship | 5 | 12 | 3 | 7 | 2 | +0.073 | 1.000 |
| text_ast | test | all | 5 | 14 | 2 | 12 | 0 | +0.044 | 0.500 |
| text_ast | test | lexical | 5 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast | test | relationship | 5 | 8 | 2 | 6 | 0 | +0.077 | 0.500 |
| text_graph | dev | all | 5 | 20 | 5 | 15 | 0 | +0.138 | 0.062 |
| text_graph | dev | lexical | 5 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_graph | dev | relationship | 5 | 12 | 5 | 7 | 0 | +0.230 | 0.062 |
| text_graph | test | all | 5 | 14 | 4 | 10 | 0 | +0.111 | 0.125 |
| text_graph | test | lexical | 5 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_graph | test | relationship | 5 | 8 | 4 | 4 | 0 | +0.195 | 0.125 |
| text_ast_graph | dev | all | 5 | 20 | 5 | 15 | 0 | +0.138 | 0.062 |
| text_ast_graph | dev | lexical | 5 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph | dev | relationship | 5 | 12 | 5 | 7 | 0 | +0.230 | 0.062 |
| text_ast_graph | test | all | 5 | 14 | 4 | 10 | 0 | +0.148 | 0.125 |
| text_ast_graph | test | lexical | 5 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph | test | relationship | 5 | 8 | 4 | 4 | 0 | +0.259 | 0.125 |
| text_ast_graph-text | dev | all | 5 | 20 | 5 | 13 | 2 | +0.088 | 0.453 |
| text_ast_graph-text | dev | lexical | 5 | 8 | 0 | 7 | 1 | -0.062 | 1.000 |
| text_ast_graph-text | dev | relationship | 5 | 12 | 5 | 6 | 1 | +0.188 | 0.219 |
| text_ast_graph-text | test | all | 5 | 14 | 4 | 6 | 4 | +0.047 | 1.000 |
| text_ast_graph-text | test | lexical | 5 | 6 | 0 | 4 | 2 | -0.113 | 0.500 |
| text_ast_graph-text | test | relationship | 5 | 8 | 4 | 2 | 2 | +0.166 | 0.688 |
| text_ast_graph-structural | dev | all | 5 | 20 | 5 | 15 | 0 | +0.138 | 0.062 |
| text_ast_graph-structural | dev | lexical | 5 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph-structural | dev | relationship | 5 | 12 | 5 | 7 | 0 | +0.230 | 0.062 |
| text_ast_graph-structural | test | all | 5 | 14 | 4 | 10 | 0 | +0.120 | 0.125 |
| text_ast_graph-structural | test | lexical | 5 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph-structural | test | relationship | 5 | 8 | 4 | 4 | 0 | +0.210 | 0.125 |
| text_ast_graph-graph | dev | all | 5 | 20 | 3 | 14 | 3 | +0.016 | 1.000 |
| text_ast_graph-graph | dev | lexical | 5 | 8 | 0 | 8 | 0 | +0.000 | 1.000 |
| text_ast_graph-graph | dev | relationship | 5 | 12 | 3 | 6 | 3 | +0.027 | 1.000 |
| text_ast_graph-graph | test | all | 5 | 14 | 2 | 12 | 0 | +0.046 | 0.500 |
| text_ast_graph-graph | test | lexical | 5 | 6 | 0 | 6 | 0 | +0.000 | 1.000 |
| text_ast_graph-graph | test | relationship | 5 | 8 | 2 | 6 | 0 | +0.080 | 0.500 |
