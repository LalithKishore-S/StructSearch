from structsearch.schemas import (
    AstRecord,
    CodeUnit,
    EvaluationLabel,
    RankedResult,
    TextRecord,
)


def test_code_unit_defaults_and_roundtrip():
    unit = CodeUnit(
        unit_id="a.py::f",
        file_path="a.py",
        start_line=1,
        end_line=2,
        name="f",
        source_text="def f(): pass",
    )
    assert unit.language == "python"
    assert unit.parse_status == "ok"
    assert CodeUnit.from_dict(unit.to_dict()) == unit


def test_ranked_result_graph_score_is_optional():
    result = RankedResult(query_id="q1", unit_id="a.py::f")
    assert result.graph_score is None
    assert result.evidence == []
    assert RankedResult.from_dict(result.to_dict()) == result


def test_from_dict_ignores_unknown_keys():
    rec = TextRecord.from_dict({"unit_id": "u", "name": "n", "extra": 1})
    assert rec.unit_id == "u" and rec.identifiers == []


def test_ast_record_and_label():
    ast_rec = AstRecord(unit_id="u", features={"if": 2.0}, extraction_version="1")
    assert AstRecord.from_dict(ast_rec.to_dict()).features["if"] == 2.0
    label = EvaluationLabel("q1", "u", 1, "lexical", "dev")
    assert label.split == "dev"


def test_mutable_defaults_not_shared():
    a = RankedResult(query_id="q", unit_id="u1")
    b = RankedResult(query_id="q", unit_id="u2")
    a.evidence.append("x")
    assert b.evidence == []
