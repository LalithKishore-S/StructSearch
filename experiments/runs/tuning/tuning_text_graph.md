# Weight tuning: text_graph (dev only)

Grid step 0.25, selection metric nDCG@k at K = 3, 20 dev queries. Ties on nDCG@k and MRR go to the more text-heavy weights. The test split is not read.

| text | graph | P@k | R@k | MRR | nDCG@k |
|---|---|---|---|---|---|
| 0.50 | 0.50 | 0.383 | 0.950 | 0.950 | 0.950 |
| 0.25 | 0.75 | 0.383 | 0.950 | 0.950 | 0.950 |
| 0.75 | 0.25 | 0.367 | 0.925 | 0.950 | 0.923 |
| 0.00 | 1.00 | 0.383 | 0.950 | 0.883 | 0.900 |
| 1.00 | 0.00 | 0.300 | 0.825 | 0.850 | 0.812 |
