# Results (k=5)

| variant | split | category | n | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|---|---|---|
| bm25 | dev | all | 20 | 0.180 | 0.825 | 0.850 | 0.812 | 0.900 |
| bm25 | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| bm25 | dev | relationship | 12 | 0.167 | 0.708 | 0.750 | 0.687 | 0.833 |
| text_ast | dev | all | 20 | 0.220 | 0.925 | 0.850 | 0.856 | 0.950 |
| text_ast | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast | dev | relationship | 12 | 0.233 | 0.875 | 0.750 | 0.760 | 0.917 |
| text_graph | dev | all | 20 | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_graph | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_graph | dev | relationship | 12 | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph | dev | all | 20 | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph | dev | relationship | 12 | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-text | dev | all | 20 | 0.230 | 0.950 | 0.883 | 0.900 | 0.950 |
| text_ast_graph-text | dev | lexical | 8 | 0.200 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-text | dev | relationship | 12 | 0.250 | 0.917 | 0.861 | 0.875 | 0.917 |
| text_ast_graph-structural | dev | all | 20 | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-structural | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-structural | dev | relationship | 12 | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-graph | dev | all | 20 | 0.210 | 0.875 | 0.825 | 0.828 | 0.900 |
| text_ast_graph-graph | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-graph | dev | relationship | 12 | 0.217 | 0.792 | 0.708 | 0.714 | 0.833 |

## Failures (20)

- L08 [text_ast_graph-text] top-1 not relevant: "append a message to a log file" top1=files.py::read_config_safe missing=[]
- R01 [text_ast] top-1 not relevant: "validate user input before database access" top1=db.py::validate_user_input missing=[]
- R01 [text_ast_graph-graph] top-1 not relevant: "validate user input before database access" top1=db.py::validate_user_input missing=[]
- R02 [bm25] top-1 not relevant: "sanitize the username and then run a SQL query" top1=db.py::find_user_unsafe missing=[]
- R02 [text_ast] top-1 not relevant: "sanitize the username and then run a SQL query" top1=db.py::find_user_unsafe missing=[]
- R02 [text_ast_graph-graph] no relevant result in top-k: "sanitize the username and then run a SQL query" top1=db.py::find_user_unsafe missing=['db.py::get_user']
- R03 [text_ast] top-1 not relevant: "check the input first, then query the database" top1=db.py::validate_user_input missing=[]
- R03 [text_ast_graph-graph] top-1 not relevant: "check the input first, then query the database" top1=db.py::validate_user_input missing=[]
- R04 [text_ast_graph-text] top-1 not relevant: "make sure the argument is acceptable before it reaches the database layer" top1=db.py::count_rows missing=[]
- R06 [bm25] top-1 not relevant: "queries that run without checking their input" top1=db.py::validate_user_input missing=['db.py::count_rows']
- R06 [text_ast] top-1 not relevant: "queries that run without checking their input" top1=db.py::validate_user_input missing=['db.py::count_rows']
- R06 [text_ast_graph-graph] top-1 not relevant: "queries that run without checking their input" top1=db.py::validate_user_input missing=['db.py::count_rows']
- R08 [bm25] no relevant result in top-k: "function that calls itself" top1=None missing=['trees.py::factorial', 'trees.py::inorder_traverse']
- R12 [bm25] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
- R12 [text_ast] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
- R12 [text_graph] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
- R12 [text_ast_graph] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
- R12 [text_ast_graph-text] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
- R12 [text_ast_graph-structural] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
- R12 [text_ast_graph-graph] no relevant result in top-k: "function that calls another function defined in the same file" top1=files.py::read_config_safe missing=['db.py::get_user']
