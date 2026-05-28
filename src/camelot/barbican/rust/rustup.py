# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Rustup toolchain installer for the Camelot SDK."""

import os
import stat
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum, auto, unique
from pathlib import Path
from subprocess import CalledProcessError
from typing import ClassVar

from ..console import console
from ..logger import logger
from ..utils.downloader import download_file


@unique
class RustupChannel(StrEnum):
    Stable = auto()
    Nightly = auto()


@unique
class RustupProfile(StrEnum):
    Minimal = auto()
    Default = auto()
    Complete = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class RustupConfig:
    version: str
    channel: RustupChannel = RustupChannel.Stable
    profile: RustupProfile = RustupProfile.Minimal
    targets: list[str]
    extra: list[str] = field(default_factory=list)


class Rustup:
    """Rust toolchain installer using the official rustup-init script.

    Downloads and runs ``https://sh.rustup.rs``, then adds the configured
    cross-compilation targets and optional extra components.  The environment
    variables ``CARGO_HOME`` and ``RUSTUP_HOME`` are set from *host_dir* so
    that the entire toolchain is installed inside the SDK tree instead of the
    user's home directory.
    """

    _RUSTUP_INIT_URL: ClassVar[str] = "https://sh.rustup.rs"

    def __init__(self, config: dict, host_dir: Path) -> None:
        """Initialise a Rustup installer from the TOML compiler configuration.

        Parameters
        ----------
        config : dict
            Rustc compiler configuration from the ``compiler.rustc`` TOML
            node.  Required keys: ``version`` (str), ``targets``
            (list[str]).  Optional keys: ``channel`` (str, default
            ``"stable"``), ``profile`` (str, default ``"minimal"``),
            ``extra`` (list[str]).
        host_dir : Path
            SDK host directory (``ProjectPath.host_dir``).  ``CARGO_HOME``
            is set to this path; ``RUSTUP_HOME`` is set to
            ``host_dir / "share" / "rustup"``.

        Raises
        ------
        ValueError
            If ``version`` is missing or empty.
            If ``targets`` is empty.
            If ``profile`` is invalid
            If ``channel`` is invalid
        """
        if not config.get("version", ""):
            raise ValueError("Rustup: 'version' is required and must not be empty")

        if not config.get("targets", []):
            raise ValueError("Rustup: 'targets' must not be empty")

        # implicitly raises ValueError if channel is not valid (see RustupChannel StrEnum)
        channel = config.get("channel")
        if channel is not None:
            config["channel"] = RustupChannel(channel)

        # implicitly raises ValueError if profile is not valid (see RustupProfile StrEnum)
        profile = config.get("profile")
        if profile is not None:
            config["profile"] = RustupProfile(profile)

        self._cfg: RustupConfig = RustupConfig(**config)
        self._cargo_home: Path = host_dir
        self._rustup_home: Path = host_dir / "share" / "rustup"

    @property
    def cargo_home(self) -> Path:
        """Cargo home directory (``CARGO_HOME``).

        Returns
        -------
        Path
            Equal to the ``host_dir`` passed at construction.
        """
        return self._cargo_home

    @property
    def rustup_home(self) -> Path:
        """Rustup home directory (``RUSTUP_HOME``).

        Returns
        -------
        Path
            Equal to ``host_dir / "share" / "rustup"``.
        """
        return self._rustup_home

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["CARGO_HOME"] = str(self._cargo_home)
        env["RUSTUP_HOME"] = str(self._rustup_home)
        return env

    def _run(self, cmd: list[str], description: str) -> None:
        logger.debug(f"Running: {' '.join(cmd)}")
        try:
            with console.status(description):
                subprocess.run(cmd, env=self._env(), check=True, capture_output=True, text=True)
        except CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}\nstdout: {e.stdout}\nstderr: {e.stderr}")
            raise RuntimeError(f"Rustup: command failed: {description!r}") from e

    def install(self, dl_dir: Path) -> None:  # noqa: DOC502
        """Download and install the Rust toolchain.

        Downloads the official ``rustup-init`` script, runs it to install
        the configured toolchain, then adds the required cross-compilation
        targets and any optional extra components.  Each step is shown to
        the user via a Rich status spinner.

        Parameters
        ----------
        dl_dir : Path
            Directory used to download the ``rustup-init`` installer script.

        Raises
        ------
        RuntimeError
            If the installer, ``rustup target add``, or
            ``rustup component add`` exits with a non-zero status.
        """
        self._cargo_home.mkdir(parents=True, exist_ok=True)
        self._rustup_home.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading rustup-init from {self._RUSTUP_INIT_URL}")
        init_script = download_file(self._RUSTUP_INIT_URL, dl_dir)
        init_script.chmod(init_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        if self._cfg.channel == RustupChannel.Nightly:
            toolchain = f"{self._cfg.channel}-{self._cfg.version}"
        else:
            toolchain = f"{self._cfg.version}"

        self._run(
            [
                "sh",
                str(init_script),
                "-y",
                "--no-modify-path",
                "--default-toolchain",
                toolchain,
                "--profile",
                self._cfg.profile,
            ],
            f"Installing Rust toolchain {toolchain}",
        )

        rustup = str(self._cargo_home / "bin" / "rustup")
        self._run(
            [rustup, "target", "add", *self._cfg.targets],
            f"Adding Rust targets: {', '.join(self._cfg.targets)}",
        )

        if self._cfg.extra:
            self._run(
                [rustup, "component", "add", *self._cfg.extra],
                f"Adding Rust components: {', '.join(self._cfg.extra)}",
            )

        logger.info(f"Rust toolchain {toolchain} installed successfully")
