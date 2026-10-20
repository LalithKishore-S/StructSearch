import pytest

from structsearch.config import load_config, validate_config


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
