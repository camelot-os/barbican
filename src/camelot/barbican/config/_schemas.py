# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import json
from importlib.resources import files

from referencing import Resource


def _schemas():
    for f in files(__package__).joinpath("schemas").iterdir():
        contents = json.loads(f.read_text(encoding="utf-8"))
        yield Resource.from_contents(contents)
