# Label review sheet

Generated from `queries.json` and `labels.jsonl` (the files to edit are those two, not this sheet).
Judge from the code in section 2 and the rules in `PROTOCOL.md`; do not run a search first.

## 1. How to review
1. Read the code of the 15 units (section 2). The 16th unit, `broken_syntax.py::<module>`, does not parse and is never relevant.
2. For each query in section 3, decide independently which units are relevant, then compare with *Proposed relevant*. Fill in your verdict column (`ok` or the units you would change).
3. Review at least the queries marked **sample** (one per paraphrase group plus the tricky single queries); more is better.
4. Settle disagreements together. To change a label, edit `labels.jsonl`: set `relevance` to 1 or 0 on the row of that `query_id` and `unit_id`. Queries of one paraphrase `group` must keep identical relevant units.
5. Run `python -m structsearch benchmark check` (must show `problems: 0` apart from the freeze message), then `python -m structsearch benchmark freeze` to lock the result. Do this before any weight tuning.

## 2. The corpus

### `db.py::count_rows`  (lines 22-24)

```python
def count_rows(db, table_name):
    """Count rows in a table."""
    return db.execute("SELECT COUNT(*) FROM " + table_name).fetchone()[0]
```

### `db.py::find_user_unsafe`  (lines 16-19)

```python
def find_user_unsafe(db, username):
    """Build the SQL string directly from user input without validation."""
    query = "SELECT * FROM users WHERE name = '" + username + "'"
    return db.execute(query).fetchall()
```

### `db.py::get_user`  (lines 10-13)

```python
def get_user(db, username):
    """Validate the username, then query the database with a parameter."""
    clean = validate_user_input(username)
    return db.execute("SELECT * FROM users WHERE name = ?", (clean,)).fetchone()
```

### `db.py::validate_user_input`  (lines 1-7)

```python
def validate_user_input(value):
    """Reject empty or suspicious user input."""
    if not value or not isinstance(value, str):
        raise ValueError("invalid input")
    if ";" in value or "--" in value:
        raise ValueError("suspicious input")
    return value.strip()
```

### `files.py::read_config_safe`  (lines 4-12)

```python
def read_config_safe(path):
    """Read a JSON config file, handling missing files and bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return None
```

### `files.py::read_lines`  (lines 21-24)

```python
def read_lines(path):
    """Read all lines of a file with no error handling."""
    with open(path) as handle:
        return handle.readlines()
```

### `files.py::write_log`  (lines 15-18)

```python
def write_log(path, message):
    """Append a message to a log file."""
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(message + "\n")
```

### `trees.py::Node.__init__`  (lines 2-5)

```python
    def __init__(self, value, left=None, right=None):
        self.value = value
        self.left = left
        self.right = right
```

### `trees.py::count_nodes`  (lines 24-37)

```python
def count_nodes(root):
    """Count nodes using an explicit stack (iterative, not recursive)."""
    if root is None:
        return 0
    stack = [root]
    total = 0
    while stack:
        current = stack.pop()
        total += 1
        if current.left:
            stack.append(current.left)
        if current.right:
            stack.append(current.right)
    return total
```

### `trees.py::factorial`  (lines 17-21)

```python
def factorial(n):
    """Compute factorial recursively."""
    if n <= 1:
        return 1
    return n * factorial(n - 1)
```

### `trees.py::inorder_traverse`  (lines 8-14)

```python
def inorder_traverse(node, visit):
    """Recursive in-order tree traversal."""
    if node is None:
        return
    inorder_traverse(node.left, visit)
    visit(node.value)
    inorder_traverse(node.right, visit)
```

### `utils.py::Counter.increment`  (lines 21-24)

```python
    def increment(self, amount=1):
        """Increase the internal count."""
        self.count = getattr(self, "count", 0) + amount
        return self.count
```

### `utils.py::add`  (lines 4-6)

```python
def add(a, b):
    """Add two numbers."""
    return a + b
```

### `utils.py::camel_to_snake`  (lines 15-17)

```python
def camel_to_snake(name):
    """Convert camelCase to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
```

### `utils.py::slugify`  (lines 9-12)

```python
def slugify(text):
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")
```

## 3. Queries

| id | split | category | group | sample | query | proposed relevant | why (notes) | reviewer A | reviewer B |
|---|---|---|---|---|---|---|---|---|---|
| L01 | dev | lexical |  |  | add two numbers | `utils.py::add` | add returns a + b |  |  |
| L02 | dev | lexical |  |  | convert text to a url friendly slug | `utils.py::slugify` | slugify builds a slug |  |  |
| L03 | dev | lexical |  | **sample** | convert camel case name to snake case | `utils.py::camel_to_snake` | camel_to_snake |  |  |
| L04 | dev | lexical |  |  | increase the internal counter | `utils.py::Counter.increment` | Counter.increment |  |  |
| L05 | dev | lexical |  |  | count rows in a database table | `db.py::count_rows` | count_rows runs SELECT COUNT(*) |  |  |
| L06 | dev | lexical |  |  | count the nodes in a tree | `trees.py::count_nodes` | count_nodes walks a tree and counts |  |  |
| L07 | dev | lexical |  |  | compute the factorial of a number | `trees.py::factorial` | factorial |  |  |
| L08 | dev | lexical |  |  | append a message to a log file | `files.py::write_log` | write_log opens in append mode |  |  |
| L09 | test | lexical |  |  | read all lines of a file | `files.py::read_lines` | read_lines |  |  |
| L10 | test | lexical |  |  | load a json configuration file | `files.py::read_config_safe` | read_config_safe loads JSON |  |  |
| L11 | test | lexical |  | **sample** | look up a user by name in the database | `db.py::find_user_unsafe`, `db.py::get_user` | get_user and find_user_unsafe both select users by name; count_rows does not |  |  |
| L12 | test | lexical |  |  | create a tree node with left and right children | `trees.py::Node.__init__` | Node.__init__ stores value, left, right |  |  |
| L13 | test | lexical |  |  | visit tree values in order | `trees.py::inorder_traverse` | in-order traversal calling visit on each value |  |  |
| L14 | test | lexical |  | **sample** | reject empty or suspicious input | `db.py::validate_user_input` | validate_user_input raises on empty or suspicious values |  |  |
| R01 | dev | relationship | validate_then_query | **sample** | validate user input before database access | `db.py::get_user` | get_user calls the validator (line 12) before execute (line 13); the validator alone has no database access; the unsafe functions do not validate |  |  |
| R02 | dev | relationship | validate_then_query |  | sanitize the username and then run a SQL query | `db.py::get_user` | paraphrase of R01 |  |  |
| R03 | dev | relationship | validate_then_query |  | check the input first, then query the database | `db.py::get_user` | paraphrase of R01 |  |  |
| R04 | dev | relationship | validate_then_query |  | make sure the argument is acceptable before it reaches the database layer | `db.py::get_user` | paraphrase of R01 with none of the usual validation words |  |  |
| R05 | dev | relationship | unvalidated_db | **sample** | database access without validation | `db.py::count_rows`, `db.py::find_user_unsafe` | both execute SQL built from their arguments with no validation step; get_user validates |  |  |
| R06 | dev | relationship | unvalidated_db |  | queries that run without checking their input | `db.py::count_rows`, `db.py::find_user_unsafe` | paraphrase of R05 |  |  |
| R07 | dev | relationship | recursion | **sample** | recursive function | `trees.py::factorial`, `trees.py::inorder_traverse` | factorial and inorder_traverse call themselves |  |  |
| R08 | dev | relationship | recursion |  | function that calls itself | `trees.py::factorial`, `trees.py::inorder_traverse` | paraphrase of R07 |  |  |
| R09 | dev | relationship | file_with_try | **sample** | exception handling around file access | `files.py::read_config_safe` | only read_config_safe wraps open in try/except |  |  |
| R10 | dev | relationship | file_with_try |  | function that catches errors when opening a file | `files.py::read_config_safe` | paraphrase of R09 |  |  |
| R11 | dev | relationship |  | **sample** | function with a while loop | `trees.py::count_nodes` | count_nodes is the only function with a while loop |  |  |
| R12 | dev | relationship |  | **sample** | function that calls another function defined in the same file | `db.py::get_user` | get_user calls validate_user_input; recursive functions call only themselves |  |  |
| R13 | test | relationship | sql_concat | **sample** | sql query built by string concatenation | `db.py::count_rows`, `db.py::find_user_unsafe` | both build SQL text with + |  |  |
| R14 | test | relationship | sql_concat |  | SQL text assembled by joining strings with caller supplied values | `db.py::count_rows`, `db.py::find_user_unsafe` | paraphrase of R13 |  |  |
| R15 | test | relationship |  |  | iterative tree traversal using an explicit stack | `trees.py::count_nodes` | count_nodes uses a stack and a while loop |  |  |
| R16 | test | relationship | file_no_try | **sample** | opens a file without error handling | `files.py::read_lines`, `files.py::write_log` | read_lines and write_log call open with no try/except |  |  |
| R17 | test | relationship | file_no_try |  | opening files without catching exceptions | `files.py::read_lines`, `files.py::write_log` | paraphrase of R16 |  |  |
| R18 | test | relationship |  | **sample** | raises an exception on invalid input | `db.py::validate_user_input` | the only function that raises |  |  |
| R19 | test | relationship | recursive_traversal | **sample** | recursive tree traversal | `trees.py::inorder_traverse` | recursive and walks a tree; factorial is recursive but not a traversal |  |  |
| R20 | test | relationship | recursive_traversal |  | in-order walk of a tree that calls itself | `trees.py::inorder_traverse` | paraphrase of R19 |  |  |
