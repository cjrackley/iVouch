"""Typed loader for ``lite/config.yaml`` (Lite spec 0.2).

Every threshold lives in ``lite/config.yaml``; this module holds only the
key names and their expected shapes, never threshold values. Unknown keys
and missing (absent or null) values raise :class:`ConfigError` with a
message naming the offending keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"

REQUIRED_KEYS = frozenset(
    {
        "max_upload_bytes",
        "allowed_types",
        "clip_model_id",
        "clip_device",
        "incident_prompts",
        "severity_prompts",
        "low_confidence_below",
        "claim_mismatch_below",
        "phash_max_distance",
        "duplicate_window",
        "policy_mock_hashes_path",
        "min_age",
        "jwt_access_minutes",
        "upload_cap_per_account",
        "login_ratelimit_max_attempts",
        "login_ratelimit_window_seconds",
        "jitter_min_m",
        "jitter_max_m",
        "console_mail_dir",
        "location_required",
    }
)

_INT_KEYS = frozenset(
    {
        "max_upload_bytes",
        "phash_max_distance",
        "duplicate_window",
        "min_age",
        "jwt_access_minutes",
        "upload_cap_per_account",
        "login_ratelimit_max_attempts",
        "login_ratelimit_window_seconds",
        "jitter_min_m",
        "jitter_max_m",
    }
)

_FLOAT_KEYS = frozenset({"low_confidence_below", "claim_mismatch_below"})

_STR_KEYS = frozenset(
    {
        "clip_model_id",
        "clip_device",
        "policy_mock_hashes_path",
        "console_mail_dir",
    }
)

_LIST_KEYS = frozenset({"allowed_types"})

_MAPPING_KEYS = frozenset({"incident_prompts", "severity_prompts"})


class ConfigError(ValueError):
    """Raised when ``lite/config.yaml`` has unknown keys, missing values,
    or values of the wrong shape."""


@dataclass(frozen=True)
class LiteConfig:
    max_upload_bytes: int
    allowed_types: list
    clip_model_id: str
    clip_device: str
    incident_prompts: dict
    severity_prompts: dict
    low_confidence_below: float
    claim_mismatch_below: float
    phash_max_distance: int
    duplicate_window: int
    policy_mock_hashes_path: str
    min_age: int
    jwt_access_minutes: int
    upload_cap_per_account: int
    login_ratelimit_max_attempts: int
    login_ratelimit_window_seconds: int
    jitter_min_m: int
    jitter_max_m: int
    console_mail_dir: str
    location_required: bool


def _is_int(value) -> bool:
    return type(value) is int


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and type(value) is not bool


def _check_shape(key: str, value) -> None:
    if key in _INT_KEYS:
        if not _is_int(value):
            raise ConfigError(
                f"config key {key!r} must be an integer, got {type(value).__name__}"
            )
    elif key in _FLOAT_KEYS:
        if not _is_number(value):
            raise ConfigError(
                f"config key {key!r} must be a number, got {type(value).__name__}"
            )
    elif key in _STR_KEYS:
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"config key {key!r} must be a non-empty string")
    elif key in _LIST_KEYS:
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) for item in value)
        ):
            raise ConfigError(
                f"config key {key!r} must be a non-empty list of strings"
            )
    elif key in _MAPPING_KEYS:
        if (
            not isinstance(value, dict)
            or not value
            or any(
                not isinstance(prompt_key, str) or not isinstance(prompt, str)
                for prompt_key, prompt in value.items()
            )
        ):
            raise ConfigError(
                f"config key {key!r} must be a non-empty mapping of strings to strings"
            )
    elif key == "location_required":
        if type(value) is not bool:
            raise ConfigError(
                "config key 'location_required' must be a boolean, "
                f"got {type(value).__name__}"
            )


def _validate(data) -> LiteConfig:
    if not isinstance(data, dict):
        raise ConfigError(
            "config must be a mapping of key-value pairs, "
            f"got {type(data).__name__}"
        )
    unknown = sorted(set(data) - set(REQUIRED_KEYS))
    if unknown:
        raise ConfigError(f"unknown config key(s): {', '.join(unknown)}")
    missing = sorted(key for key in REQUIRED_KEYS if data.get(key) is None)
    if missing:
        raise ConfigError(f"missing config value(s) for key(s): {', '.join(missing)}")
    for key in sorted(REQUIRED_KEYS):
        _check_shape(key, data[key])
    return LiteConfig(**{key: data[key] for key in sorted(REQUIRED_KEYS)})


def load_config(path=None) -> LiteConfig:
    """Load and validate the Lite config file.

    ``path`` defaults to the shipped ``lite/config.yaml``. Raises
    :class:`ConfigError` on unknown keys, missing values, or wrong shapes,
    and propagates I/O and YAML parse errors unchanged.
    """
    resolved = Path(path) if path is not None else CONFIG_PATH
    raw = resolved.read_text(encoding="utf-8")
    return _validate(yaml.safe_load(raw))
