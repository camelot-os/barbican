# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from typing import cast
from pathlib import Path
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
)

import tarfile
import hashlib
import stat

from ..logger import logger
from ..console import console
from ..utils.downloader import download_file
from .scm import ScmBaseClass


class Tarball(ScmBaseClass):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._url: str = cast(str, self._config.get("uri"))
        self._hashfile_url: str | None = cast(str | None, self._config.get("hashfile_uri"))
        self._hash_algorithm: str = self._config.get("hash_algorithm", "sha256")
        self._strip: int = self._config.get("strip", 0)
        self._tarball = Path()
        self._hashfile = Path()

    @staticmethod
    def _strip_member_path(path: Path, strip: int) -> Path:
        return Path(*path.parts[strip:])

    def _verify_download(self) -> None:
        if not self._hashfile_url:
            console.warning(f"Missing hash information for [i]{self._tarball.name}[/i]")
            return
        if self._tarball.exists() and self._hashfile.exists():
            expected_digest, filename = self._hashfile.read_text().split()
            hash = hashlib.new(self._hash_algorithm)
            hash.update(self._tarball.read_bytes())
            digest = hash.hexdigest()
            console.message(f"{self._hash_algorithm}sum: [i]{digest}[/i]")
            if expected_digest != digest:
                console.message(f"{self._tarball.name}: [bold red]FAILED[/bold red]")
                console.error(f"expected {self._hash_algorithm}sum: [i]{expected_digest}[/i]")
                raise Exception

            console.message(f"{self._tarball.name}: [bold green]OK[/bold green]")

    def _extract(self) -> None:
        console.message(f"[b]Extracting[/b] [i]{self._tarball.name}[/i]")
        progress = Progress(
            TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            MofNCompleteColumn(),
            "•",
            TimeRemainingColumn(),
            console=console._console,
        )
        if not tarfile.is_tarfile(self._tarball):
            raise Exception

        with progress:
            task_id = progress.add_task("extracting", start=False, filename=self._tarball.name)
            with tarfile.open(self._tarball, "r") as f:
                nr_members: int = 0

                for member in f.getmembers():
                    member.name = str(self._strip_member_path(Path(member.name), self._strip))
                    nr_members = nr_members + 1

                    if member.islnk():
                        member.linkname = str(
                            self._strip_member_path(Path(member.linkname), self._strip)
                        )
                    elif member.isdir() and member.mode & stat.S_IWUSR == 0:
                        # members number is used for progress bar total element.
                        # If a dir is readonly, it will be create with `r/w` permission, all
                        # components will be extracted and then permission is changed to `ro`.
                        # Thus, progress callback will be call twice for this member.
                        nr_members = nr_members + 1

                progress.update(task_id, total=nr_members)
                progress.start_task(task_id)

                def _progress_filter(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
                    logger.debug(f" Extracting {member.name}")
                    progress.update(task_id, advance=1)

                    return member

                # As tarfile might be readonly, one should use extractall which handles
                # directories permission properly.
                f.extractall(path=self.sourcedir, filter=_progress_filter)

    def _download_files(self) -> None:
        self._tarball = download_file(self._url, self._dl_dir)
        if self._hashfile_url is not None:
            self._hashfile = download_file(self._hashfile_url, self._dl_dir)

    def download(self) -> None:
        self._download_files()
        self._verify_download()
        self._extract()

    def update(self) -> None: ...
