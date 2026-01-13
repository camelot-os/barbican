# SPDX-FileCopyrightText: 2023 - 2024 Ledger SAS
# SPDX-FileCopyrightText: 2025 - 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from argparse import ArgumentParser
import os
import logging
import pathlib
import sys

from .logger import logger, log_config


class CommandLineArguments:
    def __init__(self) -> None:
        from . import cmd_download, cmd_setup, cmd_update

        self.parser = ArgumentParser(prog="barbican", add_help=True)
        self.subparsers = self.parser.add_subparsers(
            required=True,
            title="Commands",
            dest="command",
            description="Execute one of the following commands",
        )
        self.parents_parser = [self._log_level_arguments(), self._project_common_arguments()]

        self.add_command(
            "download",
            cmd_download.add_arguments,
            cmd_download.run,
            "download project packages sources",
        )
        self.add_command(
            "update", cmd_update.add_arguments, cmd_update.run, "update project packages sources"
        )
        self.add_command("setup", cmd_setup.add_arguments, cmd_setup.run, "setup project")

    def _log_level_arguments(self) -> ArgumentParser:
        parser = ArgumentParser(add_help=False)
        loglevel_parser = parser.add_argument_group("logging")
        loglevel_parser.add_argument("-q", "--quiet", action="store_true")
        loglevel_parser.add_argument("-v", "--verbose", action="store_true")
        loglevel_parser.add_argument(
            "--log-level",
            action="store",
            choices=["debug", "info", "warning", "error"],
            default="info",
        )

        return parser

    def _project_common_arguments(self) -> ArgumentParser:
        parser = ArgumentParser(add_help=False)
        project_parser = parser.add_argument_group("project arguments")
        project_parser.add_argument(
            "projectdir", type=pathlib.Path, action="store", default=os.getcwd(), nargs="?"
        )

        return parser

    def add_command(self, name: str, add_arguments, run_cmd, help) -> None:
        cmd_parser = self.subparsers.add_parser(name, help=help, parents=self.parents_parser)
        add_arguments(cmd_parser)
        cmd_parser.set_defaults(func=run_cmd)

    def run(self) -> None:
        args = self.parser.parse_args()
        if args.verbose:
            log_config.set_console_log_level(logging.DEBUG)
        elif args.quiet:
            log_config.set_console_log_level(logging.ERROR)
        else:
            lvl = logging.getLevelName(args.log_level.upper())
            log_config.set_console_log_level(lvl)

        args.func(args)


def run_internal_command(cmd: str, argv: list[str]) -> None:
    """Run an internal barbican command.

    :param cmd: internal command name
    :type cmd: str
    :param argv: internal command arguments
    :type argv: List[str], optional

    Each internal commands are in the `_internal` subdir and each module is named with the
    command name. Each internal must accept an argument of type List[str].
    """
    import importlib

    module = importlib.import_module("camelot.barbican._internals." + cmd)
    module.run(argv)


def main() -> None:
    """Barbican script entrypoint.

    Execute an barbican command or an internal command.
    barbican commands are user entrypoint, dedicated help can be printed in terminal.
    barbican internal commands are used by build system backend for internal build steps,
    those are not available through user help.

    command usage:
     `barbican <cmd> [option(s)]`
    internal command usage:
     `barbican --internal <internal_cmd> [option(s)]`
    """
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == "--internal":
            if len(sys.argv) == 2:
                raise ValueError("missing internal command")
            run_internal_command(sys.argv[2], sys.argv[3:])
        else:
            CommandLineArguments().run()

    except Exception as e:
        logger.critical(str(e))
        raise
        exit(1)
    else:
        exit(0)
