# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Sphinx extension to fix double-anchor URIs in singlehtml-based builders.

Sphinx 9.x deprecated ``SingleFileHTMLBuilder.fix_refuris`` which previously
resolved double-``#`` references (e.g. ``#document-page#anchor``) produced when
all documents are merged into a single page.  Without it, downstream consumers
such as WeasyPrint see invalid fragment identifiers and emit thousands of
*"No anchor"* / *"Anchor defined twice"* errors.

This extension restores the fix in two phases:

1. **doctree-resolved** walk the merged doctree and strip the
   ``#document-…`` prefix so only the real anchor remains.  This handles
   cross-references in the main document body.
2. **builder-inited** monkey-patch the simplepdf builder's
   ``_toctree_fix`` HTML post-processor to also strip double-``#`` hrefs
   produced by the sidebar TOC (which is generated outside the doctree).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from docutils import nodes

if TYPE_CHECKING:
    from sphinx.application import Sphinx

_DOUBLE_HASH_RE = re.compile(r'href="#[^"]*?(#[^"]*)"')


def _fix_refuris(app: Sphinx, doctree: nodes.document, docname: str) -> None:
    """Fix double-# refuris in the merged doctree."""
    if app.builder.name not in {"singlehtml", "simplepdf"}:
        return

    for refnode in doctree.findall(nodes.reference):
        refuri: str | None = refnode.get("refuri")
        if refuri is None:
            continue

        first_hash = refuri.find("#")
        if first_hash < 0:
            continue

        second_hash = refuri.find("#", first_hash + 1)
        if second_hash >= 0:
            refnode["refuri"] = refuri[second_hash:]


def _patch_builder(app: Sphinx) -> None:
    """Wrap the simplepdf builder's HTML post-processor to also fix hrefs."""
    if app.builder.name != "simplepdf":
        return

    original_toctree_fix = app.builder._toctree_fix  # type: ignore[attr-defined]

    def _patched_toctree_fix(html: str) -> str:
        html = _DOUBLE_HASH_RE.sub(r'href="\1"', html)
        return original_toctree_fix(html)

    app.builder._toctree_fix = _patched_toctree_fix  # type: ignore[attr-defined]


def setup(app: Sphinx) -> dict[str, Any]:
    app.connect("doctree-resolved", _fix_refuris, priority=900)
    app.connect("builder-inited", _patch_builder)

    return {
        "version": "1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
