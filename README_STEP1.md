# Step 1: ingestion

Unzip into the repo root (paths are already relative to it; `ingestion/__init__.py` is replaced).

## Run
```bash
source .venv/bin/activate
pytest -q                                   # expect: 33 passed
python -m structsearch.ingestion --list     # uses corpus_path from configs/default.yaml
python -m structsearch.ingestion path/to/other/corpus --out .structsearch_index/units.jsonl
```
Expected on the fixture corpus: 5 files scanned, 15 units, 1 failed file (`broken_syntax.py`). Units are written to `.structsearch_index/units.jsonl` (git-ignored).

## Rules implemented
- Units: top-level functions and methods (nested classes, async, and defs under if/try included). Functions nested inside functions stay part of their parent.
- `unit_id` = `relative/path.py::Qualified.name`; duplicates (property setters, conditional redefinitions) get `#2`, `#3`.
- `start_line` includes decorators; line numbers are 1-based and match the original file; `source_text` is the exact file slice.
- Files with syntax or encoding errors are logged and listed in `failed_files`, never fatal. Hidden and vendor folders (`.git`, `.venv`, `__pycache__`, `node_modules`, `site-packages`, ...) are skipped.
- `parse_unit(unit)` returns the function's AST node (works for indented methods); Step 4 will use it.

## Python API
```python
from structsearch.ingestion import ingest_corpus, save_units, load_units, parse_unit
result = ingest_corpus("tests/fixtures/sample_corpus")   # result.units, result.failed_files
```
