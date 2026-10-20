import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from structsearch.interface.cli import main
from structsearch.interface.explain import (
    explain_results,
    template_explanation,
    validate_llm_explanation,
)
from structsearch.interface.service import MODES, SearchRequest, SearchError, run_search
from structsearch.config import load_config
from structsearch.llm.ollama import LLMError, LLMSettings
from structsearch.schemas import CodeUnit, RankedResult

CORPUS = Path(__file__).parent / "fixtures" / "sample_corpus"


def make_unit(uid="a.py::f", code="def f(x):\n    return f(x - 1)\n"):
    return CodeUnit(unit_id=uid, file_path="a.py", start_line=1, end_line=2, name="f", source_text=code)


def make_result(evidence, uid="a.py::f"):
    return RankedResult(query_id="q", unit_id=uid, evidence=evidence)


EVIDENCE = [
    "fusion: text 1.00x0.67 + structural 1.00x0.33 = 1.000",
    "term match in name: factorial",
    "structural match: calls itself (self_call=1)",
]


def settings(**kw):
    base = dict(enabled=True, host="http://127.0.0.1:1", model="m", fallback_model=None, timeout_seconds=2)
    base.update(kw)
    return LLMSettings(**base)


# ---- template ----

def test_template_uses_only_evidence():
    exp = template_explanation(make_result(EVIDENCE), make_unit())
    assert exp.source == "template" and exp.cited == [1, 2, 3]
    assert "factorial" in " ".join(exp.points) and "calls itself" in " ".join(exp.points)
    assert exp.summary.startswith("a.py::f (lines 1-2)")


def test_template_parse_failure_and_empty():
    exp = template_explanation(make_result(["file did not parse (x)"]), make_unit())
    assert "does not parse" in exp.summary
    assert "no detailed evidence" in template_explanation(make_result([]), make_unit()).summary


# ---- validation ----

def check(data, evidence=EVIDENCE, query="recursive factorial"):
    return validate_llm_explanation(data, query, make_result(evidence), make_unit())


def test_valid_answer_accepted():
    summary, cites = check({"summary": "Matches the term factorial and calls itself.", "cites": [3, 2, 2]})
    assert cites == [2, 3]


@pytest.mark.parametrize(
    "data",
    [
        "text",
        {"summary": "", "cites": [1]},
        {"summary": "ok", "cites": []},
        {"summary": "ok", "cites": [9]},
        {"summary": "ok", "cites": [0]},
        {"summary": "ok", "cites": [True]},
        {"summary": "x" * 600, "cites": [1]},
        {"summary": "This is vulnerable to injection.", "cites": [1]},
        {"summary": "Confirmed bug here.", "cites": [1]},
        {"summary": "It calls `os.system` directly.", "cites": [1]},
        {"summary": "It uses run_command_now.", "cites": [1]},
        {"summary": "It has 42 branches.", "cites": [1]},
    ],
)
def test_ungrounded_or_overclaiming_rejected(data):
    with pytest.raises(ValueError):
        check(data)


def test_names_from_code_and_query_allowed():
    summary, _ = check({"summary": "It calls `f` on x - 1.", "cites": [3]})
    assert summary


# ---- explain_results with a stub client ----

class Stub:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, model):
        outer = self

        class C:
            def generate_json(self, prompt, schema):
                outer.calls += 1
                a = outer.answers.pop(0)
                if isinstance(a, Exception):
                    raise a
                return a

        return C()


def two_results():
    units = {"a.py::f": make_unit(), "b.py::g": make_unit("b.py::g")}
    results = [make_result(EVIDENCE), make_result(EVIDENCE, "b.py::g")]
    return results, units


def test_llm_top_only_and_template_for_rest():
    results, units = two_results()
    stub = Stub([{"summary": "Matches the term factorial.", "cites": [2]}])
    out = explain_results("factorial", results, units, "llm", settings(), top=1, client_factory=stub)
    assert out["a.py::f"].source == "llm:m" and out["b.py::g"].source == "template"
    assert stub.calls == 1 and out["b.py::g"].fallback_reason is None


def test_llm_error_stops_further_calls():
    results, units = two_results()
    stub = Stub([LLMError("down")])
    notes = []
    out = explain_results("q", results, units, "llm", settings(), top=5, client_factory=stub, notify=notes.append)
    assert stub.calls == 1 and len(notes) == 1
    assert all(e.source == "template" and "unavailable" in e.fallback_reason for e in out.values())


def test_llm_rejected_answer_falls_back_per_result():
    results, units = two_results()
    stub = Stub([{"summary": "Vulnerable!", "cites": [1]}, {"summary": "Matches the term factorial.", "cites": [2]}])
    out = explain_results("q", results, units, "llm", settings(), top=2, client_factory=stub)
    assert out["a.py::f"].source == "template" and "rejected" in out["a.py::f"].fallback_reason
    assert out["b.py::g"].source == "llm:m"


def test_unknown_method():
    with pytest.raises(ValueError):
        explain_results("q", [], {}, "magic")


# ---- fake Ollama server ----

class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"response": json.dumps(self.server.answer)}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    srv.answer = {"summary": "Matches the term factorial.", "cites": [2]}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_real_http_client(server):
    results, units = two_results()
    cfg = settings(host=f"http://127.0.0.1:{server.server_address[1]}")
    out = explain_results("factorial", results[:1], units, "llm", cfg)
    assert out["a.py::f"].source == "llm:m"


# ---- CLI ----

def run_cli(capsys, *args):
    code = main(["search", *args, "--corpus", str(CORPUS)])
    return code, capsys.readouterr()


def test_cli_explain_template_text(tmp_path, capsys):
    code, cap = run_cli(capsys, "factorial", "--mode", "text_ast", "--explain", "--index-dir", str(tmp_path / "i"))
    assert code == 0 and "why:" in cap.out


def test_cli_explain_json(tmp_path, capsys):
    code, cap = run_cli(capsys, "factorial", "--json", "--explain", "--index-dir", str(tmp_path / "i"))
    data = json.loads(cap.out)
    assert code == 0 and data["results"][0]["explanation"]["source"] == "template"


def test_cli_no_explain_by_default(tmp_path, capsys):
    code, cap = run_cli(capsys, "factorial", "--json", "--index-dir", str(tmp_path / "i"))
    assert "explanation" not in json.loads(cap.out)["results"][0]


def test_cli_explain_llm_unreachable_falls_back(tmp_path, capsys, monkeypatch):
    import structsearch.interface.cli as cli

    monkeypatch.setattr(cli, "_llm_settings", lambda a, c: settings())
    code, cap = run_cli(capsys, "factorial", "--json", "--explain", "llm", "--index-dir", str(tmp_path / "i"))
    first = json.loads(cap.out)["results"][0]["explanation"]
    assert code == 0 and first["source"] == "template" and "unavailable" in first["fallback_reason"]


# ---- service ----

@pytest.mark.parametrize("mode", [m for m in MODES if m not in ("dense", "hybrid", "like")])
def test_service_modes(tmp_path, mode):
    cfg = load_config()
    query = "recursive function" if mode == "structural" else "factorial"
    req = SearchRequest(query=query, mode=mode, k=3, corpus=str(CORPUS), index_dir=str(tmp_path / "i"))
    resp = run_search(req, cfg)
    assert resp.results and all(r.unit_id in resp.units_by_id for r in resp.results)


def test_service_bad_corpus(tmp_path):
    req = SearchRequest(query="x", mode="bm25", k=3, corpus=str(tmp_path / "nope"), index_dir=str(tmp_path / "i"))
    with pytest.raises(SearchError) as exc:
        run_search(req, load_config())
    assert exc.value.code == 2


def test_streamlit_helper(tmp_path):
    from structsearch.interface.streamlit_app import search_rows

    data = search_rows("factorial", "text_ast", 3, str(CORPUS), str(tmp_path / "i"), "template", False, [])
    assert data["rows"] and data["rows"][0]["explanation"]["source"] == "template"
