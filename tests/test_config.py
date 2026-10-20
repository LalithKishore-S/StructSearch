import pytest

from structsearch.config import load_config, validate_config

GOOD = {"top_k": 5, "weights": {"text": 1, "structural": 1, "graph": 1}}


def test_default_config_loads():
    cfg = load_config()
    assert cfg["top_k"] == 10
    assert set(cfg["weights"]) == {"text", "structural", "graph"}
    assert cfg["llm"]["enabled"] is False


def test_missing_weight_rejected():
    with pytest.raises(ValueError):
        validate_config({"top_k": 5, "weights": {"text": 1, "structural": 1}})


def test_negative_weight_rejected():
    with pytest.raises(ValueError):
        validate_config(
            {"top_k": 5, "weights": {"text": 1, "structural": -1, "graph": 0}}
        )


def test_bad_top_k_rejected():
    with pytest.raises(ValueError):
        validate_config(
            {"top_k": 0, "weights": {"text": 1, "structural": 1, "graph": 1}}
        )


@pytest.mark.parametrize(
    "bm25",
    [
        {"k1": 0},
        {"b": 1.5},
        {"field_weights": {"name": -1}},
    ],
)
def test_bad_bm25_section_rejected(bm25):
    with pytest.raises(ValueError):
        validate_config({**GOOD, "bm25": bm25})


def test_valid_bm25_section_accepted():
    validate_config({**GOOD, "bm25": {"k1": 1.2, "b": 0.5, "field_weights": {"name": 2}}})
