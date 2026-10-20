# Step 0: scaffold and shared contracts

Copy these folders and files into the repo root (merge with the existing README.md, do not overwrite it).

## Setup and run
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```
Expected: all tests pass.

## Contents
- `structsearch/schemas.py`: CodeUnit, TextRecord, AstRecord, RankedResult, EvaluationLabel (share with Member 2).
- `structsearch/config.py` and `configs/default.yaml`: weights, top_k, optional Ollama settings.
- `tests/fixtures/sample_corpus/`: 14 functions (recursion, try/except around file access, validation before DB call, utilities) and one file with a syntax error.
- `tests/fixtures/expected_units.json`: expected unit ids, used by Step 1 tests.
- Empty packages for all modules, including `graph/`, `security/`, `evaluation/` (Member 2).
