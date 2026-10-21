# Results (k=5)

| variant | split | category | n | P@k | R@k | MRR | nDCG@k | hit@k |
|---|---|---|---|---|---|---|---|---|
| bm25 | dev | all | 20 | 0.180 | 0.825 | 0.850 | 0.812 | 0.900 |
| bm25 | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| bm25 | dev | relationship | 12 | 0.167 | 0.708 | 0.750 | 0.687 | 0.833 |
| bm25 | test | all | 14 | 0.214 | 0.857 | 0.821 | 0.804 | 0.929 |
| bm25 | test | lexical | 6 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| bm25 | test | relationship | 8 | 0.200 | 0.750 | 0.750 | 0.703 | 0.875 |
| text_ast | dev | all | 20 | 0.220 | 0.925 | 0.850 | 0.856 | 0.950 |
| text_ast | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast | dev | relationship | 12 | 0.233 | 0.875 | 0.750 | 0.760 | 0.917 |
| text_ast | test | all | 14 | 0.229 | 0.893 | 0.857 | 0.848 | 0.929 |
| text_ast | test | lexical | 6 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast | test | relationship | 8 | 0.225 | 0.812 | 0.812 | 0.780 | 0.875 |
| text_graph | dev | all | 20 | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_graph | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_graph | dev | relationship | 12 | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_graph | test | all | 14 | 0.271 | 1.000 | 0.881 | 0.915 | 1.000 |
| text_graph | test | lexical | 6 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_graph | test | relationship | 8 | 0.300 | 1.000 | 0.854 | 0.898 | 1.000 |
| text_ast_graph | dev | all | 20 | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph | dev | relationship | 12 | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph | test | all | 14 | 0.271 | 1.000 | 0.929 | 0.952 | 1.000 |
| text_ast_graph | test | lexical | 6 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph | test | relationship | 8 | 0.300 | 1.000 | 0.938 | 0.962 | 1.000 |
| text_ast_graph-text | dev | all | 20 | 0.230 | 0.950 | 0.883 | 0.900 | 0.950 |
| text_ast_graph-text | dev | lexical | 8 | 0.200 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-text | dev | relationship | 12 | 0.250 | 0.917 | 0.861 | 0.875 | 0.917 |
| text_ast_graph-text | test | all | 14 | 0.271 | 1.000 | 0.786 | 0.851 | 1.000 |
| text_ast_graph-text | test | lexical | 6 | 0.233 | 1.000 | 0.750 | 0.826 | 1.000 |
| text_ast_graph-text | test | relationship | 8 | 0.300 | 1.000 | 0.812 | 0.869 | 1.000 |
| text_ast_graph-structural | dev | all | 20 | 0.230 | 0.950 | 0.950 | 0.950 | 0.950 |
| text_ast_graph-structural | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-structural | dev | relationship | 12 | 0.250 | 0.917 | 0.917 | 0.917 | 0.917 |
| text_ast_graph-structural | test | all | 14 | 0.271 | 1.000 | 0.893 | 0.924 | 1.000 |
| text_ast_graph-structural | test | lexical | 6 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-structural | test | relationship | 8 | 0.300 | 1.000 | 0.875 | 0.913 | 1.000 |
| text_ast_graph-graph | dev | all | 20 | 0.210 | 0.875 | 0.825 | 0.828 | 0.900 |
| text_ast_graph-graph | dev | lexical | 8 | 0.200 | 1.000 | 1.000 | 1.000 | 1.000 |
| text_ast_graph-graph | dev | relationship | 12 | 0.217 | 0.792 | 0.708 | 0.714 | 0.833 |
| text_ast_graph-graph | test | all | 14 | 0.229 | 0.893 | 0.857 | 0.850 | 0.929 |
| text_ast_graph-graph | test | lexical | 6 | 0.233 | 1.000 | 0.917 | 0.938 | 1.000 |
| text_ast_graph-graph | test | relationship | 8 | 0.225 | 0.812 | 0.812 | 0.783 | 0.875 |

## Failures (44)

- L08 [text_ast_graph-text] top-1 not relevant: "append a message to a log file" top1=files.py::read_config_safe missing=[]
- L09 [text_ast_graph-text] top-1 not relevant: "read all lines of a file" top1=files.py::read_config_safe missing=[]
- L11 [text_ast_graph-text] top-1 not relevant: "look up a user by name in the database" top1=db.py::count_rows missing=[]
- L12 [bm25] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
- L12 [text_ast] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
- L12 [text_graph] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
- L12 [text_ast_graph] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
- L12 [text_ast_graph-text] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
- L12 [text_ast_graph-structural] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
- L12 [text_ast_graph-graph] top-1 not relevant: "create a tree node with left and right children" top1=trees.py::inorder_traverse missing=[]
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
- R14 [bm25] top-1 not relevant: "SQL text assembled by joining strings with caller supplied values" top1=utils.py::slugify missing=['db.py::count_rows']
- R14 [text_ast] top-1 not relevant: "SQL text assembled by joining strings with caller supplied values" top1=utils.py::slugify missing=['db.py::count_rows']
- R14 [text_ast_graph-graph] top-1 not relevant: "SQL text assembled by joining strings with caller supplied values" top1=utils.py::slugify missing=['db.py::count_rows']
- R16 [bm25] top-1 not relevant: "opens a file without error handling" top1=files.py::read_config_safe missing=[]
- R16 [text_graph] top-1 not relevant: "opens a file without error handling" top1=files.py::read_config_safe missing=[]
- R16 [text_ast_graph-structural] top-1 not relevant: "opens a file without error handling" top1=files.py::read_config_safe missing=[]
- R17 [bm25] no relevant result in top-k: "opening files without catching exceptions" top1=db.py::find_user_unsafe missing=['files.py::read_lines', 'files.py::write_log']
- R17 [text_ast] no relevant result in top-k: "opening files without catching exceptions" top1=db.py::find_user_unsafe missing=['files.py::read_lines', 'files.py::write_log']
- R17 [text_graph] top-1 not relevant: "opening files without catching exceptions" top1=files.py::read_config_safe missing=[]
- R17 [text_ast_graph] top-1 not relevant: "opening files without catching exceptions" top1=files.py::read_config_safe missing=[]
- R17 [text_ast_graph-text] top-1 not relevant: "opening files without catching exceptions" top1=files.py::read_config_safe missing=[]
- R17 [text_ast_graph-structural] top-1 not relevant: "opening files without catching exceptions" top1=files.py::read_config_safe missing=[]
- R17 [text_ast_graph-graph] no relevant result in top-k: "opening files without catching exceptions" top1=db.py::find_user_unsafe missing=['files.py::read_lines', 'files.py::write_log']
- R19 [text_ast_graph-text] top-1 not relevant: "recursive tree traversal" top1=trees.py::factorial missing=[]
- R20 [text_ast_graph-text] top-1 not relevant: "in-order walk of a tree that calls itself" top1=trees.py::factorial missing=[]
