"""Hivemind CLI entry point."""

from __future__ import annotations

import click

from hivemind.commands.audit import audit as _audit_cmd
from hivemind.commands.commit import push_cmd as _push_cmd
from hivemind.commands.config_cmd import config_cmd as _config_cmd
from hivemind.commands.doctor import doctor_cmd as _doctor_cmd
from hivemind.commands.feedback import feedback as _feedback_group
from hivemind.commands.harness_score import harness_score_cmd as _harness_score_cmd
from hivemind.commands.important import important as _important_group
from hivemind.commands.init import init_cmd as _init_cmd
from hivemind.commands.link import link_cmd as _link_cmd
from hivemind.commands.migrate import migrate_cmd as _migrate_cmd
from hivemind.commands.run import run as _run_cmd
from hivemind.commands.search import index as _index_group
from hivemind.commands.search import search as _search_cmd
from hivemind.commands.search import search_read as _search_read_cmd
from hivemind.commands.stats import stats as _stats_cmd
from hivemind.commands.task import task as _task_group


@click.group()
@click.version_option(package_name="agent-hivemind")
def cli() -> None:
    """hv - Agent Hivemind CLI (v2)."""


cli.add_command(_init_cmd)
cli.add_command(_link_cmd)
cli.add_command(_migrate_cmd)
cli.add_command(_doctor_cmd)
cli.add_command(_harness_score_cmd)


cli.add_command(_push_cmd, "push")


# --- task group ---

cli.add_command(_task_group)


# --- run ---

cli.add_command(_run_cmd)


# --- log group ---


@cli.group()
def log() -> None:
    """Manage agent logs."""


@log.command()
def start() -> None:
    """Start a new log session."""
    click.echo("Not implemented yet")


@log.command()
@click.argument("message")
def append(message: str) -> None:
    """Append a message to the current log."""
    click.echo("Not implemented yet")


@log.command()
def end() -> None:
    """End the current log session."""
    click.echo("Not implemented yet")


# --- feedback group ---

cli.add_command(_feedback_group)


# --- search ---

cli.add_command(_search_cmd)
cli.add_command(_search_read_cmd, "search-read")


# --- important group ---

cli.add_command(_important_group)


# --- audit ---

cli.add_command(_audit_cmd)


# --- stats ---

cli.add_command(_stats_cmd)


# --- filter ---


@cli.command()
@click.argument("file")
def filter(file: str) -> None:
    """Filter content from a file."""
    click.echo("Not implemented yet")


# --- index group ---

cli.add_command(_index_group)


# --- config ---

cli.add_command(_config_cmd)


if __name__ == "__main__":
    cli()
