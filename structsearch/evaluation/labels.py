"""Benchmark files: reading, validation and freezing of the query set and its relevance labels.

Queries (json / jsonl / csv): query_id, query, category (lexical | relationship), split (dev | test),
optional group (queries that ask for the same thing in different words), patterns, intents and notes.
Labels (EvaluationLabel): query_id, unit_id, relevance (0 = not relevant, 1 = relevant, higher grades
allowed), query_category, split.

`check_benchmark` returns every problem it finds (the benchmark is only usable without problems):
  - queries: required fields, unique ids, known category/split, no two queries with the same text;
  - paraphrase groups: same category, same split (so no paraphrase of a dev query sits in test) and the
    same relevant units;
  - labels: known query and unit, one label per (query, unit), integer relevance >= 0, category and split
    equal to the query's, at least one relevant unit per query;
  - pool: when the corpus unit ids are given, every query is judged against every unit (a complete pool,
    so Recall@K has an exact denominator).
Warnings cover size (the plan asks for 20-40 queries), missing categories per split and a missing freeze.

`freeze_benchmark` writes a lock (hashes of the queries with their split and of the labels) next to the
queries file; later checks report any change, so the test split cannot drift after weights are tuned.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

CATEGORIES = ("lexical", "relationship")
SPLITS = ("dev", "test")
LOCK_NAME = "split.lock"
MIN_QUERIES, MAX_QUERIES = 20, 40

PathLike = Union[str, Path]


def read_records(path: PathLike) -> List[Dict[str, Any]]:
    """Records of a json list, jsonl or csv file."""
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".csv"):
        return list(csv.DictReader(text.splitlines()))
    if text.lstrip().startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@dataclass
class BenchmarkReport:
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    frozen: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"problems": self.problems, "warnings": self.warnings, "stats": self.stats, "frozen": self.frozen}


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _digest(rows: Iterable[Sequence[Any]]) -> str:
    payload = json.dumps(sorted(list(map(list, rows))), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_grade(value: Any) -> Optional[int]:
    try:
        grade = int(value)
    except (TypeError, ValueError):
        return None
    return grade if grade >= 0 and str(value).strip().lstrip("+") == str(grade) else None


def _hashes(queries: Sequence[Dict[str, Any]], labels: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    q_rows = [(str(r.get("query_id")), _normalize(str(r.get("query", ""))), r.get("category") or r.get("query_category"),
               r.get("split")) for r in queries]
    l_rows = [(str(r.get("query_id")), str(r.get("unit_id")), _as_grade(r.get("relevance"))) for r in labels]
    return {"queries_sha256": _digest(q_rows), "labels_sha256": _digest(l_rows)}


def check_benchmark(
    queries_path: PathLike,
    labels_path: PathLike,
    unit_ids: Optional[Sequence[str]] = None,
    lock_path: Optional[PathLike] = None,
    use_lock: bool = True,
) -> BenchmarkReport:
    report = BenchmarkReport()
    problems, warnings = report.problems, report.warnings
    queries = read_records(queries_path)
    labels = read_records(labels_path)
    known_units = set(unit_ids) if unit_ids is not None else None

    # ---- queries
    by_id: Dict[str, Dict[str, Any]] = {}
    texts: Dict[str, str] = {}
    for rec in queries:
        qid = str(rec.get("query_id", "")).strip()
        text = rec.get("query")
        category = rec.get("category") or rec.get("query_category")
        split = rec.get("split")
        missing = [name for name, value in (("query_id", qid), ("query", text), ("category", category), ("split", split))
                   if value in (None, "")]
        if missing:
            problems.append(f"query {qid or '?'}: missing {', '.join(missing)}")
            continue
        if qid in by_id:
            problems.append(f"duplicate query_id {qid}")
            continue
        if not str(text).strip():
            problems.append(f"query {qid}: empty query text")
        if category not in CATEGORIES:
            problems.append(f"query {qid}: category must be one of {', '.join(CATEGORIES)}, got {category!r}")
        if split not in SPLITS:
            problems.append(f"query {qid}: split must be one of {', '.join(SPLITS)}, got {split!r}")
        norm = _normalize(str(text))
        if norm and norm in texts:
            problems.append(f"queries {texts[norm]} and {qid} have the same text")
        texts.setdefault(norm, qid)
        by_id[qid] = {"category": category, "split": split, "group": rec.get("group")}

    # ---- labels
    judged: Dict[str, Dict[str, int]] = {qid: {} for qid in by_id}
    seen_pairs = set()
    for rec in labels:
        qid, unit = str(rec.get("query_id", "")), str(rec.get("unit_id", ""))
        if qid not in by_id:
            problems.append(f"label for unknown query {qid!r}")
            continue
        if known_units is not None and unit not in known_units:
            problems.append(f"label for unknown unit {unit!r} (query {qid})")
        if (qid, unit) in seen_pairs:
            problems.append(f"duplicate label for query {qid}, unit {unit}")
            continue
        seen_pairs.add((qid, unit))
        grade = _as_grade(rec.get("relevance"))
        if grade is None:
            problems.append(f"label {qid}/{unit}: relevance must be an integer >= 0, got {rec.get('relevance')!r}")
            continue
        judged[qid][unit] = grade
        if rec.get("split") != by_id[qid]["split"]:
            problems.append(f"label {qid}/{unit}: split {rec.get('split')!r} differs from the query's {by_id[qid]['split']!r}")
        if rec.get("query_category") != by_id[qid]["category"]:
            problems.append(
                f"label {qid}/{unit}: category {rec.get('query_category')!r} differs from the query's {by_id[qid]['category']!r}")

    relevant: Dict[str, List[str]] = {}
    for qid, grades in judged.items():
        if not grades:
            problems.append(f"query {qid} has no labels")
            continue
        relevant[qid] = sorted(u for u, g in grades.items() if g > 0)
        if not relevant[qid]:
            problems.append(f"query {qid} has no relevant unit (it would be skipped by the experiments)")
        if known_units is not None:
            gap = sorted(known_units - set(grades))
            if gap:
                problems.append(f"query {qid}: {len(gap)} unit(s) not judged, e.g. {gap[0]}")

    # ---- paraphrase groups
    groups: Dict[str, List[str]] = {}
    for qid, info in by_id.items():
        if info["group"]:
            groups.setdefault(str(info["group"]), []).append(qid)
    for group, members in sorted(groups.items()):
        if len(members) < 2:
            warnings.append(f"group {group} has a single query")
        if len({by_id[m]["split"] for m in members}) > 1:
            problems.append(f"group {group}: queries differ in split ({', '.join(members)}); paraphrases must stay together")
        if len({by_id[m]["category"] for m in members}) > 1:
            problems.append(f"group {group}: queries differ in category ({', '.join(members)})")
        if len({tuple(relevant.get(m, ())) for m in members}) > 1:
            problems.append(f"group {group}: queries have different relevant units ({', '.join(members)})")

    # ---- stats and warnings
    counts = Counter(f"{i['split']}/{i['category']}" for i in by_id.values())
    report.stats = {
        "queries": len(by_id),
        "labels": len(seen_pairs),
        "by_split_category": dict(sorted(counts.items())),
        "relevant_per_query": {qid: len(units) for qid, units in sorted(relevant.items())},
        "groups": {g: members for g, members in sorted(groups.items())},
        "units_in_pool": len(known_units) if known_units is not None else None,
    }
    if not MIN_QUERIES <= len(by_id) <= MAX_QUERIES:
        warnings.append(f"{len(by_id)} queries; the plan asks for {MIN_QUERIES}-{MAX_QUERIES}")
    for split in SPLITS:
        for category in CATEGORIES:
            if not counts.get(f"{split}/{category}"):
                warnings.append(f"no {category} queries in the {split} split")

    # ---- freeze lock
    lock = Path(lock_path) if lock_path else Path(queries_path).with_name(LOCK_NAME)
    if not use_lock:
        return report
    if lock.exists():
        report.frozen = True
        try:
            frozen = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{lock.name} cannot be read")
            frozen = {}
        now = _hashes(queries, labels)
        if frozen.get("queries_sha256") != now["queries_sha256"]:
            problems.append(f"benchmark queries (text, category or split) changed since it was frozen ({lock.name})")
        if frozen.get("labels_sha256") != now["labels_sha256"]:
            problems.append(f"benchmark labels changed since it was frozen ({lock.name})")
    else:
        warnings.append(f"benchmark is not frozen (run `benchmark freeze` before tuning; no {lock.name})")
    return report


def freeze_benchmark(
    queries_path: PathLike,
    labels_path: PathLike,
    unit_ids: Optional[Sequence[str]] = None,
    lock_path: Optional[PathLike] = None,
) -> Path:
    """Write the lock for a benchmark without problems; raises ValueError otherwise."""
    lock = Path(lock_path) if lock_path else Path(queries_path).with_name(LOCK_NAME)
    report = check_benchmark(queries_path, labels_path, unit_ids, use_lock=False)
    if report.problems:
        raise ValueError("cannot freeze a benchmark with problems: " + "; ".join(report.problems[:5]))
    queries, labels = read_records(queries_path), read_records(labels_path)
    payload = {**_hashes(queries, labels), "queries": len(queries), "labels": len(labels)}
    lock.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return lock

