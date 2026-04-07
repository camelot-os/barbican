# SPDX-FileCopyrightText: 2024 Ledger SAS
#
# SPDX-License-Identifier: Apache-2.0

import subprocess

from collections.abc import Iterator

from .package import Package
from ..builder.ninja import NinjaBuild, NinjaRule, NinjaVariable
from ..utils import working_directory_attr
from ..utils.environment import find_program


class Meson(Package):
    def __init__(self, name: str, parent_project, config_node: dict, type):
        super().__init__(name, parent_project, config_node, type)

    @classmethod
    def __ninja_variables__(cls) -> Iterator[NinjaVariable]:
        yield from [
            NinjaVariable(key="meson", value=find_program("meson")),
            NinjaVariable(key="ninja", value=find_program("ninja")),
        ]

    @classmethod
    def __ninja_rules__(cls) -> Iterator[NinjaRule]:
        yield from [
            NinjaRule(
                name="meson_setup",
                command="$meson setup $opts $builddir $srcdir",
                description="Setup $name",
            ),
            NinjaRule(
                name="meson_compile",
                command="$meson compile -C $builddir && touch $out",
                description="Compile $name",
            ),
            NinjaRule(
                name="meson_introspect",
                command=(
                    "$barbican --internal capture_out $out $meson introspect --all -i $builddir"
                ),
                description="Introspect $name",
            ),
            NinjaRule(
                name="meson_install",
                command=(
                    "$meson install --only-changed --destdir $destdir $opts -C $builddir && "
                    "touch $out"
                ),
                description="Install $what $name",
            ),
            NinjaRule(
                name="meson_clean",
                command="$meson compile --clean -C $builddir && rm $stamps",
                description="Clean $name",
            ),
            # TODO distclean needs introspect install plan and packages specific install
            #  - remove installed file, dep order only w/ clean
        ]

    def __ninja_builds__(self) -> Iterator[NinjaBuild]:
        yield from self._build_targets

    @property
    def _build_targets(self) -> list[NinjaBuild]:
        _setup = NinjaBuild(
            outputs=[f"{self.build_dir}/build.ninja"],
            rule="meson_setup",
            variables={
                "builddir": self.build_dir,
                "srcdir": self.src_dir,
                "name": self.name,
                "opts": self.build_options,
            },
            order_only=[f"{dep}_install.stamp" for dep in self.deps],
        )

        _setup_alias = NinjaBuild(
            outputs=[f"{self.name}-setup"],
            rule="phony",
            inputs=[_setup],
        )

        # TODO dyndep if configured
        _introspect = NinjaBuild(
            outputs=[f"{self.name}_introspect.json"],
            rule="meson_introspect",
            order_only=[_setup],
            variables={
                "builddir": self.build_dir,
                "name": self.name,
            },
        )

        _dyndep = NinjaBuild(
            outputs=[f"{self.name}.dyndep"],
            rule="internal",
            implicit=[_introspect],
            variables={
                "cmd": "meson_package_dyndep",
                "args": (
                    f"--name={self.name} "
                    f"-j {_introspect.outputs[0]} "
                    f"{self.staging_dir} "
                    f"{self.name}.dyndep"
                ),
            },
        )

        _compile = NinjaBuild(
            outputs=[f"{self.name}_compile.stamp"],
            rule="meson_compile",
            variables={
                "name": self.name,
                "builddir": self.build_dir,
                "dyndep": _dyndep.outputs[0],
            },
            order_only=[_setup, _dyndep],
        )

        _compile_alias = NinjaBuild(
            outputs=[f"{self.name}-compile"],
            rule="phony",
            inputs=[_compile],
        )

        _install = NinjaBuild(
            outputs=[f"{self.name}_install.stamp"],
            rule="meson_install",
            variables={
                "name": self.name,
                "builddir": self.build_dir,
                "destdir": self.staging_dir,
                "what": "all",
                "opts": "",
                "dyndep": _dyndep.outputs[0],
            },
            order_only=[_compile, _dyndep],
        )

        _install_alias = NinjaBuild(
            outputs=[f"{self.name}-install"],
            rule="phony",
            inputs=[_install],
        )

        _clean = NinjaBuild(
            outputs=[f"{self.build_dir}/clean"],
            rule="meson_clean",
            inputs=[_compile, f"{self.name}_compile.stamp"],
            variables={
                "name": self.name,
                "builddir": self.build_dir,
                "stamps": list(_compile.outputs) + list(_install.outputs),
            },
        )

        _clean_alias = NinjaBuild(outputs=[f"{self.name}-clean"], rule="phony", inputs=[_clean])

        # TODO:
        #  Install destdir may differ according
        #   - Add native build tool target / install sdk target
        #   - Add install staging target (for static lib + header)
        #   - Add install data (license, man pages, kconfig, dts, etc.)
        #   - Add install bin (embedded app to integrate)
        # Add entries in package config to en/dis steps
        # By default, build for cross, install staging, binary, data
        # TOML can turns off those steps if needed and enable native tool(s)
        # build and install in sdk.
        # Generate only build target statements that are enabled in config.

        return [
            _setup,
            _setup_alias,
            _introspect,
            _dyndep,
            _compile,
            _compile_alias,
            _install,
            _install_alias,
            _clean,
            _clean_alias,
        ]

    @property
    def build_options(self) -> list[str]:
        opts = list()
        opts.append(f"-Ddts={self.parent._dts}")
        opts.append(f"-Ddts-include-dirs={','.join(str(i) for i in self.parent._dts_include_dirs)}")
        opts.append(f"--cross-file={self.parent._crossfile}")
        opts.append("--pkgconfig.relocatable")
        opts.append(f"--pkg-config-path={self.pkgconfig_dir}")
        opts.append(f"-Dconfig={str(self._dotconfig)}")
        opts.extend([f"-D{k}={str(v)}" for k, v in self._extra_build_opts.items()])
        return opts

    @working_directory_attr("src_dir")
    def post_download_hook(self):
        subprocess.run(["meson", "subprojects", "download"], capture_output=True)

    @working_directory_attr("src_dir")
    def post_update_hook(self):
        subprocess.run(["meson", "subprojects", "download"], capture_output=True)
        subprocess.run(["meson", "subprojects", "update"], capture_output=True)
