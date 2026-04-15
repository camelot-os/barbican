# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Jinja-to-RST rendering engine for JSON Schemas."""

from __future__ import annotations

import json
import os
import typing

from jinja2 import Environment, FileSystemLoader

if typing.TYPE_CHECKING:
    from referencing import Registry


def uri_to_node_id(uri: str) -> str:
    """Convert a schema URI to a valid docutils node ID.

    Parameters
    ----------
    uri : str
        Schema URN, e.g. ``urn:barbican:project``.

    Returns
    -------
    str
        Node ID string, e.g. ``schema-project``.
    """
    name = uri
    if name.startswith("urn:barbican:"):
        name = name[len("urn:barbican:"):]
    return "schema-" + name.replace(":", "-").replace("/", "-")


def derive_title(uri: str) -> str:
    """Derive a human-readable title from a schema URI.

    Parameters
    ----------
    uri : str
        Schema URN, e.g. ``urn:barbican:scm:git``.

    Returns
    -------
    str
        Display title, e.g. ``scm:git``.
    """
    if uri.startswith("urn:barbican:"):
        return uri[len("urn:barbican:"):]
    return uri


def discover_schema_uris(registry_module: str) -> list[str]:
    """Discover all schema URIs by scanning the schema package resources.

    Parameters
    ----------
    registry_module : str
        Dotted module path of the config package containing schemas.

    Returns
    -------
    list[str]
        Sorted list of schema ``$id`` URIs.
    """
    from importlib.resources import files

    schemas_dir = files(registry_module).joinpath("schemas")
    uris: list[str] = []
    for f in schemas_dir.iterdir():
        if str(f).endswith(".json"):
            contents = json.loads(f.read_text(encoding="utf-8"))
            if "$id" in contents:
                uris.append(contents["$id"])

    def _sort_key(uri: str) -> tuple[int, str]:
        name = derive_title(uri)
        return (name.count(":"), name)

    return sorted(uris, key=_sort_key)


class SchemaRenderer:
    """Renders JSON Schema metadata to RST text via Jinja templates."""

    def __init__(self) -> None:
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render(self, schema_uri: str, registry: Registry) -> list[str]:
        """Render a schema to RST text lines.

        Parameters
        ----------
        schema_uri : str
            The schema URN identifier.
        registry : Registry
            The JSON Schema registry for resolving references.

        Returns
        -------
        list[str]
            RST text lines.
        """
        schema = registry.contents(schema_uri)
        context = self._build_context(schema_uri, schema, registry)
        template = self._env.get_template("schema.rst.jinja")
        rst_text = template.render(**context)
        return _cleanup_rst(rst_text.splitlines())

    def _build_context(
        self,
        schema_uri: str,
        schema: dict[str, typing.Any],
        registry: Registry,
    ) -> dict[str, typing.Any]:
        """Build the Jinja template context dict from a schema."""
        title = derive_title(schema_uri)
        node_id = uri_to_node_id(schema_uri)

        properties = []
        required_fields = schema.get("required", [])
        for name, prop_schema in schema.get("properties", {}).items():
            properties.append(
                self._extract_property(
                    name, prop_schema, name in required_fields, registry
                )
            )

        pattern_properties = []
        for pattern, prop_schema in schema.get(
            "patternProperties", {}
        ).items():
            pattern_properties.append(
                self._extract_property(
                    pattern, prop_schema, False, registry, is_pattern=True
                )
            )

        one_of = None
        if "oneOf" in schema:
            one_of = []
            for option in schema["oneOf"]:
                one_of.append(
                    {
                        "required": option.get("required", []),
                        "description": option.get("description", ""),
                    }
                )

        return {
            "schema_uri": schema_uri,
            "node_id": node_id,
            "title": title,
            "underline": "-" * len(title),
            "description": schema.get("description", ""),
            "schema_type": schema.get("type", ""),
            "properties": properties,
            "pattern_properties": pattern_properties,
            "required_fields": required_fields,
            "additional_properties": schema.get("additionalProperties", True),
            "dependent_required": schema.get("dependentRequired", {}),
            "one_of": one_of,
        }

    def _extract_property(
        self,
        name: str,
        prop_schema: dict[str, typing.Any],
        required: bool,
        registry: Registry,
        *,
        is_pattern: bool = False,
    ) -> dict[str, typing.Any]:
        """Extract metadata for a single property."""
        ref = prop_schema.get("$ref")

        if ref:
            type_str = derive_title(ref.split("#")[0] if "#" in ref else ref)
        else:
            type_str = self._resolve_type(prop_schema)

        constraints: dict[str, typing.Any] = {}
        for key in (
            "format",
            "pattern",
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
        ):
            if key in prop_schema:
                constraints[key] = prop_schema[key]

        ref_base, ref_display = self._resolve_ref_parts(ref)

        nested = self._extract_nested_properties(prop_schema, registry)

        description_line = self._build_description_line(
            prop_schema.get("description", ""),
            prop_schema.get("default"),
            prop_schema.get("enum"),
            constraints,
        )

        return {
            "name": name,
            "type": type_str,
            "required": required,
            "description": prop_schema.get("description", ""),
            "description_line": description_line,
            "default": prop_schema.get("default"),
            "enum": prop_schema.get("enum"),
            "ref": ref,
            "ref_base": ref_base,
            "ref_display": ref_display,
            "constraints": constraints,
            "is_pattern": is_pattern,
            "nested_properties": nested,
        }

    def _resolve_type(self, prop_schema: dict[str, typing.Any]) -> str:
        """Map a JSON Schema type definition to a display string."""
        if "enum" in prop_schema:
            return "enum"
        if "oneOf" in prop_schema:
            types = []
            for option in prop_schema["oneOf"]:
                types.append(self._resolve_type(option))
            return " \\| ".join(types)

        schema_type = prop_schema.get("type", "any")
        if schema_type == "array":
            items = prop_schema.get("items", {})
            item_type = self._resolve_type(items)
            return f"array[{item_type}]"
        if schema_type == "object":
            additional = prop_schema.get("additionalProperties")
            if isinstance(additional, dict):
                val_type = self._resolve_type(additional)
                if val_type != "any":
                    return f"map[string, {val_type}]"
            return "object"
        return str(schema_type)

    def _resolve_ref_parts(
        self, ref: str | None
    ) -> tuple[str | None, str | None]:
        """Split a ``$ref`` URI into base URI and display name.

        Parameters
        ----------
        ref : str or None
            The ``$ref`` value, possibly with a JSON pointer fragment.

        Returns
        -------
        tuple[str | None, str | None]
            ``(base_uri, display_name)`` or ``(None, None)``.
        """
        if ref is None:
            return None, None
        if "#" in ref:
            base, fragment = ref.split("#", 1)
            display = derive_title(base)
            fragment_name = fragment.rstrip("/").rsplit("/", 1)[-1]
            if fragment_name:
                display = f"{display} ({fragment_name})"
            return base, display
        return ref, derive_title(ref)

    def _extract_nested_properties(
        self,
        prop_schema: dict[str, typing.Any],
        registry: Registry,
    ) -> list[dict[str, typing.Any]]:
        """Extract nested properties for inline object types."""
        if "properties" not in prop_schema or "$ref" in prop_schema:
            return []
        required = prop_schema.get("required", [])
        result = []
        for name, sub_schema in prop_schema["properties"].items():
            result.append(
                self._extract_property(
                    name, sub_schema, name in required, registry
                )
            )
        return result

    @staticmethod
    def _build_description_line(
        description: str,
        default: typing.Any,
        enum: list[str] | None,
        constraints: dict[str, typing.Any],
    ) -> str:
        """Combine description with inline constraint info for table cells."""
        parts: list[str] = []
        if description:
            parts.append(description)
        if default is not None:
            parts.append(f"*(default:* ``{default}`` *)*")
        if enum:
            enum_str = ", ".join(f"``{v}``" for v in enum)
            parts.append(f"One of: {enum_str}")
        for k, v in constraints.items():
            parts.append(f"*({k}: {v})*")
        return " ".join(parts) if parts else ""


def _cleanup_rst(lines: list[str]) -> list[str]:
    """Remove excessive blank lines from rendered RST.

    Parameters
    ----------
    lines : list[str]
        Raw RST lines from template rendering.

    Returns
    -------
    list[str]
        Cleaned RST lines with at most one consecutive blank line.
    """
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    return result
