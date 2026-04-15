# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""SchemaDocumenter — autodoc integration for JSON Schema documentation."""

from __future__ import annotations

import importlib
import typing

from sphinx.ext.autodoc import Documenter
from sphinx.util import logging

from . import get_schema_targets
from .renderer import SchemaRenderer, derive_title, uri_to_node_id

if typing.TYPE_CHECKING:
    from referencing import Registry

logger = logging.getLogger(__name__)


class SchemaDocumenter(Documenter):
    """Autodoc Documenter subclass for JSON Schema objects.

    Generates structured RST documentation for a single JSON schema
    identified by its URN.  Registered via ``app.add_autodocumenter``,
    which creates the ``autoschema`` directive automatically.
    """

    objtype = "schema"
    content_indent = ""

    option_spec: typing.ClassVar[dict[str, typing.Any]] = {}

    # Instance attributes populated during processing
    schema_uri: str
    schema: dict[str, typing.Any]
    _registry: Registry

    @classmethod
    def can_document_member(
        cls,
        member: typing.Any,
        membername: str,
        isattr: bool,
        parent: typing.Any,
    ) -> bool:
        """Return False — schemas are always top-level, never members."""
        return False

    def parse_name(self) -> bool:
        """Extract the schema URN from the directive argument.

        Returns
        -------
        bool
            Always ``True`` if a non-empty URN is provided.
        """
        self.schema_uri = self.name.strip()
        if not self.schema_uri:
            logger.warning("autoschema requires a schema URN argument")
            return False
        self.modname = ""
        self.objpath = [self.schema_uri]
        self.fullname = self.schema_uri
        self.args = ""
        self.retann = ""
        return True

    def import_object(self, raiseerror: bool = False) -> bool:
        """Load the JSON Schema from the configured registry.

        Parameters
        ----------
        raiseerror : bool
            Ignored; kept for compatibility with the base class signature.

        Returns
        -------
        bool
            ``True`` if the schema was loaded successfully.
        """
        try:
            module_name = self.env.config.jsonschema_registry_module
            attr_name = self.env.config.jsonschema_registry_attr
            mod = importlib.import_module(module_name)
            self._registry = getattr(mod, attr_name)
            self.schema = self._registry.contents(self.schema_uri)
            self.object = self.schema
            self.object_name = self.schema_uri
            return True
        except Exception as exc:
            logger.warning(
                "failed to load schema %s: %s",
                self.schema_uri,
                exc,
                type="jsonschema",
                subtype="import",
            )
            return False

    def get_sourcename(self) -> str:
        """Return a descriptive source name for error messages."""
        return f"schema:{self.schema_uri}"

    def format_name(self) -> str:
        """Return the display name of the schema."""
        return derive_title(self.schema_uri)

    def format_signature(self, **kwargs: typing.Any) -> str:
        """Return an empty string — schemas have no signature."""
        return ""

    def generate(
        self,
        more_content: typing.Any | None = None,
        real_modname: str | None = None,
        check_module: bool = False,
        all_members: bool = False,
    ) -> None:
        """Generate RST content for the schema.

        Overrides the default ``Documenter.generate`` entirely because the
        autodoc base implementation expects Python objects with modules and
        signatures.
        """
        if not self.parse_name():
            return
        if not self.import_object():
            return

        sourcename = self.get_sourcename()
        renderer = SchemaRenderer()
        lines = renderer.render(self.schema_uri, self._registry)

        for line in lines:
            self.add_line(line, sourcename)

        if more_content:
            self.add_line("", sourcename)
            for line, src in zip(more_content.data, more_content.items):
                self.add_line(line, src[0], src[1])

        # Register cross-reference target
        node_id = uri_to_node_id(self.schema_uri)
        title = derive_title(self.schema_uri)
        targets = get_schema_targets(self.env)
        targets[self.schema_uri] = (self.env.docname, node_id, title)
