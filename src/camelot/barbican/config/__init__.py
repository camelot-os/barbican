# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from referencing.jsonschema import EMPTY_REGISTRY as _EMPTY_REGISTRY

from ._schemas import _schemas

REGISTRY = (_schemas() @ _EMPTY_REGISTRY).crawl()
__all__ = ["REGISTRY"]
