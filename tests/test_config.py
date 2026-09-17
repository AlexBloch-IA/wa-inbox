import json

import pytest

from wa_inbox import config


def test_defaults_when_no_file(tmp_path):
    cfg = config.load(tmp_path / "missing.json")
    assert cfg["default_list"] == "Inbox" and cfg["language"] == "en" and cfg["batch_size"] == 50


def test_user_values_override_and_tilde_expands(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"default_list": "Boîte", "images_dir": "~/shots", "batch_size": 10}))
    cfg = config.load(p)
    assert cfg["default_list"] == "Boîte" and cfg["batch_size"] == 10
    assert cfg["images_dir"].startswith("/") and "~" not in cfg["images_dir"]


def test_unknown_key_is_rejected(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"defaultList": "Inbox"}))
    with pytest.raises(ValueError, match="unknown config keys"):
        config.load(p)


@pytest.mark.parametrize("bad", [{"active_hours": 7}, {"active_hours": [7]}, {"language": "de"}])
def test_invalid_values_are_rejected(tmp_path, bad):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        config.load(p)


def test_write_default_is_loadable(tmp_path):
    p = config.write_default(tmp_path / "config.json")
    assert config.load(p)["default_list"] == config.DEFAULTS["default_list"]


def test_both_prompt_files_exist():
    for lang in ("en", "fr"):
        assert config.prompt_path({"language": lang}).exists()
