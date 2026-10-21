# Weight tuning: text_ast_graph (dev only)

Grid step 0.25, selection metric nDCG@k at K = 3, 20 dev queries. Ties on nDCG@k and MRR go to the more text-heavy weights. The test split is not read. Constraint: every signal keeps a weight of at least 0.25.

| text | structural | graph | P@k | R@k | MRR | nDCG@k |
|---|---|---|---|---|---|---|
| 0.25 | 0.25 | 0.50 | 0.383 | 0.950 | 0.950 | 0.950 |
| 0.50 | 0.25 | 0.25 | 0.383 | 0.950 | 0.950 | 0.942 |
| 0.25 | 0.50 | 0.25 | 0.367 | 0.900 | 0.850 | 0.863 |
