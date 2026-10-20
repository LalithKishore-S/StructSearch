# Step 9 (extension): error-tolerant parsing

Off by default. Without `--tolerant` nothing changes: a file Python cannot parse is still one searchable file-level unit.

## Setup
    pip install -r requirements-tolerant.txt      # tree-sitter, tree-sitter-python (Python 3.9+ wheels; newer versions may need 3.10+)

## Use
    python -m structsearch.ingestion <corpus> --tolerant --list     # per-function units + syntax-error lines
    python -m structsearch search "loop with if" --mode text_ast --tolerant
    python -m structsearch features --tolerant      (also: fragments, index)
Changing `--tolerant` makes the index rebuild by itself. Missing tree-sitter -> exit code 2 with the install command.

## What happens to a file that does not parse
1. tree-sitter parses it anyway and marks ERROR/MISSING regions (their lines are reported).
2. `def` lines (class context from indentation; defs inside strings ignored) give the function units. A clean tree-sitter
   function node gives the exact end line, otherwise the end is the last line indented deeper than the `def`.
3. Each function is checked with Python's own parser:
   - parses: `ok`, identical to a normal file (same features and fragments)
   - parses after skipping the lines with syntax errors (replaced by `pass`, never invented): `partial`; `error_lines` kept
   - cannot be repaired (e.g. broken `def` line): `failed`, function-level unit, text search only
4. Partial units get AST features and fragments from the surviving code, so they can match structural queries, and are
   flagged: `[partial parse: syntax errors at line 14]` in listings, an evidence line `partial parse: ...`, and a `why:` note.

New: `CodeUnit.error_lines` (default empty, old index files still load), `PARSE_PARTIAL`, `FailedFile.recovered_units/error_lines`
(in `failed_files.json`), `ingestion/repair.py`, `parsing/tolerant.py`. Tests: `tests/test_tolerant.py` (skipped if tree-sitter is absent).

## Limits
- Function ends in broken code are indentation-based; code dedented inside brackets can end a function early.
- A syntax error inside the `def` line makes that function `failed`. Module-level code outside functions is not indexed (same as normal files).
- Skipping an erroneous line can drop real structure that was on it (a partial unit's counts are lower bounds).
- Not for other languages; tree-sitter is only used to locate error regions and exact function ends.
