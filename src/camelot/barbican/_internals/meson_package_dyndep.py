# SPDX-FileCopyrightText: 2024 Ledger SAS
# SPDX-FileCopyrightText: 2025 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from argparse import ArgumentParser
import json
from pathlib import Path
import subprocess
import typing as T

from ..builder.ninja import (
    NinjaBuild,
    NinjaBuilderProtocol,
    NinjaFile,
    NinjaVariable,
)
from ..utils.environment import find_program


class NinjaDyndepBuilder(NinjaBuilderProtocol):
    def __init__(self) -> None:
        self.name = "dyndep"
        self._builds: list[NinjaBuild] = list()

    @classmethod
    def __ninja_variables__(cls):
        yield NinjaVariable(key="ninja_dyndep_version", value="1")

    def __ninja_builds__(self):
        yield from self._builds

    def add_dyndep(self, output, implicit, implicit_outputs) -> None:
        self._builds.append(
            NinjaBuild(
                outputs=[output],
                rule="dyndep",
                implicit=implicit,
                implicit_outputs=implicit_outputs,
                variables={"restat": "1"},
            )
        )


def _gen_ninja_dyndep_file(
    package: str, introspect: T.Any, stagingdir: Path, output: T.Any
) -> None:
    """Generate dyndep file.

    For compile target, build system files and sources file are needed as implicit inputs.
    Files to be installed are implicit output (resp. inputs) of compile (resp. install) command.
    ..notes: if inner build system files change, a reconfigure and rebuild is triggered.
    ..warning: some internal target are inputs for another target, thus remove those from implicit
    inputs.
    """
    compile_target = f"{package}_compile.stamp"
    install_target = f"{package}_install.stamp"

    buildsys_files = introspect["buildsystem_files"]

    sources = []
    filenames = []
    installed = introspect["installed"]

    for target in introspect["targets"]:
        if "filename" in target:
            filenames.extend(target["filename"])

        if "target_sources" in target:
            for target_sources in target["target_sources"]:
                if "sources" in target_sources:
                    sources.extend(target_sources["sources"])

    compile_implicit_outputs = set(filenames)
    compile_implicit_inputs = set(buildsys_files + sources)
    # remove generated file and/or internal target filename also used as input
    compile_implicit_inputs.difference_update(compile_implicit_outputs)

    install_implicit_inputs = set(installed.keys())

    install_implicit_outputs = set()
    for file in installed.values():
        _path = Path(file)
        # XXX:
        # Concatenation between 2 absolute path, makes no sense at all, if install path is
        # absolute, remove first part before destdir prefix concatenation.
        # i.e.:
        #  - leading "/" for Posix path
        #  - drive letter for Windows path
        if _path.is_absolute():
            _path = stagingdir.joinpath(*_path.parts[1:])
        else:
            _path = stagingdir.joinpath(_path)
        install_implicit_outputs.add(str(_path))

    builder = NinjaDyndepBuilder()
    builder.add_dyndep(compile_target, compile_implicit_inputs, compile_implicit_outputs)
    builder.add_dyndep(install_target, install_implicit_inputs, install_implicit_outputs)
    nf = NinjaFile([builder])
    nf.write(output)


def run_meson_package_dyndep(
    name: str, builddir: Path, stagingdir: Path, dyndep: Path, outfile: Path
) -> None:
    """Generate a ninja dynamic dependencies file for a meson package.

    This will populated implicit inputs and outputs of the given meson package
    using meson introspection.

    for a meson target, the following build rules are generated:
     - <name>_setup
     - <name>_compile[.stamp]
     - <name>_install[.stamp]

    This command generate a ninja dyndep file for compile and install target
    """
    meson = find_program("meson")
    cmdline = [meson, "introspect", "--all", "-i", str(builddir.resolve(strict=True))]
    proc_return = subprocess.run(cmdline, check=True, capture_output=True)
    package_introspection = json.loads(proc_return.stdout)

    _gen_ninja_dyndep_file(name, package_introspection, stagingdir, dyndep)
    with outfile.open("w") as out:
        out.write(json.dumps(package_introspection, indent=4))


def argument_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("--name", type=str, action="store", help="package name")
    parser.add_argument(
        "-j",
        "--json",
        type=Path,
        required=True,
        help="save meson package introspection data to file (json formatted)",
    )
    parser.add_argument("builddir", type=Path, help="package builddir")
    parser.add_argument("stagingdir", type=Path, help="package stagingdir")
    parser.add_argument("dyndep", type=Path, help="dynamic dependencies file")

    return parser


def run(argv: list[str]) -> None:
    """Execute meson package dyndep internal command."""
    args = argument_parser().parse_args(argv)
    run_meson_package_dyndep(args.name, args.builddir, args.stagingdir, args.dyndep, args.json)
