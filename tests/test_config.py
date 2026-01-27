# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import pytest
from collections.abc import Mapping
from importlib.resources import files

from jsonschema import Draft202012Validator
from referencing.exceptions import NoSuchResource

from camelot.barbican.config import REGISTRY


def uris() -> list[str]:
    """
    Local schemas uri are an URN with `barbican` namespace.

    A given schema <name>.json must have an id equals to `urn:barbican:<name>`
    An underscore in name is considered namespace and convert to colon in id string.

    e.g. scm_git.json -> `urn:barbican:scm:git`
    """
    uris = list()
    for f in files("camelot.barbican").joinpath("config/schemas").iterdir():
        name = f.stem
        uris.append(f"urn:barbican:{name.replace('_', ':')}")

    return uris


URIS = uris()


class TestSchema:
    def test_schema_registry_not_empty(self):
        assert len(REGISTRY) != 0

    @pytest.mark.parametrize("uri", URIS)
    def test_schema_name_id(self, uri):
        schema = REGISTRY.contents(uri)
        assert isinstance(schema, Mapping)

    def test_schema_bad_id(self):
        with pytest.raises(NoSuchResource):
            REGISTRY.contents("malformed_uri")

    @pytest.mark.parametrize("uri", URIS)
    def test_schema_validate(self, uri):
        """Json schema must be compliant w/ Draft 2020-12 schema specification."""
        schema = REGISTRY.contents(uri)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)
