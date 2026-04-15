# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

""":schema: cross-reference role for JSON Schema documentation."""

from __future__ import annotations

import typing

from docutils import nodes
from sphinx.roles import XRefRole
from sphinx.util import logging

if typing.TYPE_CHECKING:
    from sphinx.addnodes import pending_xref
    from sphinx.application import Sphinx
    from sphinx.builders import Builder
    from sphinx.environment import BuildEnvironment

logger = logging.getLogger(__name__)


class SchemaXRefRole(XRefRole):
    """Cross-reference role for linking to schema documentation sections.

    Usage::

        :schema:`urn:barbican:project`
        :schema:`project <urn:barbican:project>`
    """

    def process_link(
        self,
        env: BuildEnvironment,
        refnode: nodes.Element,
        has_explicit_title: bool,
        title: str,
        target: str,
    ) -> tuple[str, str]:
        """Process the role text into a display title and target URI.

        Parameters
        ----------
        env : BuildEnvironment
            The Sphinx build environment.
        refnode : nodes.Element
            The pending cross-reference node being constructed.
        has_explicit_title : bool
            Whether the user provided an explicit display title.
        title : str
            The display title (explicit or derived from target).
        target : str
            The raw cross-reference target text (the schema URN).

        Returns
        -------
        tuple[str, str]
            ``(display_title, target_uri)``.
        """
        refnode["refdomain"] = ""
        refnode["reftype"] = "schema"
        target = target.strip()
        if not has_explicit_title:
            # Derive a short display title from the URN
            if target.startswith("urn:barbican:"):
                title = target[len("urn:barbican:") :]
            else:
                title = target
        return title, target


def resolve_schema_xref(
    app: Sphinx,
    env: BuildEnvironment,
    node: pending_xref,
    contnode: nodes.Element,
) -> nodes.reference | None:
    """Resolve ``:schema:`` cross-references to their target documents.

    Connected to the ``missing-reference`` event in ``setup()``.

    Parameters
    ----------
    app : Sphinx
        The Sphinx application.
    env : BuildEnvironment
        The Sphinx build environment.
    node : pending_xref
        The unresolved pending cross-reference node.
    contnode : nodes.Element
        The content node (display text) inside the pending xref.

    Returns
    -------
    nodes.reference | None
        A resolved reference node, or ``None`` if not a schema xref.
    """
    if node.get("reftype") != "schema":
        return None

    from . import get_schema_targets

    target_uri = node.get("reftarget", "")
    targets = get_schema_targets(env)

    if target_uri not in targets:
        logger.warning(
            "undefined schema reference: %s",
            target_uri,
            location=node,
            type="jsonschema",
            subtype="ref",
        )
        return None

    docname, node_id, _title = targets[target_uri]
    builder: Builder = app.builder

    refuri = builder.get_relative_uri(node["refdoc"], docname)
    if node_id:
        refuri += "#" + node_id

    ref = nodes.reference("", "", internal=True, refuri=refuri)
    ref.append(contnode)
    return ref
