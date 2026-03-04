# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from argparse import ArgumentParser, Namespace

import rich.console
import json
from pathlib import Path
from typing import Dict, Optional, List

from rich.table import Table
from rich import box

from .project import Project

# get back console instance for rendering, we want to use the same console
# for all rendering to ensure consistent output and proper handling of colors
# and formatting
# TODO: while the local console module do not handle tables properly, we
# still use the rich console directly here, but we might want to refactor the console
# module to provide a unified interface that includes support for tables instead.
console = rich.console.Console()


# About memory layout information parts


# Utility functions for processing and displaying memory regions permissions
# so that the main logic is cleaner and easier to read that an integer
def __decode_permissions(perm: int) -> str:
    flags = [("X", 2), ("W", 1), ("R", 0)]
    return "".join(letter if perm & (1 << bit) else "-" for letter, bit in flags)


# Determine color based on region type
# very basic for now, enough to be visually distinguishable
def __region_color(region_type: str) -> str:
    if region_type.lower() == "text":
        return "cyan"
    if region_type.lower() == "ram":
        return "green"
    return "white"


# Detect overlapping regions, return a list of booleans indicating if each region
# is involved in a collision.
# This is O(n^2) but we expect a small number of regions so it should be fine.
def __detect_collisions(regions: List[Dict]) -> List[bool]:
    enriched = []
    for r in regions:
        start = int(r["start_address"], 16)
        size = int(r["size"], 16)
        end = start + size - 1
        enriched.append((r, start, end))

    enriched.sort(key=lambda x: x[1])

    collisions = {id(r): False for r, _, _ in enriched}

    for i in range(len(enriched)):
        r1, s1, e1 = enriched[i]
        for j in range(i + 1, len(enriched)):
            r2, s2, e2 = enriched[j]

            if s2 > e1:
                break

            if s2 <= e1:
                collisions[id(r1)] = True
                collisions[id(r2)] = True

    return [collisions[id(r)] for r in regions]


# Effective rendering of the memory layout using rich
def __render_layout(regions: List[Dict]) -> None:
    table = Table(
        title="Memory Mapping",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )

    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Start Addr", justify="right")
    table.add_column("End Addr", justify="right")
    table.add_column("Size (hex)", justify="right")
    table.add_column("Size (dec)", justify="right")
    table.add_column("Perm", justify="center")
    table.add_column("", justify="center", width=3)

    collisions = __detect_collisions(regions)

    regions_sorted = sorted(enumerate(regions), key=lambda x: int(x[1]["start_address"], 16))

    for original_index, r in regions_sorted:
        start = int(r["start_address"], 16)
        size = int(r["size"], 16)
        end = start + size - 1

        perms = __decode_permissions(r["permission"])
        color = __region_color(r["type"])

        collision_flag = collisions[original_index]
        collision_marker = "[bold red]X[/bold red]" if collision_flag else ""
        row_style = "on red" if collision_flag else ""

        table.add_row(
            r["name"],
            f"[{color}]{r['type'].upper()}[/{color}]",
            f"0x{start:08X}",
            f"0x{end:08X}",
            f"0x{size:X}",
            f"{size}",
            perms,
            collision_marker,
            style=row_style,
        )

    console.print(table)


# about tasks configuration overview, not directly related to memory layout but can
# be useful for overall system understanding


# .config to dict configuration. We only care about task configuration but we need
# to parse the whole file to detect if it's a valid task config and to extract capabilities.
# XXX: maybe a tool such as kconfiglib could be used for a more robust parsing,
# but for now this should be enough by now.
def __parse_config_file(path: Path) -> Dict[str, str]:
    config = {}

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()

    return config


# Extract relevant task information from a .config file, return None if the config
# is not a valid task configuration
def __extract_task_info(task_name: str, path: Path) -> Optional[Dict]:
    config = __parse_config_file(path)

    def get_value(key: str, default: str = "") -> str:
        return config.get(key, default)

    # Capabilities actives
    capabilities = [
        key.replace("CONFIG_CAP_", "")
        for key, value in config.items()
        if key.startswith("CONFIG_CAP_") and value == "y"
    ]

    return {
        "task_name": task_name,
        "label": get_value("CONFIG_TASK_LABEL"),
        "magic": get_value("CONFIG_TASK_MAGIC_VALUE"),
        "priority": get_value("CONFIG_TASK_PRIORITY"),
        "quantum": get_value("CONFIG_TASK_QUANTUM"),
        "autostart": "true" if config.get("CONFIG_TASK_AUTO_START") == "y" else "false",
        "stack_size": get_value("CONFIG_TASK_STACK_SIZE"),
        "capabilities": ", ".join(sorted(capabilities)),
    }


# rendering of the tasks configuration overview for usefull information
# helping with understanding the system configuration and scheduling behavior
def __render_tasks(tasks: List[Dict]):
    table = Table(
        title="Task Configuration Overview",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )

    table.add_column("Task Name", style="bold cyan")
    table.add_column("Label", justify="right")
    table.add_column("Magic", justify="right")
    table.add_column("Priority", justify="right")
    table.add_column("Quantum (ms)", justify="right")
    table.add_column("Autostart", justify="center")
    table.add_column("Stack Size", justify="right")
    table.add_column("Capabilities")

    for task in sorted(tasks, key=lambda x: x["task_name"]):
        autostart_style = "green" if task["autostart"] == "true" else "red"

        table.add_row(
            task["task_name"],
            task["label"],
            task["magic"],
            task["priority"],
            task["quantum"],
            f"[{autostart_style}]{task['autostart']}[/{autostart_style}]",
            task["stack_size"],
            task["capabilities"],
        )

    console.print(table)


def add_arguments(parser: ArgumentParser) -> None:
    pass


def run(args: Namespace) -> None:
    layout_path = Path(args.projectdir) / "output" / "build" / "camelot_private" / "layout.json"
    project = Project(args.projectdir)

    if not layout_path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {layout_path}")
        raise SystemExit(1)

    try:
        data = json.loads(layout_path.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[bold red]Invalid JSON:[/bold red] {e}")
        raise SystemExit(1)

    regions = data.get("regions", [])
    if not regions:
        console.print("[yellow]Warning:[/yellow] No regions found in layout.")
        return

    __render_layout(regions)

    tasks = []

    for app in project.apps:
        config_path = app.config_path

        task_info = __extract_task_info(app.name, config_path)
        if task_info:
            tasks.append(task_info)

    if not tasks:
        console.print("[yellow]No valid task configurations found.[/yellow]")

    __render_tasks(tasks)
