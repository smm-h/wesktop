"""The CLI's effect classification, pinned so a change has to be deliberate.

strictcli requires every command to declare ``effect="read_only"`` or
``effect="mutating"``; there is no default and a missing declaration is a
registration-time hard error. The classification answers exactly one question:
*should a dry run record this operation rather than perform it?*

Separately, a command may declare itself ``consequential``, which is what the
framework's confirm protocol keys on. It is not inferred from ``mutating`` --
that inference was measured at a ~1:10 signal-to-noise ratio across the fleet
and removed.

This file pins both tables in both directions. A new command shows up as an
unexpected entry; a reclassified one shows up as a mismatch. Either way the
edit has to come here, which is the point.
"""

from typing import Any

from wesktop.cli import app

# Every command wesktop declares, with the reviewed classification.
#
# `diagnose` reads: it imports modules to report their versions, reads
# `platform`, and prints a table. It creates nothing, writes nothing and
# spawns nothing.
#
# The `config` group is auto-registered by strictcli (`App(config=True)`), not
# by wesktop. Its classification is the framework's business, so it is
# deliberately absent here -- pinning it would pin an upstream decision this
# project does not own.
EFFECTS = {
    "diagnose": "read_only",
}

# Empty, and correctly so. `consequential` marks an act worth interrupting
# someone for. wesktop's only command is read_only, and strictcli makes
# declaring a read_only command consequential a registration-time hard error
# (a command that changes nothing has nothing to confirm).
CONSEQUENTIAL: set[str] = set()


def _walk() -> dict[str, Any]:
    """Map dotted command path -> Command for every command wesktop declares."""
    found: dict[str, Any] = {}

    def visit(container: Any, prefix: str) -> None:
        registry = getattr(container, "_commands", None) or container.commands
        for name, cmd in registry.items():
            found[prefix + name] = cmd
        for name, group in container._groups.items():
            visit(group, prefix + name + ".")

    visit(app, "")
    # Drop the framework's own auto-registered subcommands: they are strictcli's
    # to classify, not wesktop's.
    return {p: c for p, c in found.items() if not p.startswith("config.")}


def test_every_command_is_classified_exactly_as_reviewed() -> None:
    declared = {path: cmd.effect for path, cmd in _walk().items()}
    assert declared == EFFECTS


def test_no_command_declares_itself_consequential() -> None:
    declared = {path for path, cmd in _walk().items() if cmd.consequential}
    assert declared == CONSEQUENTIAL


def test_no_command_redeclares_a_framework_reserved_flag_name() -> None:
    """strictcli owns dry-run/approve-consequential/quiet/verbose, and bans `yes`.

    A collision is a registration-time error, so reaching this assertion at all
    means the app built. It pins the absence so a future flag cannot quietly
    reintroduce one under a spelling the framework would reject.
    """
    reserved = {"dry-run", "approve-consequential", "quiet", "verbose", "yes"}
    assert not ({f.name for f in app._global_flags} & reserved)
    for path, cmd in _walk().items():
        names = {f.name for f in cmd.flags}
        assert not (names & reserved), f"{path} declares a reserved flag name"
