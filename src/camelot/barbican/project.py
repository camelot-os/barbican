# SPDX-FileCopyrightText: 2025 - 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import tomllib

from collections.abc import Iterator
from pathlib import Path, PurePath

from .console import console
from .logger import logger
from .config.validator import validate_project_config
from .package import Package, create_package
from .package.kernel import Kernel
from .package.runtime import Runtime
from .package.meson import Meson
from .package.cargo import Cargo
from .package import cargo

from .builder.ninja import NinjaBuild, NinjaRule, NinjaVariable, NinjaFile
from .utils import pathhelper
from .utils.environment import find_program


class Project:
    def __init__(self, project_dir: Path) -> None:
        self.path = pathhelper.ProjectPath(
            project_dir=project_dir,
            output_dir=project_dir / "output",
        )

        # XXX:
        #  Even if toml is a text format, the file must be opened as binary file
        with self.path.config_full_path.open("rb") as f:
            self._toml = tomllib.load(f)
            validate_project_config(self._toml)

        console.title(f"Barbican project '{self.name}'")

        self.path.mkdirs()
        self.path.save()

        self._packages: list[Meson | Cargo] = []  # list of ABCpackage
        self._ninja_filepath = self.path.build_dir / "build.ninja"

        # XXX:
        # we assumed that the order in package list is fixed
        #  - 0: kernel
        #  - 1: libshield
        #  - 2..n: apps
        # There is only meson packages
        #
        # This will be, likely, false for next devel step.

        # Instantiate Sentry kernel
        self._kernel = Kernel(self, self._toml)
        self._packages.append(self._kernel._package)

        # Instantiate libshield
        self._runtime = Runtime(self, self._toml)
        self._packages.append(self._runtime._package)

        if "application" in self._toml:
            self._noapp = False
            for app, node in self._toml["application"].items():
                self._packages.append(
                    create_package(app, self, node, Package.Type.Application)  # type: ignore
                )
        else:
            self._noapp = True

        # XXX: need sdk support
        self._crossfile = self.path.project_dir / self._toml["crossfile"]
        self._dts = self.path.project_dir / self._toml["dts"]
        self._dts_include_dirs = []
        for p in self._packages:
            self._dts_include_dirs.extend(p.dts_include_dirs)

        self._default_target: list[str | Path] = []

    @classmethod
    def __ninja_variables__(cls) -> Iterator[NinjaVariable]:
        yield from [
            NinjaVariable(key="barbican", value=find_program("barbican")),
        ]

    @classmethod
    def __ninja_rules__(cls) -> Iterator[NinjaRule]:
        yield from [
            NinjaRule(
                name="reconfigure",
                command="$barbican setup $projectdir",
                generator=True,
                description="Reconfigure barbican project",
                pool="console",
            ),
            NinjaRule(
                name="internal",
                command="$barbican --internal $cmd $args",
                description="$cmd (internal)",
            ),
        ]

    def __ninja_builds__(self) -> Iterator[NinjaBuild]:
        yield from self._config_targets
        if not self._noapp:
            yield from self._integration_targets

    @property
    def apps(self) -> list[Package]:
        return [p for p in self._packages if p.is_application]

    @property
    def name(self) -> str:
        return self._toml["name"]

    @property
    def _config_targets(self) -> list[NinjaBuild]:
        path_target = NinjaBuild(
            outputs=[self.path.config_full_path, self.path.save_full_path],
            rule="phony",
        )
        reconfigure = NinjaBuild(
            outputs=[self._ninja_filepath],
            rule="reconfigure",
            variables={"projectdir": self.path.project_dir},
            implicit=[path_target],
        )
        return [path_target, reconfigure]

    def _dummy_layout_target(self, out: Path) -> NinjaBuild:
        return NinjaBuild(
            outputs=[out],
            rule="internal",
            variables={
                "cmd": "gen_memory_layout",
                "args": f"--dummy {out}",
                "description": "Dummy memory layout",
            },
        )

    def _firmware_layout_target(self, out: Path, apps: list[NinjaBuild]) -> NinjaBuild:
        # XXX: use sdk and dyndep for dts
        dts = self.path.sysroot_data_dir / f"{Path(self._toml['dts']).name}.pp"
        implicit: list[str | NinjaBuild] = []
        implicit.extend(apps)
        implicit.append(self._kernel._package.as_dependency)
        elves: list[str | PurePath] = []
        elves.extend(self._kernel._package.installed_targets)
        for app in apps:
            elves.extend(app.outputs)
        opts = " ".join(f"-l {elf}" for elf in elves)

        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=implicit,
            variables={
                "cmd": "gen_memory_layout",
                "args": f"{out} --dts {dts} {opts}",
                "description": "Firmware layout",
            },
        )

    def _gen_ldscript_target(
        self, name: str, out: Path, layout: NinjaBuild, package: Package | None = None
    ) -> NinjaBuild:

        # XXX: hardcoded in early steps, need sdk w/ src and meson metadata support
        # This implicit input must be added as dep using dyndep once supported.
        template = self.path.sysroot_data_dir / "shield" / "linkerscript.ld.in"
        implicit: list[NinjaBuild | str] = []
        implicit.extend([layout, self._runtime._package.as_dependency])
        if package:
            implicit.append(package.as_dependency)

        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=implicit,
            variables={
                "cmd": "gen_ldscript",
                "args": f"--name {name} {template} {layout.outputs[0]} {out}",
                "description": f"generating {name} linker script",
            },
        )

    def _relink_target(
        self, package: Package, inp: Path, out: Path, ldscript: NinjaBuild
    ) -> NinjaBuild:
        kernel_introspect = "kernel_introspect.json"  # XXX

        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=[kernel_introspect, ldscript, package.as_dependency],
            variables={
                "cmd": "relink_elf",
                "args": f"-l {ldscript.outputs[0]} -m {kernel_introspect} {out} {inp}",
                "description": f"{package.name}: linking {out}",
            },
        )

    def _objcopy(self, inp: NinjaBuild, out: Path, format: str) -> NinjaBuild:
        kernel_introspect = "kernel_introspect.json"  # XXX

        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=[kernel_introspect, inp],
            variables={
                "cmd": "objcopy",
                "args": f"-f {format} -m {kernel_introspect} {out} {inp.outputs[0]}",
                "description": f"Objcopy {inp.outputs[0]} -> {out}",
            },
        )

    def _gen_metadata(self, inp: NinjaBuild, out: Path) -> NinjaBuild:
        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=[inp],
            variables={
                "cmd": "gen_task_metadata_bin",
                "args": f"{out} {inp.outputs[0]} {self.path.project_dir}",
                "description": f"Generate {out}",
            },
        )

    def _kernel_fixup(self, inp: Path, out: Path, metadata: list[NinjaBuild]) -> NinjaBuild:
        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=metadata + [self._kernel._package.as_dependency],
            variables={
                "cmd": "kernel_fixup",
                "args": f"{out} {inp} {' '.join(f"{m.outputs[0]}" for m in metadata)}",
                "description": "Kernel fixup",
            },
        )

    def _srec_cat(
        self, out: Path, kernel: NinjaBuild, idle: Path, apps: list[NinjaBuild]
    ) -> NinjaBuild:
        hex_files = [str(app.outputs[0]) for app in apps + [kernel]]
        hex_files.append(str(idle))
        return NinjaBuild(
            outputs=[out],
            rule="internal",
            implicit=apps + [kernel],
            variables={
                "cmd": "srec_cat",
                "args": f"--format ihex {out} {' '.join(hex_files)}",
                "description": f"generating {out} with srec_cat",
            },
            build_by_default=True,
        )

    @property
    def _integration_targets(self) -> list[NinjaBuild]:
        dummy_layout = self._dummy_layout_target(self.path.private_build_dir / "dummy_layout.json")
        dummy_ld_script = self._gen_ldscript_target(
            "dummy", self.path.private_build_dir / "dummy.lds", dummy_layout
        )
        # dummy link for partially linked, non-pic application
        dummy_apps: list[NinjaBuild] = []
        for package in self._packages:
            if package.is_application:
                dummy_apps.append(
                    self._relink_target(
                        package,
                        package.installed_targets[0],
                        package.dummy_linked_targets[0],
                        dummy_ld_script,
                    )
                )

        # Generate final firmware layout
        firmware_layout = self._firmware_layout_target(
            self.path.private_build_dir / "layout.json", dummy_apps
        )

        apps_ld_script: list[NinjaBuild] = []
        apps_elves: list[NinjaBuild] = []
        apps_hex: list[NinjaBuild] = []
        apps_metadata: list[NinjaBuild] = []

        for package in self._packages:
            if package.is_application:
                elf = package.installed_targets[0]
                relinked_elf = package.relocated_targets[0]
                ld_script = self.path.private_build_dir / f"{elf.stem}.lds"
                metadata = relinked_elf.with_suffix(".meta")
                hex = relinked_elf.with_suffix(".hex")

                apps_ld_script.append(
                    self._gen_ldscript_target(elf.stem, ld_script, firmware_layout, package)
                )

                apps_elves.append(
                    self._relink_target(package, elf, relinked_elf, apps_ld_script[-1])
                )

                apps_hex.append(self._objcopy(apps_elves[-1], hex, "ihex"))

                apps_metadata.append(self._gen_metadata(apps_elves[-1], metadata))

        # XXX this is ugly (...)
        _kernel_elf = self._kernel._package.installed_targets[1]
        _kernel_patched = self._kernel._package.relocated_targets[1]
        _kernel_hex = _kernel_patched.with_suffix(".hex")
        _idle_hex = self._kernel._package.installed_targets[0].with_suffix(".hex")

        kernel_patched = self._kernel_fixup(_kernel_elf, _kernel_patched, apps_metadata)
        kernel_hex = self._objcopy(kernel_patched, _kernel_hex, "ihex")
        firmware = self._srec_cat(
            self.path.build_dir / "firmware.hex",
            kernel_hex,
            _idle_hex,
            apps_hex,
        )

        return [
            dummy_layout,
            dummy_ld_script,
            *dummy_apps,
            firmware_layout,
            *apps_ld_script,
            *apps_elves,
            *apps_hex,
            *apps_metadata,
            kernel_patched,
            kernel_hex,
            firmware,
        ]

    def download(self) -> None:
        logger.info("Downloading packages")
        for p in self._packages:
            p.download()

    def update(self) -> None:
        logger.info("Updating packages")
        for p in self._packages:
            p.update()

    def setup(self) -> None:

        logger.info("Create Cargo local repository")
        registry = cargo.LocalRegistry(
            self.path.sysroot_data_dir / "cargo" / "registry" / "camelot_sdk"
        )
        cargo_config = cargo.Config(self.path.output_dir, registry)
        registry.init()
        self._kernel.install_crates(registry, cargo_config)
        self._runtime.install_crates(registry, cargo_config)

        logger.info(f"Generating {self.name} Ninja build File")
        NinjaFile(self._packages + [self]).write(self._ninja_filepath)
