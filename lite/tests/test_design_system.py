"""Tests for Lite spec 6, objective 6.1: global design system.

Grep-style static checks over ``lite/app/server/static/style.css``
and ``lite/app/server/templates/base.html`` (plus a Jinja render of
the shell, no app, no network): every spec colour, radius, and shadow
is a CSS variable; templates use the variables, not literals; font
smoothing applies globally; no page uses Times New Roman or ``#000``
text; every button is 44px+ tall and defines every required state;
the layout shell provides the mobile tab bar (Map, Create, Saved,
Profile), the desktop sidebar, the top bar with gear link, and 16px
SafeArea padding as pure HTML+CSS.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2

TESTS_DIR = Path(__file__).resolve().parent
STATIC_DIR = TESTS_DIR.parent / "app" / "server" / "static"
TEMPLATES_DIR = TESTS_DIR.parent / "app" / "server" / "templates"

CSS_PATH = STATIC_DIR / "style.css"
BASE_PATH = TEMPLATES_DIR / "base.html"


def _css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _base() -> str:
    return BASE_PATH.read_text(encoding="utf-8")


def _root_block() -> str:
    css = _css()
    match = re.search(r":root\s*\{(.*?)\}", css, re.DOTALL)
    assert match is not None, "style.css defines no :root block"
    return match.group(1)


def _render_base() -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    return env.get_template("base.html").render({"title": "x"})


# Every spec colour must exist as a CSS variable value.
COLOUR_VARS = {
    "--color-primary": "#0F6BFF",
    "--color-secondary": "#00C98D",
    "--color-bg": "#F5F8FB",
    "--color-card": "#FFFFFF",
    "--color-border": "#E5E7EB",
    "--color-text": "#111827",
    "--color-text-secondary": "#6B7280",
    "--color-text-muted": "#9CA3AF",
}

RADIUS_VARS = {
    "--radius-card": "16px",
    "--radius-button": "12px",
    "--radius-pill": "24px",
}

SHADOW_VARS = {
    "--shadow-card": "0 2px 10px rgba(0, 0, 0, 0.06)",
    "--shadow-fab": "0 8px 24px rgba(15, 107, 255, 0.25)",
}

GRADIENT_VALUE = "linear-gradient(135deg, #0F6BFF 0%, #00C98D 100%)"

# Hex colour literal, ignoring HTML entities such as &#9881;.
HEX_RE = re.compile(r"(?<!&)#[0-9A-Fa-f]{3,8}\b")

FORBIDDEN_WORDS = ("accurate", "verified-result", "proves", "guarantees")


def test_stylesheet_defines_every_spec_colour_variable():
    root = _root_block()
    for var, value in COLOUR_VARS.items():
        assert re.search(
            re.escape(var) + r"\s*:\s*" + re.escape(value) + r"\s*;",
            root,
        ), f"{var} is not defined as {value} in :root"


def test_stylesheet_defines_gradient_variable():
    root = _root_block()
    assert "--gradient-primary" in root
    assert GRADIENT_VALUE in root


def test_stylesheet_defines_every_radius_variable():
    root = _root_block()
    for var, value in RADIUS_VARS.items():
        assert re.search(
            re.escape(var) + r"\s*:\s*" + re.escape(value) + r"\s*;",
            root,
        ), f"{var} is not defined as {value} in :root"


def test_stylesheet_defines_every_shadow_variable():
    root = _root_block()
    for var, value in SHADOW_VARS.items():
        assert re.search(
            re.escape(var) + r"\s*:\s*" + re.escape(value) + r"\s*;",
            root,
        ), f"{var} is not defined as {value} in :root"


def test_templates_use_variables_not_literals():
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        assert not HEX_RE.search(source), (
            f"{path.name} carries a literal colour instead of a "
            f"CSS variable: {HEX_RE.search(source).group(0)!r}"
        )


def test_base_shell_loads_stylesheet_and_uses_classes():
    source = _base()
    assert '<link rel="stylesheet" href="/static/style.css">' in source
    anchors = re.findall(r"<a\b[^>]*>", source)
    assert anchors, "base.html has no navigation links"
    for tag in anchors:
        assert 'class="' in tag, f"raw nav link without a class: {tag}"
        assert re.search(r"\bbtn\b|\btab-item\b|\bcard\b", tag), (
            f"nav link is not a button/card component: {tag}"
        )


def test_font_stack_and_global_smoothing():
    css = _css()
    assert "'Inter'" in css
    assert "-apple-system" in css
    assert "BlinkMacSystemFont" in css
    assert "Segoe UI" in css
    assert "-webkit-font-smoothing: antialiased" in css
    assert "-moz-osx-font-smoothing: grayscale" in css
    assert "text-rendering: optimizeLegibility" in css
    # Smoothing is global, not scoped to one widget.
    assert re.search(
        r"\*\s*\{[^}]*-webkit-font-smoothing", css, re.DOTALL
    ), "font smoothing is not applied globally"


def test_no_times_or_pure_black_text():
    css = _css()
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        assert "times" not in source.lower(), (
            f"{path.name} mentions Times"
        )
    assert "times" not in css.lower()
    assert "#000" not in css
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<!&)#[0O]00\b", source), path.name


def test_no_certainty_words_in_design_files():
    for text, name in ((_css(), "style.css"), (_base(), "base.html")):
        for word in FORBIDDEN_WORDS:
            assert word not in text.lower(), f"{name} uses {word!r}"


def test_buttons_min_height_and_all_states():
    css = _css()
    assert re.search(
        r"\.btn\s*\{[^}]*min-height:\s*44px", css, re.DOTALL
    ), ".btn base lacks min-height: 44px"
    assert re.search(
        r"\.btn:hover\s*\{[^}]*brightness\(0\.95\)", css, re.DOTALL
    ), ".btn lacks the hover state"
    assert re.search(
        r"\.btn:active\s*\{[^}]*scale\(0\.98\)[^}]*brightness\(0\.9\)",
        css, re.DOTALL,
    ), ".btn lacks the active state"
    assert re.search(
        r"\.btn:disabled[^{]*\{[^}]*opacity:\s*0\.5[^}]*"
        r"cursor:\s*not-allowed",
        css, re.DOTALL,
    ), ".btn lacks the disabled state"
    assert ".is-loading" in css, ".btn lacks the loading state"
    assert "@keyframes" in css, "loading spinner has no keyframes"
    for variant in (".btn-primary", ".btn-secondary", ".btn-tertiary"):
        assert variant in css, f"missing button variant {variant}"
    assert re.search(
        r"\.btn-primary\s*\{[^}]*var\(--gradient-primary\)", css, re.DOTALL
    ), ".btn-primary does not use the gradient variable"


def test_layout_shell_structure():
    source = _base()
    assert 'class="top-bar"' in source
    assert 'class="safe-area"' in source
    assert 'class="tab-bar"' in source
    assert 'class="sidebar"' in source
    assert 'href="/account"' in source, "header gear to /account missing"
    for target in ("/feed", "/map", "/upload", "/saved", "/account"):
        assert f'href="{target}"' in source, (
            f"tab bar missing link to {target}"
        )
    css = _css()
    assert re.search(
        r"\.top-bar\s*\{[^}]*height:\s*var\(--top-bar-h\)", css, re.DOTALL
    ), "top bar is not 64px via variable"
    assert re.search(
        r"\.tab-bar\s*\{[^}]*height:\s*var\(--tab-bar-h\)", css, re.DOTALL
    ), "tab bar is not 80px via variable"
    assert "--top-bar-h: 64px" in css
    assert "--tab-bar-h: 80px" in css
    assert "--safe-area-x: 16px" in css
    assert "--shell-max: 430px" in css
    # Cards: white, 16px radius, card shadow, 16px padding.
    assert re.search(
        r"\.card\s*\{[^}]*var\(--color-card\)", css, re.DOTALL
    )
    assert re.search(
        r"\.card\s*\{[^}]*var\(--radius-card\)", css, re.DOTALL
    )
    assert re.search(
        r"\.card\s*\{[^}]*var\(--shadow-card\)", css, re.DOTALL
    )
    assert re.search(
        r"\.card\s*\{[^}]*padding:\s*16px", css, re.DOTALL
    )


def test_shell_is_pure_html_css_without_scripts():
    source = _base()
    assert "<script" not in source.lower(), (
        "base.html must carry no script tags"
    )
    body = _render_base()
    assert "<script" not in body.lower()
    for target in ("/feed", "/map", "/upload", "/saved", "/account"):
        assert f'href="{target}"' in body
    # Desktop collapse rule: tab bar becomes a sidebar.
    assert "@media" in _css()
    assert ".sidebar" in _css()
