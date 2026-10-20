"""Optional Streamlit front end:  streamlit run structsearch/interface/streamlit_app.py

Uses the same service and explanation layers as the CLI. Dense/hybrid modes need Ollama's embedding
model; --explain llm style explanations need an Ollama chat model; everything else works offline.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# `streamlit run` puts this file's folder on sys.path, not the repo root.
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from structsearch.config import load_config
from structsearch.interface.explain import explain_results
from structsearch.interface.format import result_to_dict
from structsearch.interface.service import MODES, SearchError, SearchRequest, run_search
from structsearch.llm.ollama import LLMSettings


def search_rows(query: str, mode: str, k: int, corpus: str, index_dir: str, explain: str, use_llm_mapper: bool,
                patterns: List[str]) -> Dict[str, Any]:
    """Run one search and return plain data for display (no Streamlit needed; unit-testable)."""
    cfg = load_config()
    settings = LLMSettings.from_config(cfg, enabled=True if use_llm_mapper else None)
    response = run_search(
        SearchRequest(query=query, mode=mode, k=k, corpus=corpus, index_dir=index_dir,
                      llm=settings, patterns=patterns),
        cfg,
    )
    notes: List[str] = []
    explanations = None
    if explain != "none":
        explanations = explain_results(query, response.results, response.units_by_id, method=explain,
                                       llm=LLMSettings.from_config(cfg, enabled=True), notify=notes.append)
    rows = [
        result_to_dict(r, response.units_by_id[r.unit_id], 12, (explanations or {}).get(r.unit_id))
        for r in response.results
    ]
    return {"rows": rows, "total_units": response.total_units, "extra": response.extra, "notes": notes}


def main() -> None:  # pragma: no cover - exercised through streamlit
    import streamlit as st

    cfg = load_config()
    st.set_page_config(page_title="StructSearch", layout="wide")
    st.title("StructSearch")
    with st.sidebar:
        mode = st.selectbox("Mode", MODES, index=MODES.index("text_ast"))
        k = st.slider("Results", 1, 20, int(cfg["top_k"]))
        corpus = st.text_input("Corpus", cfg["corpus_path"])
        index_dir = st.text_input("Index folder", cfg["index_dir"])
        explain = st.selectbox("Explanation", ["template", "none", "llm"])
        use_llm_mapper = st.checkbox("Map query with Ollama", value=False)
        patterns = [p for p in st.text_area("Structural patterns (one per line)").splitlines() if p.strip()]
    query = st.text_input("Query", placeholder="function that opens a file without closing it")
    if not query:
        return
    try:
        with st.spinner("Searching..."):
            data = search_rows(query, mode, k, corpus, index_dir, explain, use_llm_mapper, patterns)
    except SearchError as exc:
        st.error(str(exc))
        return
    for note in data["notes"]:
        st.info(note)
    st.caption(f"{len(data['rows'])} of {data['total_units']} units shown")
    for row in data["rows"]:
        with st.expander(f"{row['unit_id']}  -  score {row['final_score']:.3f}", expanded=True):
            if "explanation" in row:
                st.write(row["explanation"]["summary"])
            st.code(row["excerpt"], language="python")
            st.markdown("\n".join(f"- {line}" for line in row["evidence"]))


if __name__ == "__main__":  # pragma: no cover
    main()
