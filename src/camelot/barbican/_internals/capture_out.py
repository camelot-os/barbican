# SPDX-FileCopyrightText: 2024 Ledger SAS
# SPDX-FileCopyrightText: 2025 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Capture stdout internal command.

Execute a random command and capture stdout to file
"""


from argparse import ArgumentParser, REMAINDER
from pathlib import Path
import subprocess


def run_capture_stdout(cmdline: list[str], output: Path) -> None:
    proc_return = subprocess.run(cmdline, check=True, capture_output=True)
    with output.open("w") as fout:
        fout.write(proc_return.stdout.decode("utf-8"))


def argument_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("out", type=Path, help="output filename")
    parser.add_argument("cmdline", type=str, nargs=REMAINDER, help="command line")

    return parser


def run(argv: list[str]) -> None:
    """Execute capture stdout internal command."""
    args = argument_parser().parse_args(argv)
    run_capture_stdout(args.cmdline, args.out)
