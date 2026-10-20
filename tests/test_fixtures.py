import ast
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "sample_corpus"


def _units_from_file(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(CORPUS).as_posix()
    found = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                found.append(f"{rel}::{qual}")
                walk(child, qual + ".<locals>.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def test_manifest_matches_corpus():
    manifest = json.loads((FIXTURES / "expected_units.json").read_text())
    expected = set(manifest["units"])
    actual = set()
    for path in sorted(CORPUS.glob("*.py")):
        if path.name in manifest["unparseable_files"]:
            continue
        actual.update(_units_from_file(path))
    assert actual == expected


def test_broken_file_is_unparseable():
    import pytest

    with pytest.raises(SyntaxError):
        ast.parse((CORPUS / "broken_syntax.py").read_text())


def test_recursive_fixtures_present():
    src = (CORPUS / "trees.py").read_text()
    assert "inorder_traverse(node.left" in src and "factorial(n - 1)" in src
