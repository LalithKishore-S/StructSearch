# Weight tuning: text_graph (dev only)

Grid step 0.25, selection metric nDCG@k at K = 3, 20 dev queries. Ties on nDCG@k and MRR go to the more text-heavy weights. The test split is not read. Constraint: every signal keeps a weight of at least 0.25.

| text | graph | P@k | R@k | MRR | nDCG@k |
|---|---|---|---|---|---|
| 0.50 | 0.50 | 0.383 | 0.950 | 0.950 | 0.950 |
| 0.25 | 0.75 | 0.383 | 0.950 | 0.950 | 0.950 |
| 0.75 | 0.25 | 0.367 | 0.925 | 0.950 | 0.923 |
