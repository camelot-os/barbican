# SPDX-FileCopyrightText: 2025 - 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import tomllib

import os
import pathlib

from .console import console
from .logger import logger
from .config.validator import validate_project_config
from .package import Package, create_package, Backend
from .package.kernel import Kernel
from .package.runtime import Runtime
from .package.meson import Meson
from .package.cargo import Cargo
from .package import cargo

from .buildsys import ninja_backend
from .utils import pathhelper


class Project:
    def __init__(self, project_dir: pathlib.Path) -> None:
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

        self._packages = list()  # list of ABCpackage

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

    @property
    def name(self) -> str:
        return self._toml["name"]

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
        ninja = ninja_backend.NinjaGenFile(os.path.join(self.path.build_dir, "build.ninja"))

        ninja.add_barbican_rules()
        ninja.add_barbican_internals_rules()
        ninja.add_barbican_targets(self)
        ninja.add_barbican_cross_file(
            (pathlib.Path(self.path.project_dir) / self._toml["crossfile"]).resolve(strict=True)
        )
        dts_include_dirs = []
        for p in self._packages:
            dts_include_dirs.extend(p.dts_include_dirs)

        ninja.add_barbican_dts(
            (pathlib.Path(self.path.project_dir) / self._toml["dts"]).resolve(strict=True),
            dts_include_dirs,
        )

        ninja.add_meson_rules()
        ninja.add_cargo_rules(self._kernel.rustargs, self._kernel.rust_target)

        # Add setup/compile/install targets for meson packages
        for p in self._packages:
            if isinstance(p, Meson):
                ninja.add_meson_package(p)
            elif isinstance(p, Cargo):
                ninja.add_cargo_package(p)

        if self._noapp:
            ninja.close()
            return

        # Dummy layout for dummy link
        dummy_layout = ninja.add_internal_gen_dummy_memory_layout_target(
            output=pathlib.Path(self.path.private_build_dir, "dummy_layout.json"),
        )

        # linkerscript template file
        # XXX: hardcoded in early steps
        linker_script_template = (
            pathlib.Path(self.path.sysroot_data_dir) / "shield" / "linkerscript.ld.in"
        )

        dummy_linker_script = pathlib.Path(self.path.private_build_dir, "dummy.lds")
        ninja.add_gen_ldscript_target(
            "dummy", dummy_linker_script, linker_script_template, pathlib.Path(dummy_layout[0])
        )

        # Dummy link, for non pic application
        for package in self._packages:
            # if package.is_application and package.backend == Backend.Meson:
            if package.is_application:
                ninja.add_relink_target(
                    package.name,
                    package.installed_targets[0],
                    package.dummy_linked_targets[0],
                    dummy_linker_script,
                    package_name=package.name if package.backend == Backend.Meson else "kernel",
                )

        layout_sys_exelist = []
        layout_app_exelist = []
        for package in self._packages:
            if package.is_sys_package:
                layout_sys_exelist.extend(package.installed_targets)
            else:
                layout_app_exelist.extend(package.dummy_linked_targets)

        firmware_layout = ninja.add_internal_gen_memory_layout_target(
            output=pathlib.Path(self.path.private_build_dir, "layout.json"),
            dts=pathlib.Path(
                self.path.sysroot_data_dir, f"{pathlib.Path(self._toml['dts']).name}.pp"
            ),
            dependencies=self._packages,
            sys_exelist=layout_sys_exelist,
            app_exelist=layout_app_exelist,
        )

        app_metadata = []
        app_hex_files = []

        # gen_ld/relink/gen_meta/objcopy app(s)
        for package in self._packages:
            if package.is_application:
                # XXX: Handle multiple exe package
                elf_in = package.installed_targets[0]
                elf_out = package.relocated_targets[0]
                linker_script = pathlib.Path(self.path.private_build_dir, f"{elf_in.stem}.lds")
                metadata_out = elf_out.with_suffix(".meta")
                hex_out = elf_out.with_suffix(".hex")

                ninja.add_gen_ldscript_target(
                    elf_in.stem,
                    linker_script,
                    linker_script_template,
                    pathlib.Path(firmware_layout[0]),
                    package.name,
                )
                ninja.add_relink_target(
                    package.name,
                    elf_in,
                    elf_out,
                    linker_script,
                    package_name=package.name if package.backend == Backend.Meson else "kernel",
                )

                ninja.add_objcopy_rule(
                    elf_out,
                    hex_out,
                    "ihex",
                    [],
                    package_name=package.name if package.backend == Backend.Meson else "kernel",
                )
                app_hex_files.append(hex_out)

                ninja.add_gen_metadata_rule(
                    elf_out, metadata_out, pathlib.Path(self.path.project_dir)
                )
                app_metadata.append(metadata_out)

        # Patch kernel/objcopy
        kernel_elf = self._packages[0].installed_targets[1]
        kernel_patched_elf = self._packages[0].relocated_targets[1]
        kernel_hex = kernel_patched_elf.with_suffix(".hex")
        # idle_elf = self._packages[0].installed_targets[0]
        # XXX this is ugly (...)
        idle_hex = self._packages[0].installed_targets[0].with_suffix(".hex")

        ninja.add_fixup_kernel_rule(kernel_elf, kernel_patched_elf, app_metadata)
        ninja.add_objcopy_rule(kernel_patched_elf, kernel_hex, "ihex", [], self._packages[0].name)

        # XXX:
        # idle does not need to be relocated nor patched, use the one installed by sentry package
        # This is not a dependency of srec_cat as there is no explicit nor implicit rule to built-it
        # (this is an implicit **dynamic** output)
        # ninja.add_objcopy_rule(idle_elf, idle_hex, "ihex", None, self._packages[0].name)

        # srec_cat
        firmware_hex = pathlib.Path(self.path.build_dir) / "firmware.hex"
        ninja.add_srec_cat_rule(kernel_hex, idle_hex, app_hex_files, firmware_hex)

        ninja.close()
