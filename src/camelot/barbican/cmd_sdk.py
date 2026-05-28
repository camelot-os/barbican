# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import tomllib
from argparse import ArgumentParser, Namespace
from pathlib import Path

from .config.validator import validate_sdk_config
from .console import console
from .rust import Rustup
from .utils import pathhelper
from .scm import scm_create


class SdkBuilder:
    def __init__(self, topdir: Path) -> None:
        self.path = pathhelper.ProjectPath(
            project_dir=topdir,
            output_dir=topdir / "output",
            config_filename=Path("sdk.toml"),
        )

        with self.path.config_full_path.open("rb") as f:
            self._toml = tomllib.load(f)
            validate_sdk_config(self._toml)

        self._gcc = scm_create(
            "", self.path.dl_dir, self.path.host_dir, self._toml["compiler"]["gcc"]
        )
        self._rustup = Rustup(self._toml["compiler"]["rustc"], self.path.host_dir)

    def build(self) -> None:
        console.title(f"Barbican SDK {self._toml['name']}")

        self.path.mkdirs()
        self.path.save()

        self._gcc.download()
        self._rustup.install(self.path.dl_dir)


def add_arguments(parser: ArgumentParser) -> None: ...


def run(args: Namespace) -> None:
    sdk = SdkBuilder(args.projectdir)
    sdk.build()
