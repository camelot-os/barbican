# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from argparse import ArgumentParser, Namespace

from .project import Project


def add_arguments(parser: ArgumentParser) -> None:
    pass


def run(args: Namespace) -> None:
    project = Project(args.projectdir)
    project.download()
