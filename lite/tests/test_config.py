"""Config loader tests for Lite spec 0, objective 0.2.

The loader must reject unknown keys and missing values with a clear
error, and must load the shipped ``lite/config.yaml`` cleanly. Negative
cases build on a copy of the shipped config so they track the real key
set; all threshold values are read via the loader, never re-typed here.
"""

from pathlib import Path

import pytest
import yaml

from lite.app.config import ConfigError, LiteConfig, load_config

LITE_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = LITE_ROOT / "config.yaml"


def _shipped_data():
    return yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))


def _write_config(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_loads_shipped_config_cleanly():
    cfg = load_config(SHIPPED_CONFIG)
    assert isinstance(cfg, LiteConfig)
    assert cfg.location_required is True
    assert cfg.allowed_types == ["jpeg", "png"]
    assert set(cfg.incident_prompts) == {
        "car_crash",
        "fire",
        "flood",
        "storm_damage",
        "earthquake_damage",
        "none",
    }
    assert set(cfg.severity_prompts) == {"minor", "moderate", "severe"}


def test_rejects_unknown_keys(tmp_path):
    data = _shipped_data()
    data["not_a_real_key"] = "oops"
    with pytest.raises(ConfigError, match="unknown.*not_a_real_key"):
        load_config(_write_config(tmp_path, data))


def test_rejects_missing_values(tmp_path):
    data = _shipped_data()
    del data["max_upload_bytes"]
    data["clip_device"] = None
    with pytest.raises(ConfigError, match="missing"):
        load_config(_write_config(tmp_path, data))
    with pytest.raises(ConfigError, match="max_upload_bytes"):
        load_config(_write_config(tmp_path, data))
