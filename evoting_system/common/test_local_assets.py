"""
NFR (offline demo / no third-party requests): every script, stylesheet and font is
served from this project's own static files, never from another host.

- No template may load a <script> or <link> resource from an absolute or
  protocol-relative URL (http://, https://, //). Ordinary <a href> links are allowed.
- No static CSS file may pull a font or stylesheet from another host (url(...) or @import).
- The vendored files exist, every {% static %} path the templates use resolves, and
  every font file named in the vendored font CSS is present.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders

TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
STATIC_DIR = Path(settings.BASE_DIR) / "static"
VENDOR = STATIC_DIR / "vendor"
TAILWIND = VENDOR / "tailwindcss" / "tailwindcss-3.4.17-forms-0.5.10-container-queries-0.1.1.js"
FONT_CSS = VENDOR / "fonts" / "fonts.css"
THIRD_PARTY = Path(settings.BASE_DIR) / "THIRD_PARTY.md"

RESOURCE_TAG = re.compile(r"""<(script|link)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["'][^>]*>""", re.IGNORECASE)
EXTERNAL = re.compile(r"""^\s*(?:https?:)?//""", re.IGNORECASE)
CSS_EXTERNAL = re.compile(r"""(?:url\(\s*["']?|@import\s+["'])\s*((?:https?:)?//[^"')\s]+)""", re.IGNORECASE)
STATIC_TAG = re.compile(r"""\{%\s*static\s+["']([^"']+)["']\s*%\}""")


def _templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def test_no_template_or_css_loads_a_resource_from_another_host():
    offenders = []
    for path in _templates():
        for tag, url in RESOURCE_TAG.findall(path.read_text(encoding="utf-8")):
            if EXTERNAL.match(url):
                offenders.append(f"{path.relative_to(TEMPLATES_DIR)}: <{tag}> {url}")
    for css in STATIC_DIR.rglob("*.css"):
        for url in CSS_EXTERNAL.findall(css.read_text(encoding="utf-8")):
            offenders.append(f"{css.relative_to(STATIC_DIR)}: {url}")
    assert offenders == [], "external resources:\n" + "\n".join(offenders)


def test_vendored_assets_exist_and_every_static_reference_resolves():
    for f in (TAILWIND, FONT_CSS, THIRD_PARTY):
        assert f.is_file() and f.stat().st_size > 0, f"missing: {f}"
    font_files = re.findall(r"""url\(["']?([^"')]+\.woff2)["']?\)""", FONT_CSS.read_text(encoding="utf-8"))
    assert font_files, "fonts.css names no woff2 file"
    for name in font_files:
        assert (FONT_CSS.parent / name).is_file(), f"fonts.css names a missing file: {name}"
    unresolved = sorted({ref for path in _templates() for ref in STATIC_TAG.findall(path.read_text(encoding="utf-8"))
                         if finders.find(ref) is None})
    assert unresolved == [], f"{{% static %}} paths that do not resolve: {unresolved}"
