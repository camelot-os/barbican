# SPDX-FileCopyrightText: 2024 Ledger SAS
#
# SPDX-License-Identifier: Apache-2.0

import json
import shutil

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, BaseLoader

from .package import Package
from ..builder.ninja import NinjaBuild, NinjaRule, NinjaVariable
from ..utils.environment import ExeWrapper, find_program


class Metadata:
    def __init__(self, manifest_path: Path) -> None:
        self._cargo = ExeWrapper("cargo", capture_out=True)
        self._metadata = json.loads(
            self._cargo.metadata(
                manifest_path=str(manifest_path.resolve(strict=True)),
                no_deps=True,
                quiet=True,
                format_version=1,
            )
        )

    def package_version(self, name: str) -> str | None:
        p = list(filter(lambda x: x["name"] == name, self._metadata["packages"]))
        return None if len(p) != 1 else p[0]["version"]


class LocalRegistry:
    def __init__(self, path: Path) -> None:
        self._path = path
        # Check for cargo extension cargo-index (but wrapp call as cargo subcommand)
        find_program("cargo-index")
        self._cargo = ExeWrapper("cargo")

    @property
    @lru_cache
    def name(self) -> str:
        return self._path.name

    @property
    @lru_cache
    def path(self) -> Path:
        return self._path

    @property
    @lru_cache
    def index(self) -> Path:
        return self._path / "index"

    @property
    @lru_cache
    def exists(self) -> bool:
        return (self.index / ".cargo-index-lock").exists()

    def init(self) -> None:
        """Initialize a new cargo registry index."""
        if not self.exists:
            if self.index.exists():
                shutil.rmtree(self.index)
            self._cargo.index(subcmd=["init"], dl=self._path.as_uri(), index=str(self.index))

    def publish(self, *, name: str, version: str, manifest: Path, target_dir: Path) -> None:
        """Package a new cate and push to local registry index."""
        crate_filename = f"{name}-{version}.crate"
        crate_index_filepath = self.index / name[:2] / name[2:4] / name
        if crate_index_filepath.exists():
            crate_index_filepath.unlink()
        self._cargo.package(
            manifest_path=str(manifest),
            target_dir=str(target_dir),
            no_verify=True,
            allow_dirty=True,
        )
        self._cargo.index(
            subcmd=["add"],
            crate=str(target_dir / "package" / crate_filename),
            index=str(self.index),
            index_url=self.path.as_uri(),
            upload=str(self.path),
            force=True,
        )


class Config:

    template: str = """
[registries.{{ registry.name }}]
index = "{{ registry.index.as_uri() }}"

[source.{{ registry.name }}]
registry = "{{ registry.index.as_uri() }}"
replace-with = 'local-registry'

[source.local-registry]
local-registry = "{{ registry.path }}"

[net]
git-fetch-with-cli = true

{% if crates|length != 0 %}
[patch.crates-io]
{%- for name, version in crates.items() %}
{{ name }} = { version="{{ version }}", registry="{{ registry.name }}" }
{%- endfor %}
{% endif %}
"""

    def __init__(self, builddir: Path, registry: LocalRegistry) -> None:
        self._base_path = builddir
        self._local_registry = registry
        self._crates: dict[str, str] = dict()
        self.config_dir.mkdir(exist_ok=True)
        self._update()

    @property
    @lru_cache
    def config_dir(self) -> Path:
        return self._base_path / ".cargo"

    @property
    @lru_cache
    def config_filename(self) -> Path:
        return self.config_dir / "config.toml"

    def _update(self) -> None:
        template = Environment(loader=BaseLoader()).from_string(self.template)
        with self.config_filename.open(mode="w", encoding="utf-8") as config:
            config.write(template.render(registry=self._local_registry, crates=self._crates))

    def patch_crate_registry(self, name: str, version: str) -> None:
        self._crates[name] = version
        self._update()


class Cargo(Package):
    def __init__(self, name: str, parent_project, config_node: dict, type):
        super().__init__(name, parent_project, config_node, type)

        _setup = NinjaBuild(
            outputs=[f"{self.build_dir}/.cargo/config.toml"],
            rule="internal",
            variables={
                "cmd": "cargo_config",
                "args": (
                    f"--rustargs-file={str(self._parent._kernel.rustargs)} "
                    f"--target-file={str(self._parent._kernel.rust_target)} "
                    '--extra-args="' + " ".join(self.build_options) + '" '
                    f"{str(self.build_dir)}"
                ),
                "description": f"Setup {self.name}",
            },
            order_only=[f"{dep}_install.stamp" for dep in self.deps],
        )

        _setup_alias = NinjaBuild(
            outputs=[f"{self.name}-setup"],
            rule="phony",
            inputs=[_setup],
        )

        _compile = NinjaBuild(
            outputs=[f"{self.name}_compile.stamp"],
            rule="cargo_compile",
            variables={
                "name": self.name,
                "manifest": self.manifest,
                "builddir": self.build_dir,
                "env": f"config={self._dotconfig}",
            },
            implicit=[_setup],
        )

        _compile_alias = NinjaBuild(
            outputs=[f"{self.name}-compile"],
            rule="phony",
            inputs=[_compile],
        )

        _install = NinjaBuild(
            outputs=[f"{self.name}_install.stamp"],
            rule="internal",
            implicit=[_compile],
            variables={
                "cmd": "cargo_install",
                "args": (
                    "--suffix=.elf "
                    f"--target-file={str(self._parent._kernel.rust_target)} "
                    f"--stamp={self.name}_install.stamp "
                    f"{str(self.build_dir)} "
                    + " ".join((str(t.with_suffix("")) for t in self.installed_targets))
                ),
                "description": f"Install {self.name}",
            },
        )

        _install_alias = NinjaBuild(
            outputs=[f"{self.name}-install"],
            rule="phony",
            inputs=[_install],
        )

        _clean = NinjaBuild(
            outputs=[f"{self.build_dir}/clean"],
            rule="cargo_clean",
            variables={
                "name": self.name,
                "manifest": self.manifest,
                "builddir": self.build_dir,
                "env": f"config={self._dotconfig}",
                "stamps": list(_compile.outputs) + list(_install.outputs),
            },
        )

        _clean_alias = NinjaBuild(outputs=[f"{self.name}-clean"], rule="phony", inputs=[_clean])

        self._build_targets: list[NinjaBuild] = [
            _setup,
            _setup_alias,
            _compile,
            _compile_alias,
            _install,
            _install_alias,
            _clean,
            _clean_alias,
        ]

    @classmethod
    def __ninja_variables__(cls) -> Iterator[NinjaVariable]:
        yield from [
            NinjaVariable(key="cargo", value=find_program("cargo")),
        ]

    @classmethod
    def __ninja_rules__(cls) -> Iterator[NinjaRule]:
        # Cargo setup and Cargo install use internal cmd rule
        yield from [
            NinjaRule(
                name="cargo_compile",
                description="Compile $name",
                command=(
                    "cd $builddir && "
                    "$env $cargo build --manifest-path=$manifest --release && "
                    "cd - && "
                    "touch $out"
                ),
            ),
            NinjaRule(
                name="cargo_clean",
                description="Clean $name",
                command=(
                    "cd $builddir && "
                    "$env $cargo clean --manifest-path=$manifest --release && "
                    "cd - && "
                    "rm $stamps"
                ),
            ),
        ]

    def __ninja_builds__(self) -> Iterator[NinjaBuild]:
        yield from self._build_targets

    @property
    def build_options(self) -> list[str]:
        opts = list()
        opts.append("-Clto=true")
        # XXX:
        #  todo: use pic/no-pic generic opt from project.toml
        #  Hardcode no-pic (i.e. partial link, relocated and relink at build time)
        opts.append("-Clink-args=-r")
        opts.append("-Clink-args=-Wl,-entry=_start")
        return opts

    @property
    @lru_cache
    def manifest(self) -> Path:
        return (self.src_dir / "Cargo.toml").resolve()

    def deploy_local(self, registry: LocalRegistry, config: Config) -> None:
        # TODO: fetch version from cargo manifest
        pass
        # registry.add(manifest=self.manifest)
        # config.patch_crate_registry(name=self.name, version=self._scm.revision)

    def post_download_hook(self): ...

    def post_update_hook(self): ...
