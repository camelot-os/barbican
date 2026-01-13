# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from argparse import ArgumentParser, Namespace

from .project import Project
from .utils import working_directory


def add_arguments(parser: ArgumentParser) -> None:
    pass


def run(args: Namespace) -> None:
    project = Project(args.projectdir)
    with working_directory(project.path.output_dir):
        project.setup()
