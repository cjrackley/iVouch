"""Tests for Lite spec 7, objective 7.1: probability display strings.

Socket-free by design (direct unit checks, template-source grep, and
direct Jinja renders with fabricated contexts -- no app, no encoder,
no network):

- ``pages._pct`` / ``pages._pct_map`` format one-decimal percents and
  never emit raw decimals or exponent notation.
- Report, shared, and review templates render the percent strings and
  do no probability arithmetic themselves.
- Display logic lives only in ``pages.py``: ``api.py`` payloads carry
  no percent keys, so JSON retrieval bodies are byte-identical.
- Rendered report/shared/review pages show ``XX.X%`` strings and no
  raw probability decimals.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2

from lite.app.server import pages as pages_module

TESTS_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = TESTS_DIR.parent / "app" / "server" / "templates"
API_PATH = TESTS_DIR.parent / "app" / "server" / "api.py"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)

PCT_RE = re.compile(r"^\d+\.\d%$")


def _report_context() -> dict:
    report = {
        "report_id": 7,
        "needs_review": False,
        "photo_url": "/api/photos/7",
        "top_severity": "moderate",
        "verdict": "likely-real",
        "confidence": 0.91116,
        "display_lat": 51.5,
        "display_lng": -0.12,
        "claim_text": "a photo of a street",
        "created_at": "2026-01-01T00:00:00",
        "incident_probs": {"fire": 0.91116, "flood": 9.566271774757038e-06},
        "severity_probs": {"moderate": 0.62, "mild": 0.38},
        "reasons": ["mock reason one"],
    }
    return {
        "title": "Report 7",
        "report": report,
        "top_incident": "fire",
        "top_incident_prob": 0.91116,
        "top_incident_pct": pages_module._pct(0.91116),
        "confidence_pct": pages_module._pct(report["confidence"]),
        "incident_pct": pages_module._pct_map(report["incident_probs"]),
        "severity_pct": pages_module._pct_map(report["severity_probs"]),
        "category": None,
        "category_label": None,
        "correction": None,
        "is_owner": True,
        "is_saved": False,
        "vouched": False,
        "vouch_count": 0,
        "vouches": [],
        "comments": [],
        "error": None,
    }


def test_pct_formats_one_decimal_percent():
    assert pages_module._pct(0.91) == "91.0%"
    assert pages_module._pct(0.91116) == "91.1%"
    assert pages_module._pct(1.0) == "100.0%"
    assert pages_module._pct(0.0) == "0.0%"
    assert PCT_RE.match(pages_module._pct(0.12345)) is not None


def test_pct_never_emits_exponent_notation():
    tiny = pages_module._pct(9.566271774757038e-06)
    assert tiny == "0.0%"
    assert "e" not in tiny.lower()


def test_pct_handles_missing_or_bad_values():
    assert pages_module._pct(None) == "0.0%"
    assert pages_module._pct("not-a-number") == "0.0%"
    assert pages_module._pct_map(None) == {}
    assert pages_module._pct_map("nope") == {}


def test_pct_map_covers_every_label():
    probs = {"fire": 0.91116, "flood": 0.2, "none": 0.0}
    mapped = pages_module._pct_map(probs)
    assert set(mapped) == set(probs)
    for value in mapped.values():
        assert PCT_RE.match(value) is not None, value


def test_display_logic_lives_only_in_pages():
    api_source = API_PATH.read_text(encoding="utf-8")
    assert "_pct" not in api_source
    assert "confidence_pct" not in api_source
    assert "incident_pct" not in api_source


def _template_source(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def test_templates_render_strings_not_raw_values():
    for name in ("report.html", "shared.html", "review_detail.html", "review.html"):
        source = _template_source(name)
        assert "top_incident_prob" not in source, name
        assert "report.confidence" not in source, name
        assert "item.confidence" not in source or "confidence_pct" in source, name
    for name in ("report.html", "review_detail.html"):
        assert "{{ prob }}" not in _template_source(name), name


def test_templates_do_no_probability_arithmetic():
    for name in ("report.html", "shared.html", "review_detail.html", "review.html"):
        source = _template_source(name)
        assert "* 100" not in source, name
        assert "|float" not in source, name


def test_report_page_shows_percents_not_raw_decimals():
    body = _env.get_template("report.html").render(_report_context())
    assert "91.1%" in body
    assert "0.91116" not in body
    assert "9.566271774757038e-06" not in body
    assert "e-06" not in body.lower()


def test_shared_page_shows_percents_not_raw_decimals():
    body = _env.get_template("shared.html").render(_report_context())
    assert "91.1%" in body
    assert "0.91116" not in body


def test_review_detail_page_shows_percents_not_raw_decimals():
    ctx = _report_context()
    ctx.update(
        {
            "needs_review": False,
            "provenance": {},
            "duplicates": [],
            "history": [],
            "incident_labels": ["fire", "flood"],
            "severity_labels": ["mild", "moderate"],
            "csrf_token": "csrf",
        }
    )
    body = _env.get_template("review_detail.html").render(ctx)
    assert "91.1%" in body
    assert "0.91116" not in body
    assert "9.566271774757038e-06" not in body


def test_review_queue_shows_percent_not_raw_decimal():
    body = _env.get_template("review.html").render(
        {
            "title": "Review queue",
            "reports": [
                {
                    "report_id": 7,
                    "verdict": "needs-review",
                    "confidence": 0.91116,
                    "confidence_pct": "91.1%",
                    "needs_review": True,
                }
            ],
        }
    )
    assert "91.1%" in body
    assert "0.91116" not in body
