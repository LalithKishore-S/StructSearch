"""StructSearch command line.

  python -m structsearch index [CORPUS] [--dense]       build/refresh the index(es)
  python -m structsearch search "read file" -k 5        BM25 search (builds the index if needed)
  python -m structsearch search "check credentials" --mode dense   semantic search (needs Ollama)
  python -m structsearch features [UNIT]                show the AST features of one unit (or a table of all)
  python -m structsearch search "recursive traversal" --mode structural   AST-constraint search
  python -m structsearch search "recursive tree traversal" --mode text_ast   BM25 + structure, fused
  python -m structsearch search "validate input before database access" --mode text_graph   BM25 + call graph, fused
  python -m structsearch search "check credentials" --mode hybrid            BM25 + dense + structure + graph, fused
  python -m structsearch search "..." --mode structural --pattern "For//Try"   add an explicit pattern
  python -m structsearch search "@snippet.py" --mode like               structure similar to a code snippet
  python -m structsearch profile "read file without error handling"       show the constraints a query maps to
  python -m structsearch fragments UNIT                                  show a unit's structure relations
  python -m structsearch graph [UNIT]                                    show the call graph (or one unit's calls, markers and callers)
  python -m structsearch security                                        candidate paths from input to SQL construction
  python -m structsearch benchmark check|freeze                          validate / freeze the query set and labels
  python -m structsearch graph --markers                                 list the API/database/validation markers

Status messages go to stderr so that --json output on stdout stays clean.
Exit codes: 0 ok, 2 bad argument or missing corpus, 3 embedding backend problem.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Callable, List, Optional

from structsearch.config import load_config
from structsearch.indexing.builder import FAILED_FILE, ensure_index
from structsearch.graph import INTENTS, REL_CALLS, REL_USES_API, describe_markers, ensure_graph
from structsearch.indexing.embedder import EmbeddingError
from structsearch.ingestion.corpus import load_failed
from structsearch.interface.explain import explain_results
from structsearch.parsing.tolerant import TolerantUnavailable
from structsearch.schemas import PARSEABLE, status_flag
from structsearch.interface.format import format_results, result_to_dict
from structsearch.interface.service import (
    MODES,
    SearchError,
    SearchRequest,
    make_profile,
    prepare_dense,
    run_search,
)
from structsearch.llm import LLMSettings
from structsearch.parsing import (
    FEATURE_NAMES,
    describe_term,
    ensure_ast_records,
    ensure_fragment_records,
    node_type_counts,
)


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _add_dense_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--embedder",
        choices=("ollama", "hashing"),
        default=None,
        help="dense backend (default from config; 'hashing' is lexical, for tests/offline demos)",
    )
    parser.add_argument("--model", default=None, help="Ollama embedding model (default from config)")


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="map the query to structural constraints with a local Ollama model (falls back to rules)",
    )
    parser.add_argument("--llm-model", default=None, help="Ollama model for --use-llm (default from config)")


def _add_pattern_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        metavar="PATTERN",
        help='structural pattern, repeatable and ANDed, e.g. "For//Try", "!With//Call:open", "If=>Call:execute"',
    )


def _add_intent_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--intent",
        action="append",
        default=[],
        choices=INTENTS,
        help="call-graph relationship for text_graph/hybrid instead of reading it from the query (repeatable, averaged)",
    )


def _llm_settings(args, cfg) -> LLMSettings:
    enabled = True if getattr(args, "use_llm", False) else None  # None keeps the config value
    return LLMSettings.from_config(cfg, model=getattr(args, "llm_model", None), enabled=enabled)


def _build_parser(cfg) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="structsearch", description="Structure-aware code search.")
    sub = parser.add_subparsers(dest="command", required=True)

    index_p = sub.add_parser("index", help="build or refresh the index")
    index_p.add_argument("corpus", nargs="?", default=cfg["corpus_path"], help="folder (or file) to index")
    index_p.add_argument("--index-dir", default=cfg["index_dir"])
    index_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    index_p.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    index_p.add_argument("--rebuild", action="store_true", help="force a rebuild")
    index_p.add_argument("--dense", action="store_true", help="also build the dense (embedding) index")
    _add_dense_args(index_p)

    search_p = sub.add_parser("search", help="search the indexed code")
    search_p.add_argument("query")
    search_p.add_argument("-k", type=int, default=cfg["top_k"], help="number of results")
    search_p.add_argument("--mode", choices=MODES, default="bm25")
    search_p.add_argument("--corpus", default=cfg["corpus_path"], help="folder (or file) to search")
    search_p.add_argument("--index-dir", default=cfg["index_dir"])
    search_p.add_argument("--lines", type=int, default=8, help="excerpt lines per result")
    search_p.add_argument("--json", action="store_true", help="machine-readable output")
    search_p.add_argument("--rebuild", action="store_true", help="force an index rebuild first")
    search_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    search_p.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    search_p.add_argument("--query-id", default="adhoc", help="id stored in the result records")
    _add_dense_args(search_p)
    _add_llm_args(search_p)
    _add_pattern_arg(search_p)
    _add_intent_arg(search_p)
    search_p.add_argument(
        "--weight",
        action="append",
        default=[],
        metavar="SIGNAL=VALUE",
        help="override a fusion weight for text_ast/text_graph/hybrid, e.g. --weight structural=0.5 (repeatable)",
    )

    search_p.add_argument(
        "--explain",
        nargs="?",
        const="template",
        choices=("template", "llm"),
        default=None,
        help="add a 'why' line per result: template (default, no Ollama) or llm (Ollama, validated, falls back to template)",
    )
    search_p.add_argument("--explain-top", type=int, default=3, help="with --explain llm: results sent to the model")

    exp_p = sub.add_parser("experiment", help="run variants over labelled queries and write result tables")
    exp_p.add_argument("--queries", required=True, help="queries file (json/jsonl/csv)")
    exp_p.add_argument("--labels", required=True, help="labels file (json/jsonl/csv)")
    exp_p.add_argument("--variants", default="bm25,dense,text_ast,text_graph,hybrid", help="comma list, e.g. bm25,text_ast,text_ast+llm,text_ast_graph-graph (-SIGNAL removes a signal)")
    exp_p.add_argument("--out", default="results")
    exp_p.add_argument("-k", type=int, default=cfg["top_k"])
    exp_p.add_argument("--corpus", default=cfg["corpus_path"])
    exp_p.add_argument("--index-dir", default=cfg["index_dir"])
    exp_p.add_argument("--final", action="store_true", help="also run the test split (do this once, after tuning on dev)")
    exp_p.add_argument("--tune", choices=("text_ast", "text_graph", "text_ast_graph", "hybrid"), default=None, help="grid-search fusion weights on dev only")
    exp_p.add_argument("--step", type=float, default=0.25, help="grid step for --tune")
    exp_p.add_argument("--min-weight", type=float, default=0.0,
                       help="with --tune: every signal keeps at least this weight (e.g. 0.25), so the variant stays what it is named")
    exp_p.add_argument("--ks", default=None, help="comma list of K for the tables, e.g. 1,3,5 (the run retrieves max K); "
                       "adds summary_by_k.csv, paired.csv, report.md and run.json")
    exp_p.add_argument("--baseline", default=None, help="variant the paired comparison is made against (default: the first)")
    _add_dense_args(exp_p)
    _add_llm_args(exp_p)

    prof_p = sub.add_parser("profile", help="show the structural constraints a query maps to")
    prof_p.add_argument("query")
    prof_p.add_argument("--json", action="store_true")
    _add_llm_args(prof_p)
    _add_pattern_arg(prof_p)

    frag_p = sub.add_parser("fragments", help="show the structure relations (fragment terms) of a unit")
    frag_p.add_argument("unit", help="unit id or part of one, e.g. db.py::find_user_unsafe")
    frag_p.add_argument("--corpus", default=cfg["corpus_path"])
    frag_p.add_argument("--index-dir", default=cfg["index_dir"])
    frag_p.add_argument("--kind", choices=("u", "pc", "ch3", "ad", "ord"), default=None, help="only one relation kind")
    frag_p.add_argument("--json", action="store_true")
    frag_p.add_argument("--skip-failed", action="store_true")
    frag_p.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    frag_p.add_argument("--rebuild", action="store_true")

    bench_p = sub.add_parser("benchmark", help="check or freeze the query set and its relevance labels")
    bench_p.add_argument("action", choices=("check", "freeze"))
    bench_p.add_argument("--queries", default="experiments/benchmark/queries.json")
    bench_p.add_argument("--labels", default="experiments/benchmark/labels.jsonl")
    bench_p.add_argument("--corpus", default=cfg["corpus_path"], help="corpus whose unit ids the labels must cover")
    bench_p.add_argument("--lock", default=None, help="freeze lock (default: split.lock next to the queries file)")
    bench_p.add_argument("--json", action="store_true")

    sec_p = sub.add_parser("security", help="list candidate paths from input to SQL text construction (for review, not proof)")
    sec_p.add_argument("-k", type=int, default=cfg["top_k"], help="number of candidates")
    sec_p.add_argument("--corpus", default=cfg["corpus_path"])
    sec_p.add_argument("--index-dir", default=cfg["index_dir"])
    sec_p.add_argument("--min-level", choices=("low", "medium", "high"), default="low")
    sec_p.add_argument("--lines", type=int, default=8, help="excerpt lines per candidate")
    sec_p.add_argument("--json", action="store_true")
    sec_p.add_argument("--skip-failed", action="store_true")
    sec_p.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    sec_p.add_argument("--rebuild", action="store_true")

    graph_p = sub.add_parser("graph", help="show the call graph of the corpus (or the calls and callers of one unit)")
    graph_p.add_argument("unit", nargs="?", help="unit id or part of one, e.g. db.py::get_user")
    graph_p.add_argument("--corpus", default=cfg["corpus_path"])
    graph_p.add_argument("--index-dir", default=cfg["index_dir"])
    graph_p.add_argument("--json", action="store_true")
    graph_p.add_argument("--skip-failed", action="store_true")
    graph_p.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    graph_p.add_argument("--rebuild", action="store_true")
    graph_p.add_argument("--markers", action="store_true", help="list the API/database/validation markers and exit")

    feat_p = sub.add_parser("features", help="show AST features of a unit (or a table of all units)")
    feat_p.add_argument("unit", nargs="?", help="unit id or part of one, e.g. trees.py::factorial")
    feat_p.add_argument("--corpus", default=cfg["corpus_path"])
    feat_p.add_argument("--index-dir", default=cfg["index_dir"])
    feat_p.add_argument("--json", action="store_true")
    feat_p.add_argument("--skip-failed", action="store_true", help="leave unparseable files out")
    feat_p.add_argument("--tolerant", action="store_true", help="recover functions from files that do not parse (needs tree-sitter)")
    feat_p.add_argument("--rebuild", action="store_true", help="force an index rebuild first")
    return parser


TABLE_COLUMNS = (
    ("if", "if_count"), ("for", "for_count"), ("while", "while_count"), ("try", "try_count"),
    ("call", "call_count"), ("ret", "return_count"), ("depth", "max_depth"), ("self", "self_call"),
)


def _features_command(args) -> int:
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, _ = loaded
    records, reason = ensure_ast_records(units, args.index_dir)
    if reason:
        _err(f"AST features extracted ({reason}): {len(records)} units")
    pairs = list(zip(units, records))
    if args.unit:
        chosen = [p for p in pairs if p[0].unit_id == args.unit] or [p for p in pairs if args.unit in p[0].unit_id]
        if not chosen:
            _err(f"error: no unit matches '{args.unit}'")
            return 2
        pairs = chosen

    if args.json:
        payload = [
            {"unit_id": u.unit_id, "parse_status": r.parse_status, "features": r.features} for u, r in pairs
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if not args.unit:
        width = max((len(u.unit_id) for u, _ in pairs), default=4)
        print(f"{'unit':<{width}}  " + " ".join(f"{label:>5}" for label, _ in TABLE_COLUMNS))
        for unit, rec in pairs:
            if rec.parse_status not in PARSEABLE:
                print(f"{unit.unit_id:<{width}}  (did not parse: no AST features)")
                continue
            cells = " ".join(f"{int(rec.features[name]):>5}" for _, name in TABLE_COLUMNS)
            print(f"{unit.unit_id:<{width}}  {cells}{status_flag(unit)}")
        return 0

    for unit, rec in pairs[:10]:
        print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]{status_flag(unit)}")
        if rec.parse_status not in PARSEABLE:
            print("  did not parse: no AST features")
            continue
        for name in FEATURE_NAMES:
            if rec.features.get(name):
                print(f"  {name:<24}{rec.features[name]:g}")
        types = sorted(node_type_counts(rec).items(), key=lambda kv: (-kv[1], kv[0]))
        print("  node types: " + ", ".join(f"{t}={int(n)}" for t, n in types))
        print()
    if len(pairs) > 10:
        _err(f"note: {len(pairs) - 10} more matching units not shown; use a longer unit id")
    return 0


def _security_command(args) -> int:
    from structsearch.security import (
        DISCLAIMER, LEVELS, NOT_MODELLED, PATTERN_QUERY, candidates_to_results, scan_sql_candidates,
    )

    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, _ = loaded
    graph, reason = ensure_graph(units, args.index_dir)
    if reason:
        _err(f"graph built ({reason}): {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    order = [name for name, _ in LEVELS]
    candidates = [c for c in scan_sql_candidates(units, graph) if order.index(c.level) <= order.index(args.min_level)]
    total = len(candidates)
    candidates = candidates[: args.k]
    results = candidates_to_results(candidates)
    units_by_id = {u.unit_id: u for u in units}
    if args.json:
        rows = []
        for cand, res in zip(candidates, results):
            row = result_to_dict(res, units_by_id[res.unit_id], args.lines)
            row.update({"level": cand.level, "hops": cand.hops})
            rows.append(row)
        print(json.dumps({"pattern": PATTERN_QUERY, "disclaimer": DISCLAIMER, "not_modelled": NOT_MODELLED,
                          "candidates_found": total, "results": rows}, indent=2))
        return 0
    print("Candidates for review, not confirmed vulnerabilities.")
    if not results:
        print(f'Pattern: "{PATTERN_QUERY}"\n\nNo candidates.')
        return 0
    print(format_results(PATTERN_QUERY, results, units_by_id, len(units), args.lines, mode="security"), end="")
    if total > len(results):
        print(f"({total - len(results)} more candidate(s); raise -k)")
    print("Not modelled: " + "; ".join(NOT_MODELLED))
    return 0


def _benchmark_command(args) -> int:
    from structsearch.evaluation import check_benchmark, freeze_benchmark
    from structsearch.ingestion import ingest_corpus

    try:
        if not Path(args.corpus).exists():
            raise OSError(f"corpus path not found: {args.corpus}")
        unit_ids = [u.unit_id for u in ingest_corpus(args.corpus).units]
        if args.action == "freeze":
            lock = freeze_benchmark(args.queries, args.labels, unit_ids, args.lock)
            print(f"frozen: {lock}")
            return 0
        report = check_benchmark(args.queries, args.labels, unit_ids, args.lock)
    except (OSError, ValueError, KeyError) as exc:
        _err(f"error: {exc}")
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        st = report.stats
        print(f"queries: {st['queries']}   labels: {st['labels']}   units in pool: {st['units_in_pool']}")
        for key, n in st["by_split_category"].items():
            print(f"  {key:<20} {n}")
        print(f"frozen: {'yes' if report.frozen else 'no'}")
        for warning in report.warnings:
            print(f"warning: {warning}")
        print(f"problems: {len(report.problems)}")
        for problem in report.problems:
            print(f"  - {problem}")
    return 2 if report.problems else 0


def _graph_command(args) -> int:
    if args.markers:
        rows = describe_markers()
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        width = max(len(r["label"]) for r in rows)
        for r in rows:
            print(f"{r['label']:<{width}}  {r['matches']}")
            print(f"{'':<{width}}  {r['description']}")
        return 0
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, _ = loaded
    graph, reason = ensure_graph(units, args.index_dir)
    if reason:
        _err(f"graph built ({reason}): {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    if args.unit:
        ids = [u for u in graph.nodes if u == args.unit] or [u for u in graph.nodes if args.unit in u]
        if not ids:
            _err(f"error: no unit matches '{args.unit}'")
            return 2
        ids = ids[:5]
        if args.json:
            print(json.dumps([{
                "unit_id": u,
                "calls": [e.__dict__ for e in graph.edges_from(u)],
                "called_by": [e.__dict__ for e in graph.edges_to(u)],
            } for u in ids], indent=2))
            return 0
        for unit_id in ids:
            node = graph.nodes[unit_id]
            print(f"{unit_id}{'' if node.parse_status == 'ok' else f'  [{node.parse_status}]'}")
            outgoing, incoming = graph.edges_from(unit_id), graph.edges_to(unit_id)
            print("  calls:" + ("" if outgoing else " (none)"))
            for e in outgoing:
                print(f"    -> {e.target}  ({e.relation}, line {e.line}, {e.method})" + (f"  via {e.detail}" if e.detail else ""))
            print("  called by:" + ("" if incoming else " (none)"))
            for e in incoming:
                print(f"    <- {e.source}  ({e.relation}, line {e.line}, {e.method})" + (f"  via {e.detail}" if e.detail else ""))
            print()
        return 0
    if args.json:
        print(json.dumps(graph.to_dict(), indent=2))
        return 0
    calls = [e for e in graph.edges if e.relation == REL_CALLS]
    api = [e for e in graph.edges if e.relation == REL_USES_API]
    print(f"nodes: {len(graph.nodes)}   edges: {len(graph.edges)} ({len(calls)} calls, {len(api)} uses_api)   "
          f"ambiguous calls: {len(graph.ambiguous)}")
    for e in graph.edges:
        print(f"  {e.source} -> {e.target}  ({e.relation}, line {e.line})")
    for a in graph.ambiguous:
        print(f"  ambiguous: {a.source} calls {a.name} (line {a.line}): {', '.join(a.candidates)}")
    return 0


def _load(args, corpus: str):
    corpus_path = Path(corpus)
    if not corpus_path.exists():
        _err(f"error: corpus path not found: {corpus}")
        return None
    units, index, reason = ensure_index(
        corpus_path,
        args.index_dir,
        include_failed=not args.skip_failed,
        rebuild=args.rebuild,
        tolerant=getattr(args, "tolerant", False),
    )
    if reason:
        _err(f"index built ({reason}): {len(units)} units -> {args.index_dir}")
    return units, index


def _progress_printer() -> Callable[[int, int], None]:
    state = {"last": -1}

    def report(done: int, total: int) -> None:
        percent = 100 * done // max(total, 1)
        if done == total or percent // 10 > state["last"] // 10:
            _err(f"  embedding units: {done}/{total}")
            state["last"] = percent

    return report


def _dense(args, cfg, units):
    """Used by the index command: (dense_index, embedder, settings), building or refreshing the index."""
    return prepare_dense(
        cfg, units, args.index_dir, args.embedder, args.model, args.rebuild, _err, _progress_printer()
    )


def main(argv: Optional[List[str]] = None) -> int:
    cfg = load_config()
    args = _build_parser(cfg).parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    try:
        return _run(args, cfg)
    except EmbeddingError as exc:
        _err(f"error: {exc}")
        return 3
    except TolerantUnavailable as exc:
        _err(f"error: {exc}")
        return 2


def _parse_ks(text: Optional[str]) -> List[int]:
    if not text:
        return []
    try:
        ks = sorted({int(x) for x in text.split(",") if x.strip()})
    except ValueError:
        ks = []
    if not ks or any(k < 1 for k in ks):
        raise ValueError("--ks must be a comma list of positive integers, e.g. 1,3,5")
    return ks


def _write_tuning_log(rows, mode: str, args, out_dir: Path) -> Path:
    names = list(rows[0]["weights"]) if rows else []
    lines = [f"# Weight tuning: {mode} (dev only)", "",
             f"Grid step {args.step}, selection metric nDCG@k at K = {args.k}, {rows[0]['n'] if rows else 0} dev queries. "
             "Ties on nDCG@k and MRR go to the more text-heavy weights. The test split is not read."
             + (f" Constraint: every signal keeps a weight of at least {args.min_weight:g}." if args.min_weight else ""), "",
             "| " + " | ".join(names) + " | P@k | R@k | MRR | nDCG@k |", "|" + "---|" * (len(names) + 4)]
    for row in rows:
        lines.append("| " + " | ".join(f"{row['weights'][n]:.2f}" for n in names) + " | "
                     + " | ".join(f"{row[m]:.3f}" for m in ("P@k", "R@k", "MRR", "nDCG@k")) + " |")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (f"tuning_{mode}_min{args.min_weight:g}.md" if args.min_weight else f"tuning_{mode}.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_run_info(args, cfg, variants, ks, splits, baseline, out_dir: Path) -> Path:
    lock_path = Path(args.queries).with_name("split.lock")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else None
    except (OSError, ValueError):
        lock = None
    keys = ("weights", "text_graph_weights", "text_ast_graph_weights", "hybrid_weights", "bm25")
    info = {"queries": args.queries, "labels": args.labels, "corpus": args.corpus, "variants": variants, "ks": ks,
            "splits": list(splits), "baseline": baseline, "benchmark_lock": lock,
            "weights": {k: cfg[k] for k in keys if k in cfg}, "python": sys.version.split()[0]}
    path = out_dir / "run.json"
    path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return path


def _experiment_command(args, cfg) -> int:
    from structsearch.experiments.report import write_report
    from structsearch.experiments.runner import (
        load_labels, load_queries, parse_variant, run_experiment, tune_weights, write_results,
    )

    try:
        ks = _parse_ks(args.ks)
        queries, labels = load_queries(args.queries), load_labels(args.labels)
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]
        for v in variants:
            parse_variant(v)
        splits = ("dev", "test") if args.final else ("dev",)
        if args.tune:
            rows = tune_weights(queries, labels, args.tune, cfg, args.corpus, args.index_dir, args.k, args.step, args.embedder,
                                min_weight=args.min_weight)
            print(f"weights tuned on dev only ({args.tune}); best first:")
            for row in rows[:5]:
                print(f"  {row['weights']}  nDCG@k={row['nDCG@k']:.3f} MRR={row['MRR']:.3f} (n={row['n']})")
            print("wrote: " + str(_write_tuning_log(rows, args.tune, args, Path(args.out))))
            return 0
        k_run = max(ks) if ks else args.k
        result = run_experiment(queries, labels, variants, cfg, args.corpus, args.index_dir, k_run, splits,
                                llm=_llm_settings(args, cfg), embedder=args.embedder)
    except (OSError, ValueError, KeyError, SearchError) as exc:
        _err(f"error: {exc}")
        return getattr(exc, "code", 2)
    except EmbeddingError as exc:
        _err(f"error: {exc}")
        return 3
    files = write_results(result, Path(args.out), k_run)
    print((Path(args.out) / "results.md").read_text(encoding="utf-8"))
    if ks:
        baseline = args.baseline or variants[0]
        try:
            files += write_report(result, labels, Path(args.out), ks, baseline)
        except ValueError as exc:
            _err(f"error: {exc}")
            return 2
        files.append(_write_run_info(args, cfg, variants, ks, splits, baseline, Path(args.out)))
        print((Path(args.out) / "report.md").read_text(encoding="utf-8"))
    print("wrote: " + ", ".join(str(f) for f in files))
    return 0


def _profile_for(args, cfg):
    """Profile from the query plus any --pattern flags. Raises SearchError for a bad flag."""
    return make_profile(args.query, _llm_settings(args, cfg), getattr(args, "pattern", []), _err)


def _profile_command(args, cfg) -> int:
    try:
        profile = _profile_for(args, cfg)
    except SearchError as exc:
        _err(f"error: {exc}")
        return exc.code
    if args.json:
        print(json.dumps({"query": args.query, **profile.to_dict()}, indent=2))
        return 0
    print(f"mapper: {profile.source}")
    if profile.is_empty:
        print("no structural requirements found in the query")
    for c in profile.constraints:
        op = f"{c.op} {c.value:g}" if c.op in ("at_least", "at_most") else c.op
        print(f"  {op:<12} {'+'.join(c.features):<50} {c.reason}")
    for r in profile.relations:
        print(f"  {'pattern':<12} {r.text:<50} {r.reason if r.reason != r.text else ''}".rstrip())
    return 0


def _fragments_command(args) -> int:
    loaded = _load(args, args.corpus)
    if loaded is None:
        return 2
    units, _ = loaded
    records, reason = ensure_fragment_records(units, args.index_dir)
    if reason:
        _err(f"fragments extracted ({reason}): {len(records)} units")
    pairs = list(zip(units, records))
    chosen = [p for p in pairs if p[0].unit_id == args.unit] or [p for p in pairs if args.unit in p[0].unit_id]
    if not chosen:
        _err(f"error: no unit matches '{args.unit}'")
        return 2
    chosen = chosen[:5]
    if args.json:
        print(json.dumps([{"unit_id": u.unit_id, "terms": {
            t: n for t, n in r.terms.items() if args.kind in (None, t.split(":", 1)[0])}} for u, r in chosen], indent=2))
        return 0
    for unit, rec in chosen:
        print(f"{unit.unit_id}  [{unit.start_line}-{unit.end_line}]{status_flag(unit)}")
        if rec.parse_status not in PARSEABLE:
            print("  did not parse: no fragments")
            continue
        for kind in ("ord", "ad", "ch3", "pc", "u"):
            if args.kind not in (None, kind):
                continue
            terms = sorted(t for t in rec.terms if t.split(":", 1)[0] == kind)
            print(f"  {kind} ({len(terms)}):")
            for term in terms[:25]:
                print(f"    {term[len(kind) + 1:]:<48} {describe_term(term)}")
            if len(terms) > 25:
                print(f"    ... +{len(terms) - 25} more (use --json)")
        print()
    return 0


def _run(args, cfg) -> int:
    if args.command == "features":
        return _features_command(args)
    if args.command == "experiment":
        return _experiment_command(args, cfg)
    if args.command == "profile":
        return _profile_command(args, cfg)
    if args.command == "fragments":
        return _fragments_command(args)
    if args.command == "graph":
        return _graph_command(args)
    if args.command == "benchmark":
        return _benchmark_command(args)
    if args.command == "security":
        return _security_command(args)

    if args.command == "index":
        loaded = _load(args, args.corpus)
        if loaded is None:
            return 2
        units, _ = loaded
        failed = load_failed(Path(args.index_dir) / FAILED_FILE)
        print(f"units indexed : {len(units)}")
        print(f"failed files  : {len(failed)}")
        for item in failed:
            where = f" (line {item.line})" if item.line else ""
            print(f"  - {item.rel_path}{where}: {item.error}")
        if args.dense:
            dense_index, _, _ = _dense(args, cfg, units)
            print(f"dense vectors : {len(dense_index.unit_ids)} x {dense_index.dim} (model {dense_index.model})")
        print(f"index folder  : {args.index_dir}")
        return 0

    # search
    request = SearchRequest(
        query=args.query,
        mode=args.mode,
        k=args.k,
        corpus=args.corpus,
        index_dir=args.index_dir,
        skip_failed=args.skip_failed,
        tolerant=args.tolerant,
        rebuild=args.rebuild,
        query_id=args.query_id,
        embedder=args.embedder,
        model=args.model,
        llm=_llm_settings(args, cfg),
        patterns=list(args.pattern),
        intents=list(args.intent),
        weights=list(args.weight),
    )
    try:
        response = run_search(request, cfg, notify=_err, progress=_progress_printer())
    except SearchError as exc:
        _err(f"error: {exc}")
        return exc.code

    units_by_id, results = response.units_by_id, response.results
    explanations = None
    if args.explain:
        explanations = explain_results(
            args.query,
            results,
            units_by_id,
            method=args.explain,
            llm=_llm_settings(args, cfg) if args.explain == "llm" else None,
            top=args.explain_top,
            notify=_err,
        )
    if args.json:
        payload = {
            "query": args.query,
            "mode": args.mode,
            "k": args.k,
            "units_indexed": response.total_units,
            **response.extra,
            "results": [
                result_to_dict(r, units_by_id[r.unit_id], args.lines, (explanations or {}).get(r.unit_id))
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_results(args.query, results, units_by_id, response.total_units, args.lines, args.mode, explanations))
    return 0
