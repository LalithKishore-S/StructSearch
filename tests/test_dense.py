import json
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from structsearch.indexing import (
    DenseIndex,
    DenseSettings,
    Embedder,
    EmbeddingError,
    HashingEmbedder,
    OllamaEmbedder,
    build_dense_index,
    embed_query,
    embedding_text,
    ensure_dense_index,
    make_embedder,
)
from structsearch.indexing.bm25 import BM25Index
from structsearch.indexing.records import build_text_records
from structsearch.ingestion import ingest_corpus
from structsearch.retrieval import dense_search
from structsearch.schemas import CodeUnit, RankedResult

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"
SETTINGS = DenseSettings(backend="hashing", doc_prefix="", query_prefix="")


@pytest.fixture(scope="module")
def result():
    return ingest_corpus(CORPUS)


class CountingEmbedder(HashingEmbedder):
    """Hashing embedder that records every text it is asked to embed."""

    def __init__(self):
        super().__init__()
        self.seen = []

    def embed(self, texts):
        self.seen.extend(texts)
        return super().embed(texts)


class SynonymEmbedder(HashingEmbedder):
    """Test stand-in for a semantic model: maps synonyms to one concept before hashing."""

    SYNONYMS = {"verify": "validate", "check": "validate", "sanitize": "validate"}

    def _tokens(self, text):
        return [self.SYNONYMS.get(t, t) for t in super()._tokens(text)]


# ---- embedders ----

def test_hashing_embedder_is_deterministic_and_handles_empty_text():
    emb = HashingEmbedder()
    a = emb.embed(["validate user input", ""])
    b = emb.embed(["validate user input", ""])
    assert a.shape == (2, 256) and a.dtype == np.float32
    assert np.array_equal(a, b)
    assert not a[1].any()  # empty text -> zero vector, no NaN
    assert emb.model == "hashing-256"


def test_make_embedder_and_settings_from_config():
    assert isinstance(make_embedder(DenseSettings(backend="hashing")), HashingEmbedder)
    ollama = make_embedder(DenseSettings(model="m", host="http://h:1/"))
    assert isinstance(ollama, OllamaEmbedder) and ollama.host == "http://h:1"
    with pytest.raises(ValueError):
        make_embedder(DenseSettings(backend="nope"))
    cfg = {"dense": {"model": "x", "batch_size": 4, "unknown_key": 1}}
    s = DenseSettings.from_config(cfg, backend="hashing", model=None)
    assert (s.model, s.batch_size, s.backend) == ("x", 4, "hashing")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload, raw=False):
        body = payload.encode() if raw else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        mode = self.server.mode
        self.server.requests.append((self.path, body))
        if mode == "missing_model":
            return self._send(404, {"error": 'model "x" not found, try pulling it first'})
        if mode == "server_error":
            return self._send(500, {"error": "boom"})
        if mode == "legacy":
            if self.path == "/api/embed":
                return self._send(404, "404 page not found", raw=True)
            return self._send(200, {"embedding": [float(len(body["prompt"])), 1.0, 0.0]})
        if self.path != "/api/embed":
            return self._send(404, "404 page not found", raw=True)
        inputs = body["input"]
        inputs = [inputs] if isinstance(inputs, str) else inputs
        vectors = [[float(len(t)), 1.0, 0.0] for t in inputs]
        if mode == "bad_count":
            vectors = vectors[:-1]
        self._send(200, {"model": body["model"], "embeddings": vectors})


@pytest.fixture()
def ollama_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.mode, server.requests = "ok", []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _client(server, model="nomic-embed-text"):
    return OllamaEmbedder(model, f"http://127.0.0.1:{server.server_address[1]}", timeout=5)


def test_ollama_embed_batch(ollama_server):
    vectors = _client(ollama_server).embed(["ab", "abcd"])
    assert vectors.shape == (2, 3) and vectors[1][0] == 4.0
    path, body = ollama_server.requests[0]
    assert path == "/api/embed" and body == {"model": "nomic-embed-text", "input": ["ab", "abcd"]}


def test_ollama_legacy_endpoint_fallback(ollama_server):
    ollama_server.mode = "legacy"
    vectors = _client(ollama_server).embed(["ab", "abc"])
    assert vectors.shape == (2, 3) and vectors[1][0] == 3.0
    assert [p for p, _ in ollama_server.requests] == ["/api/embed", "/api/embeddings", "/api/embeddings"]


def test_ollama_missing_model_message(ollama_server):
    ollama_server.mode = "missing_model"
    with pytest.raises(EmbeddingError, match="ollama pull nomic-embed-text"):
        _client(ollama_server).embed(["x"])


def test_ollama_server_error_and_wrong_count(ollama_server):
    ollama_server.mode = "server_error"
    with pytest.raises(EmbeddingError, match="HTTP 500"):
        _client(ollama_server).embed(["x"])
    ollama_server.mode = "bad_count"
    with pytest.raises(EmbeddingError, match="returned 1"):
        _client(ollama_server).embed(["a", "b"])


def test_ollama_unreachable_message():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing is listening on this port now
    client = OllamaEmbedder("nomic-embed-text", f"http://127.0.0.1:{port}", timeout=2)
    with pytest.raises(EmbeddingError, match="ollama serve"):
        client.embed(["x"])


def test_ollama_empty_input_makes_no_request(ollama_server):
    assert _client(ollama_server).embed([]).shape[0] == 0
    assert ollama_server.requests == []


# ---- embedding text ----

def test_embedding_text_format_prefix_and_truncation():
    unit = CodeUnit("a.py::Cls.m", "a.py", 1, 2, "m", "x" * 50)
    text = embedding_text(unit, DenseSettings(doc_prefix="P: ", max_chars=100))
    assert text.startswith("P: Cls.m (a.py)\n") and text.endswith("x" * 50)
    short = embedding_text(unit, DenseSettings(doc_prefix="", max_chars=100))
    long_unit = CodeUnit("a.py::f", "a.py", 1, 2, "f", "y" * 500)
    assert embedding_text(long_unit, DenseSettings(doc_prefix="", max_chars=120)).endswith("y" * 120)
    assert "y" * 121 not in embedding_text(long_unit, DenseSettings(doc_prefix="", max_chars=120))
    assert short.startswith("Cls.m (a.py)")


def test_failed_file_unit_uses_file_name_in_text(result):
    unit = next(u for u in result.units if u.parse_status == "failed")
    assert embedding_text(unit, SETTINGS).startswith("broken_syntax (broken_syntax.py)")


# ---- DenseIndex ----

def test_index_search_orders_by_cosine_and_ties_by_id():
    vectors = np.array([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    idx = DenseIndex(["c", "a", "b"], vectors, ["h1", "h2", "h3"], "m")
    hits = idx.search(np.array([1, 0.2]), 3)
    assert [u for u, _ in hits] == ["c", "b", "a"]
    tie = DenseIndex(["b", "a"], np.array([[1, 0], [1, 0]], dtype=np.float32), ["x", "y"], "m")
    assert [u for u, _ in tie.search(np.array([1, 0]), 2)] == ["a", "b"]
    assert np.allclose(np.linalg.norm(idx.vectors, axis=1), 1.0)


def test_index_rejects_wrong_query_dimension():
    idx = DenseIndex(["a"], np.ones((1, 4), dtype=np.float32), ["h"], "m")
    with pytest.raises(EmbeddingError, match="dimensions"):
        idx.search(np.ones(3))


def test_empty_index_and_save_load(tmp_path):
    empty = DenseIndex([], np.zeros((0, 0)), [], "m")
    assert empty.search(np.ones(3)) == [] and len(empty.score_all(np.ones(3))) == 0
    empty.save(tmp_path / "e")
    assert DenseIndex.load(tmp_path / "e").unit_ids == []


def test_save_load_gives_identical_scores(result, tmp_path):
    index = build_dense_index(result.units, HashingEmbedder(), SETTINGS)
    index.save(tmp_path)
    loaded = DenseIndex.load(tmp_path)
    assert loaded.unit_ids == index.unit_ids and loaded.model == "hashing-256"
    query = embed_query(HashingEmbedder(), SETTINGS, "read a file")
    assert np.array_equal(loaded.score_all(query), index.score_all(query))
    assert loaded.search(query, 5) == index.search(query, 5)


def test_load_returns_none_when_missing_or_wrong_version(tmp_path):
    assert DenseIndex.load(tmp_path / "nothing") is None
    DenseIndex(["a"], np.ones((1, 2), dtype=np.float32), ["h"], "m").save(tmp_path)
    meta = tmp_path / "dense_meta.json"
    meta.write_text(meta.read_text().replace('"version": 1', '"version": 9').replace('"version":1', '"version":9'))
    assert DenseIndex.load(tmp_path) is None


# ---- building and caching ----

def test_build_embeds_each_distinct_text_once_in_batches(result):
    emb = CountingEmbedder()
    calls = []
    units = result.units + [CodeUnit(**{**result.units[0].to_dict(), "unit_id": "dup.py::copy"})]
    index = build_dense_index(units, emb, DenseSettings(backend="hashing", doc_prefix="", batch_size=5),
                              progress=lambda done, total: calls.append((done, total)))
    assert len(index.unit_ids) == 17
    assert len(emb.seen) == len(set(emb.seen)) == 17  # unique per (name, path, source)
    assert calls[-1] == (17, 17) and len(calls) == 4


def test_rebuild_reuses_vectors_of_unchanged_units(result):
    emb = CountingEmbedder()
    first = build_dense_index(result.units, emb, SETTINGS)
    emb.seen.clear()
    edited = [CodeUnit(**u.to_dict()) for u in result.units]
    edited[3].source_text += "\n    # edited"
    second = build_dense_index(edited, emb, SETTINGS, previous=first)
    assert len(emb.seen) == 1 and "# edited" in emb.seen[0]
    untouched = [i for i in range(len(edited)) if i != 3]
    assert np.array_equal(second.vectors[untouched], first.vectors[untouched])


def test_ensure_dense_index_lifecycle(result, tmp_path):
    emb = CountingEmbedder()
    _, reason = ensure_dense_index(result.units, tmp_path, emb, SETTINGS)
    assert reason == "no dense index yet" and len(emb.seen) == 16
    emb.seen.clear()
    _, reason = ensure_dense_index(result.units, tmp_path, emb, SETTINGS)
    assert reason is None and emb.seen == []  # fresh: nothing re-embedded
    changed = [u for u in result.units if u.unit_id != "utils.py::add"]
    index, reason = ensure_dense_index(changed, tmp_path, emb, SETTINGS)
    assert reason == "units changed (0 to embed)" and emb.seen == []
    assert "utils.py::add" not in index.unit_ids
    _, reason = ensure_dense_index(changed, tmp_path, emb, SETTINGS, rebuild=True)
    assert reason == "rebuild requested" and len(emb.seen) == 15


def test_changing_prefix_or_model_invalidates_vectors(result, tmp_path):
    emb = CountingEmbedder()
    ensure_dense_index(result.units, tmp_path, emb, SETTINGS)
    emb.seen.clear()
    _, reason = ensure_dense_index(result.units, tmp_path, emb, DenseSettings(backend="hashing", doc_prefix="D: "))
    assert reason.startswith("units changed") and len(emb.seen) == 16

    class Other(CountingEmbedder):
        def __init__(self):
            super().__init__()
            self.model = "other-model"

    other = Other()
    _, reason = ensure_dense_index(result.units, tmp_path, other, SETTINGS)
    assert reason.startswith("units changed") and len(other.seen) == 16


def test_embedder_returning_wrong_count_is_an_error(result):
    class Bad(Embedder):
        model = "bad"

        def embed(self, texts):
            return np.ones((1, 4), dtype=np.float32)

    with pytest.raises(EmbeddingError):
        build_dense_index(result.units, Bad(), SETTINGS)


# ---- dense search ----

def test_dense_finds_what_bm25_cannot(result):
    """A semantic model can match 'verify' to 'validate'; BM25 has no such term at all."""
    bm25 = BM25Index.build(build_text_records(result.units))
    assert bm25.search("verify") == []
    emb = SynonymEmbedder()
    index = build_dense_index(result.units, emb, SETTINGS)
    by_id = {u.unit_id: u for u in result.units}
    hits = dense_search(index, emb, SETTINGS, by_id, "verify", k=3)
    assert "db.py::validate_user_input" in [h.unit_id for h in hits[:2]]


def test_dense_results_use_ranked_result_format(result):
    emb = HashingEmbedder()
    index = build_dense_index(result.units, emb, SETTINGS)
    by_id = {u.unit_id: u for u in result.units}
    failed = {f.rel_path: f for f in result.failed_files}
    hits = dense_search(index, emb, SETTINGS, by_id, "broken syntax", k=16, query_id="q9", failed_by_path=failed)
    assert len(hits) == 16  # dense search always fills k
    top = hits[0]
    assert isinstance(top, RankedResult) and top.query_id == "q9"
    assert top.unit_id == "broken_syntax.py::<module>"
    assert top.text_score == 0.0 and top.graph_score is None
    assert top.dense_score == top.final_score > 0
    assert any("semantic similarity" in e and "hashing-256" in e for e in top.evidence)
    assert any("did not parse" in e for e in top.evidence)
    scores = [h.final_score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_ranked_result_dense_score_defaults_to_none():
    res = RankedResult(query_id="q", unit_id="u")
    assert res.dense_score is None
    assert RankedResult.from_dict(res.to_dict()) == res
    legacy = RankedResult("q", "u", 1.0, 0.5, None, 1.5, ["e"])  # positional use still works
    assert legacy.evidence == ["e"] and legacy.dense_score is None


# ---- numerical safety ----

def test_scoring_emits_no_floating_point_warnings(result):
    import warnings

    emb = HashingEmbedder()
    index = build_dense_index(result.units, emb, SETTINGS)
    query = embed_query(emb, SETTINGS, "read a file")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any RuntimeWarning from the matrix product fails the test
        index.score_all(query)
        index.search(query, 5)


def test_non_finite_values_are_rejected(result):
    bad = DenseIndex(["a", "b"], np.array([[1, 0], [np.nan, 1]], dtype=np.float32), ["h1", "h2"], "m")
    with pytest.raises(EmbeddingError, match="NaN or infinity"):
        bad.score_all(np.array([1.0, 0.0]))

    class NanEmbedder(HashingEmbedder):
        def embed(self, texts):
            out = super().embed(texts)
            out[0, 0] = np.nan
            return out

    with pytest.raises(EmbeddingError, match="NaN or infinite"):
        build_dense_index(result.units, NanEmbedder(), SETTINGS)
