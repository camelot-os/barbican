# SPDX-FileCopyrightText: 2024 Ledger SAS
#
# SPDX-License-Identifier: Apache-2.0

from functools import lru_cache
from pathlib import Path

from .package import Package
from .meson import Meson
from .cargo import LocalRegistry, Metadata, Config

from ..console import console
from ..logger import logger
from ..utils import working_directory


class Kernel:
    def __init__(self, parent, config: dict) -> None:
        self._package = Meson("kernel", parent, config["kernel"], Package.Type.Kernel)
        _subprojects_dir = self._package.src_dir / "subprojects"
        _kconfig_dir : Path | None = None

        # XXX: need SDK support here
        # workaround for the following use case.
        #
        # Kernel may use frozen version instead of git refs for its subprojects,
        # this implies usage of release tarball and thus, meson will append the
        # package version after the wrap name.
        #
        # One need to glob `kconfig*` from subprojects directory and stop at first directory found.
        # (fyi, glob will return a generator w/ the wrap file and package source directory).
        for p in _subprojects_dir.glob("kconfig*"):
            if p.is_dir():
                _kconfig_dir = p
                break

        if p is None or not p.exists():
            raise Exception("kconfig not found")

        self._cargo_manifests = {
            "sentry-uapi": self._package.src_dir / "uapi" / "Cargo.toml",
            "kconfig": _kconfig_dir / "rust" / "kconfig" / "Cargo.toml",
            "kconfig_import": _kconfig_dir / "rust" / "kconfig_import" / "Cargo.toml",
        }

        self._cargo_home: Path = parent.path.sysroot_data_dir / "cargo"
        self._rustargs = self._cargo_home / "rustargs"
        self._rust_target = self._cargo_home / "rust_target"

    def install_crates(self, registry: LocalRegistry, cargo_config: Config) -> None:
        self._package.build_dir.mkdir(exist_ok=True)
        with working_directory(self._package.build_dir):
            for name, manifest in self._cargo_manifests.items():
                console.message(f"Install [b]{name}[/b] ([i]{str(manifest)}[/i]) to local registry")
                metadata = Metadata(manifest)
                version = metadata.package_version(name)
                if not version:
                    logger.warning(f"{name} version not found, skip")
                    continue
                registry.publish(
                    name=name,
                    version=version,
                    manifest=manifest,
                    target_dir=self._package.build_dir,
                )
                cargo_config.patch_crate_registry(name=name, version=version)

    @property
    @lru_cache
    def rustargs(self) -> Path:
        return self._rustargs

    @property
    @lru_cache
    def rust_target(self) -> Path:
        return self._rust_target
