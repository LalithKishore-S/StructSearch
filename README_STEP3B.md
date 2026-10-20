# Step 3b: dense semantic baseline

Unzip into the repo root (same-name files are replaced, including `schemas.py`, `config.py`,
`configs/default.yaml`, `interface/cli.py`, `retrieval/*` and `tests/test_search_cli.py`).

## Tests (no Ollama needed)
```bash
source .venv/bin/activate
pytest -q                                   # expect: 124 passed
python -m structsearch search "validate input" --mode dense --embedder hashing -k 3
```
`--embedder hashing` is a lexical stand-in used only for tests and offline demos. It is NOT semantic.

## Ollama setup (needed for real semantic search)
```bash
# 1. Install Ollama: https://ollama.com/download  (macOS: the app, or `brew install ollama`)
# 2. Make sure the server is running (the macOS app starts it; otherwise run in a separate terminal):
ollama serve
# 3. Download the embedding model (about 270 MB):
ollama pull nomic-embed-text
# 4. Check that it works; this should print a JSON object containing an "embeddings" list:
curl http://localhost:11434/api/embed -d '{"model":"nomic-embed-text","input":"hello"}'
```
Then, from the repo root:
```bash
python -m structsearch search "check credentials before running sql" --mode dense -k 5
python -m structsearch search "check credentials before running sql" --mode bm25  -k 5   # compare
python -m structsearch index path/to/your/repo --dense                                   # pre-build the vectors
python -m structsearch search "..." --mode dense --model mxbai-embed-large               # try another model
```
(For a model other than nomic-embed-text, also set `doc_prefix` and `query_prefix` to `""` in
`configs/default.yaml`, because those prefixes are specific to nomic-embed-text.)

If it fails the CLI prints the reason and exits with code 3:
- `Cannot reach Ollama` -> the server is not running (`ollama serve`) or `dense.host` in the config is wrong.
- `does not have the model` -> run `ollama pull <model>`.
- A very slow first call is normal: Ollama loads the model into memory.

## How it works
- Every unit is turned into text (`<prefix>Class.method (path)` + source, cut to `max_chars`) and embedded
  in batches (`batch_size`) through Ollama's `/api/embed` (older servers fall back to `/api/embeddings`).
- Vectors are L2-normalized and stored as `dense_vectors.npy` plus `dense_meta.json` in the index folder.
  Search is exact cosine similarity (one matrix product), no vector database and no approximation, so the
  BM25 vs dense comparison is reproducible. The numpy matrix sits behind `DenseIndex`, so FAISS or Chroma
  could replace it later.
- Vectors are cached by a hash of (model, text). When code changes, only new or edited units are re-embedded;
  changing the model, prefix or `max_chars` re-embeds everything. A refresh happens automatically on the
  next `--mode dense` search, or with `--rebuild`.
- Dense search always returns k results (the least dissimilar ones), unlike BM25, which only returns units
  that share a term with the query. Read the score, not just the rank.
- Results are `RankedResult` records with `dense_score` set (cosine), `text_score=0`, `final_score=dense_score`.

## For Member 2
- `RankedResult` has a new optional field `dense_score` (added at the end, default `None`).
- The evaluation needs a variant name `dense`; `search --mode dense --json --query-id Q` produces the records.
- New `dense:` section in `configs/default.yaml`.

## Not verified here
The Ollama client is tested against a fake local server (batch call, legacy endpoint, missing model, server
error, unreachable host), not against a real Ollama, which is not available in my environment. Please run the
three commands under "Ollama setup" and send me the output if anything differs.
