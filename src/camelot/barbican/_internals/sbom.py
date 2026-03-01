# SPDX-FileCopyrightText: 2025 H2Lab OSS Team
# SPDX-License-Identifier: Apache-2.0


from argparse import ArgumentParser
from spdx_tools import spdx

from ..console import console

def run_spdx_forge():
    pass

def argument_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument(
        "-f",
        "--format",
        action="store",
        type=str,
        default="json",
        help="Set the SBOM output format to generate (json, cpe)",
    )
    parser.add_argument(
        "-o",
        "--output",
        action="store",
        type=str,
        default="sbom.json",
        help="SBOM file, default to sbom.json"
    )

    return parser
