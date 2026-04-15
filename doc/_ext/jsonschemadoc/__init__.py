# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Sphinx extension for auto-documenting TOML configuration from JSON Schemas.

This extension hooks into Sphinx autodoc to generate structured documentation
from JSON Schema files, using the ``camelot.barbican.config.REGISTRY`` for
schema resolution and cross-referencing.

Provides
--------
- ``autoschema`` directive: documents a single schema by URN
- ``schematoc`` directive: generates a table of contents for all schemas
- ``:schema:`` role: cross-references between schema sections
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment

__version__ = "0.1.0"

SCHEMA_TARGETS_KEY = "jsonschema_all_targets"


def get_schema_targets(
    env: BuildEnvironment,
) -> dict[str, tuple[str, str, str]]:
    """Return the schema cross-reference target mapping from the environment.

    Parameters
    ----------
    env : BuildEnvironment
        The Sphinx build environment.

    Returns
    -------
    dict[str, tuple[str, str, str]]
        Mapping of schema URN to ``(docname, node_id, display_title)``.
    """
    if not hasattr(env, SCHEMA_TARGETS_KEY):
        setattr(env, SCHEMA_TARGETS_KEY, {})
    return getattr(env, SCHEMA_TARGETS_KEY)


def setup(app: Sphinx) -> dict[str, typing.Any]:
    """Register the extension with Sphinx.

    Parameters
    ----------
    app : Sphinx
        The Sphinx application object.

    Returns
    -------
    dict[str, typing.Any]
        Extension metadata.
    """
    from .directives import SchemaTocDirective
    from .documenter import SchemaDocumenter
    from .roles import SchemaXRefRole, resolve_schema_xref

    app.add_config_value("jsonschema_registry_module", "camelot.barbican.config", "env")
    app.add_config_value("jsonschema_registry_attr", "REGISTRY", "env")

    app.add_autodocumenter(SchemaDocumenter)
    app.add_directive("schematoc", SchemaTocDirective)
    app.add_role("schema", SchemaXRefRole())

    app.connect("env-purge-doc", _purge_schema_targets)
    app.connect("env-merge-info", _merge_schema_targets)
    app.connect("missing-reference", resolve_schema_xref)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


def _purge_schema_targets(app: Sphinx, env: BuildEnvironment, docname: str) -> None:
    """Remove targets belonging to a purged document."""
    targets = get_schema_targets(env)
    to_remove = [uri for uri, (doc, _, _) in targets.items() if doc == docname]
    for uri in to_remove:
        del targets[uri]


def _merge_schema_targets(
    app: Sphinx,
    env: BuildEnvironment,
    docnames: list[str],
    other: BuildEnvironment,
) -> None:
    """Merge schema targets from parallel builds."""
    get_schema_targets(env).update(get_schema_targets(other))
