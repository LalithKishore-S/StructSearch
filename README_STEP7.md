# Step 7: interface + grounded explanations

## What is new
- `structsearch/interface/service.py`: one search entry point (`run_search`) used by the CLI and the UI.
- `structsearch/interface/explain.py`: a `why:` line per result.
  - `template` (default): built only from the result's evidence lines. No Ollama.
  - `llm`: a local Ollama model writes two sentences and must cite evidence line numbers. The answer is rejected
    (template used instead, reason shown) if it cites a line that does not exist, mentions an identifier,
    backticked text or number not present in the evidence/code/query, or uses words like "vulnerable", "confirmed", "bug".
    If Ollama is down, it is tried once, then all remaining results use the template.
- CLI flags: `--explain [template|llm]`, `--explain-top N` (results sent to the model, default 3). `--json` adds `explanation` per result.
- `structsearch/interface/streamlit_app.py` (optional UI) and `requirements-ui.txt`.

## Run
    pip install -r requirements.txt
    python -m pytest -q
    python -m structsearch search "recursive factorial" --mode text_ast --explain
    python -m structsearch search "recursive factorial" --mode bm25 --json --explain
    python -m structsearch search "query" --mode hybrid --explain llm --explain-top 3   # needs Ollama

Modes: bm25, dense, structural, like, text_ast, hybrid (dense/hybrid need the embedding model).

## Optional: Ollama
    ollama pull nomic-embed-text      # dense / hybrid
    ollama pull qwen2.5-coder:7b      # --explain llm and --use-llm (falls back to :3b if missing)
    ollama serve

## Optional: Streamlit
    pip install -r requirements-ui.txt
    streamlit run structsearch/interface/streamlit_app.py

## Limits
- Explanations restate retrieval evidence; they never claim a bug or vulnerability.
- The validator checks names/numbers/cited lines, not every word of prose.
- The LLM explanation path was tested against a fake HTTP server and a stub, not a real Ollama.
