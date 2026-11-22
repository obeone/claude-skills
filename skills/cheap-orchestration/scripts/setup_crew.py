#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Install or check the cheap-orchestration crew for one provider.

The skill names four agents (scout, editor, worker, reviewer) and ties each to
a model tier. This script renders the bundled definitions for the harness of a
given provider and writes them where that harness looks for agents:

- ``claude``: Markdown with YAML front-matter, ``~/.claude/agents/<name>.md``
- ``codex``: TOML, ``~/.codex/agents/<name>.toml``
- ``gemini``: Markdown with YAML front-matter, ``~/.gemini/agents/<name>.md``
  (experimental in the Gemini CLI, needs ``experimental.enableAgents``)

Nothing is written without ``--apply``, and an existing entry (a file or a
symlink) is never replaced without ``--force``. User scope follows the
harness's own configuration directory (``CLAUDE_CONFIG_DIR``, ``CODEX_HOME``)
when it is set.

``--check`` reads each installed definition and compares its name and its
model with what this provider and these tier overrides expect, so a
definition from another provider or one that inherits the session model does
not pass.

Usage
-----
    uv run setup_crew.py --provider claude              # dry run, user scope
    uv run setup_crew.py --provider codex --apply       # install
    uv run setup_crew.py --provider claude --check      # exit 1 if not ready
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "agents"
RULES_FILE = AGENTS_DIR.parent / "delegation-and-cost.md"

# The tier of each agent is the cost boundary of the whole skill, so it is
# fixed here and not read from the bundled files.
AGENT_TIERS = {
    "scout": "small",
    "editor": "small",
    "worker": "medium",
    "reviewer": "large",
}

# Agents that must never change a file. Only they get a restricted tool list
# on harnesses whose tool names differ from Claude Code's.
READ_ONLY_AGENTS = {"scout"}


@dataclass(frozen=True)
class Provider:
    """
    Where and how one provider's harness expects agent definitions.

    Attributes
    ----------
    config_dir : str
        Harness configuration directory name, found in the home directory
        (user scope) or in the project root (project scope).
    extension : str
        File extension of an agent definition, with the leading dot.
    models : dict[str, str]
        Model identifier written in the definition, per tier.
    labels : dict[str, str]
        Human name of the model, per tier, used in descriptions and in the
        bracket label of a delegation call.
    home_env : str or None
        Environment variable that relocates the harness's user configuration
        directory, when the harness has one.
    enforces_no_delegation : bool
        Whether the rendered definition technically keeps the agent from
        launching others. When false, the limit is an instruction only.
    """

    config_dir: str
    extension: str
    models: dict[str, str]
    labels: dict[str, str]
    home_env: str | None = None
    enforces_no_delegation: bool = False


PROVIDERS = {
    "claude": Provider(
        config_dir=".claude",
        extension=".md",
        models={"small": "haiku", "medium": "sonnet", "large": "opus"},
        labels={"small": "Haiku", "medium": "Sonnet", "large": "Opus"},
        home_env="CLAUDE_CONFIG_DIR",
        # The bundled tool lists have no Agent tool.
        enforces_no_delegation=True,
    ),
    "codex": Provider(
        config_dir=".codex",
        extension=".toml",
        models={
            "small": "gpt-6-luna",
            "medium": "gpt-6.1-terra",
            "large": "gpt-6.2-sol",
        },
        labels={"small": "Luna", "medium": "Terra", "large": "Sol"},
        home_env="CODEX_HOME",
    ),
    "gemini": Provider(
        config_dir=".gemini",
        extension=".md",
        models={
            "small": "gemini-4-hydrogen",
            "medium": "gemini-4-neon",
            "large": "gemini-4-carbon",
        },
        labels={"small": "Hydrogen", "medium": "Neon", "large": "Carbon"},
    ),
}

# Read-only tool names of the Gemini CLI. Editing agents get no list there and
# inherit the session's tools.
GEMINI_READ_ONLY_TOOLS = ["read_file", "grep_search"]

# Appended to the instructions on harnesses where nothing technical stops an
# agent from launching another one: the limit is then this sentence.
NO_DELEGATION = (
    "Never launch, spawn or delegate to another agent, whatever tools you "
    "have. Do the work yourself, and report if you cannot."
)


@dataclass(frozen=True)
class Agent:
    """
    One bundled agent definition, parsed from its Claude Code source file.

    Attributes
    ----------
    name : str
        Agent name, also the file stem.
    description : str
        One-line description the main loop reads to pick the agent.
    front_matter : dict[str, str]
        Every front-matter key of the source file, in order.
    body : str
        System instructions, without the front-matter.
    """

    name: str
    description: str
    front_matter: dict[str, str]
    body: str


def parse_agent(path: Path) -> Agent:
    """
    Parse a bundled agent file.

    Parameters
    ----------
    path : Path
        Markdown file starting with a ``---`` delimited front-matter made of
        single-line ``key: value`` pairs.

    Returns
    -------
    Agent
        The parsed definition.

    Raises
    ------
    ValueError
        If the file has no front-matter, or lacks ``name`` or ``description``.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing front-matter")
    try:
        header, body = text[4:].split("\n---\n", 1)
    except ValueError:
        raise ValueError(f"{path}: unterminated front-matter") from None
    front_matter: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"{path}: not a key: value line: {line!r}")
        front_matter[key.strip()] = value.strip()
    for required in ("name", "description"):
        if not front_matter.get(required):
            raise ValueError(f"{path}: front-matter lacks {required!r}")
    return Agent(
        name=front_matter["name"],
        description=front_matter["description"],
        front_matter=front_matter,
        body=body.lstrip("\n"),
    )


def load_agents(source_dir: Path = AGENTS_DIR) -> list[Agent]:
    """
    Load the four crew agents from the bundled definitions.

    Parameters
    ----------
    source_dir : Path, optional
        Directory holding ``<name>.md`` for each crew agent.

    Returns
    -------
    list[Agent]
        The agents, in the order of ``AGENT_TIERS``.

    Raises
    ------
    ValueError
        If a file declares a name other than its stem.
    """
    agents = []
    for name in AGENT_TIERS:
        agent = parse_agent(source_dir / f"{name}.md")
        if agent.name != name:
            raise ValueError(f"{name}.md declares name {agent.name!r}")
        agents.append(agent)
    return agents


def describe(agent: Agent, provider_name: str, model: str) -> str:
    """
    Return the agent description with the right model name in front.

    The bundled descriptions start with the Claude model name ("Haiku
    read-only code scout"). That word is replaced with the name of the model
    the agent will really run on, because the main loop copies it into the
    label of each delegation: a wrong name there hides the real cost tier.

    Parameters
    ----------
    agent : Agent
        The bundled definition.
    provider_name : str
        Key of ``PROVIDERS``.
    model : str
        Model identifier the definition is rendered with.

    Returns
    -------
    str
        The description for that provider and model.
    """
    tier = AGENT_TIERS[agent.name]
    provider = PROVIDERS[provider_name]
    claude_label = PROVIDERS["claude"].labels[tier]
    # A tier override has no display name: the identifier itself is the only
    # truthful label.
    label = provider.labels[tier] if model == provider.models[tier] else model
    first, _, rest = agent.description.partition(" ")
    if first == claude_label:
        return f"{label} {rest}"
    return agent.description


def render(agent: Agent, provider_name: str, models: dict[str, str]) -> str:
    """
    Render one agent definition in the format of a provider's harness.

    Parameters
    ----------
    agent : Agent
        The bundled definition.
    provider_name : str
        Key of ``PROVIDERS``.
    models : dict[str, str]
        Model identifier per tier, already merged with command-line overrides.

    Returns
    -------
    str
        The file content, ending with a newline.
    """
    model = models[AGENT_TIERS[agent.name]]
    description = describe(agent, provider_name, model)
    body = agent.body.rstrip("\n") + "\n"
    if not PROVIDERS[provider_name].enforces_no_delegation:
        body += "\n" + NO_DELEGATION + "\n"

    if provider_name == "claude":
        lines = ["---"]
        for key, value in agent.front_matter.items():
            if key == "model":
                value = model
            elif key == "description":
                value = description
            lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines) + "\n\n" + body

    if provider_name == "codex":
        # A JSON string is a valid TOML basic string: same quoting, same
        # escapes. It keeps the instructions on one line and needs no TOML
        # writer.
        fields = {
            "name": agent.name,
            "description": description,
            "developer_instructions": body,
            "model": model,
        }
        return "".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
            for key, value in fields.items()
        )

    lines = [
        "---",
        f"name: {agent.name}",
        f"description: {json.dumps(description, ensure_ascii=False)}",
        "kind: local",
        f"model: {model}",
    ]
    if agent.name in READ_ONLY_AGENTS:
        lines.append("tools:")
        lines.extend(f"  - {tool}" for tool in GEMINI_READ_ONLY_TOOLS)
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body


def destination(provider_name: str, scope: str, dest: Path | None) -> Path:
    """
    Resolve the directory agent definitions are written to.

    Parameters
    ----------
    provider_name : str
        Key of ``PROVIDERS``.
    scope : str
        ``user`` for the home directory, ``project`` for the current one.
    dest : Path or None
        Explicit directory, which wins over ``scope``.

    Returns
    -------
    Path
        The target directory. It may not exist yet. In user scope it is the
        ``agents`` directory of the harness's configuration directory, taken
        from the provider's environment variable when that is set.
    """
    if dest is not None:
        return dest
    provider = PROVIDERS[provider_name]
    if scope == "project":
        return Path.cwd() / provider.config_dir / "agents"
    # A relocated profile is where the running harness reads its agents:
    # writing to the default directory would install a crew it never sees.
    relocated = os.environ.get(provider.home_env) if provider.home_env else None
    if relocated:
        return Path(relocated).expanduser() / "agents"
    return Path.home() / provider.config_dir / "agents"


def read_pin(path: Path, provider_name: str) -> tuple[str | None, str | None]:
    """
    Read the name and the pinned model of an installed definition.

    Parameters
    ----------
    path : Path
        Installed definition, TOML for Codex, front-matter Markdown otherwise.
    provider_name : str
        Key of ``PROVIDERS``.

    Returns
    -------
    tuple[str or None, str or None]
        ``(name, model)``, each None when the definition does not declare it.

    Raises
    ------
    ValueError
        If the file cannot be parsed as a definition of that provider.
    """
    text = path.read_text(encoding="utf-8")
    if PROVIDERS[provider_name].extension == ".toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"not valid TOML: {exc}") from None
        name, model = data.get("name"), data.get("model")
        return (
            name if isinstance(name, str) else None,
            model if isinstance(model, str) else None,
        )
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("no front-matter")
    header = text[4:].split("\n---\n", 1)[0]
    fields: dict[str, str] = {}
    # Only top-level scalar keys matter here; list items and nested keys of a
    # user's own definition are skipped rather than rejected.
    for line in header.splitlines():
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip().strip("\"'")
    return fields.get("name") or None, fields.get("model") or None


def crew_problems(
    provider_name: str, target: Path, models: dict[str, str]
) -> list[str]:
    """
    List what keeps the installed crew from being safe to delegate to.

    A definition that exists is not enough: one copied from another provider,
    or a user's own file with ``model: inherit``, would bill the session
    model, which is the failure this check exists to catch.

    Parameters
    ----------
    provider_name : str
        Key of ``PROVIDERS``.
    target : Path
        Directory to look in.
    models : dict[str, str]
        Expected model identifier per tier, overrides included.

    Returns
    -------
    list[str]
        One line per problem, empty when the crew is complete and pinned.
    """
    extension = PROVIDERS[provider_name].extension
    problems = []
    for name, tier in AGENT_TIERS.items():
        path = target / f"{name}{extension}"
        if not path.is_file():
            problems.append(f"{name}: missing ({path.name})")
            continue
        try:
            found_name, found_model = read_pin(path, provider_name)
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            problems.append(f"{name}: unreadable definition ({exc})")
            continue
        if found_name != name:
            problems.append(f"{name}: definition declares name {found_name!r}")
        expected = models[tier]
        if found_model != expected:
            problems.append(
                f"{name}: model is {found_model!r}, expected {expected!r} "
                f"({tier} tier)"
            )
    return problems


def write_entry(path: Path, content: str, replace: bool) -> None:
    """
    Write a definition as a new regular file in its directory.

    The entry itself is replaced, never its target: a symlink into a shared
    dotfiles checkout must not have that shared file truncated, and a dangling
    symlink must not make the write land somewhere else.

    Parameters
    ----------
    path : Path
        Destination entry.
    content : str
        File content.
    replace : bool
        Remove an existing file or symlink first. When false the creation is
        exclusive and fails if anything is there.

    Raises
    ------
    FileExistsError
        If ``replace`` is false and the entry exists.
    IsADirectoryError
        If the entry is a directory.
    """
    if path.is_dir() and not path.is_symlink():
        raise IsADirectoryError(str(path))
    if replace and (path.is_symlink() or path.exists()):
        path.unlink()
    # "x" refuses to follow or overwrite anything that appeared meanwhile.
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(content)


def install(
    provider_name: str,
    target: Path,
    models: dict[str, str],
    apply: bool,
    force: bool,
) -> int:
    """
    Write the crew definitions, or report what would be written.

    Parameters
    ----------
    provider_name : str
        Key of ``PROVIDERS``.
    target : Path
        Directory to write into, created on ``apply``.
    models : dict[str, str]
        Model identifier per tier.
    apply : bool
        Write the files. When false, only print the plan.
    force : bool
        Replace an existing file or symlink.

    Returns
    -------
    int
        Number of agents left out because an entry already exists.
    """
    extension = PROVIDERS[provider_name].extension
    kept = 0
    for agent in load_agents():
        path = target / f"{agent.name}{extension}"
        content = render(agent, provider_name, models)
        tier = AGENT_TIERS[agent.name]
        # A symlink counts as an existing entry even when it dangles, and is
        # never "up to date": its content belongs to another location.
        is_link = path.is_symlink()
        present = is_link or path.exists()
        if (
            present
            and not is_link
            and path.is_file()
            and path.read_text(encoding="utf-8") == content
        ):
            action = "up to date"
        elif present and not force:
            what = "is a symlink" if is_link else "differs"
            action = f"kept, {what} (use --force to replace)"
            kept += 1
        else:
            action = "written" if apply else "would write"
            if apply:
                target.mkdir(parents=True, exist_ok=True)
                write_entry(path, content, replace=present)
        print(f"{agent.name:<9}{tier:<7}{models[tier]:<20}{path}: {action}")
    return kept


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for the options documented in the module docstring.
    """
    parser = argparse.ArgumentParser(
        description="Install or check the cheap-orchestration crew."
    )
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument(
        "--scope",
        choices=("user", "project"),
        default="user",
        help="home directory (default) or current project",
    )
    parser.add_argument("--dest", type=Path, help="explicit target directory")
    parser.add_argument("--apply", action="store_true", help="write the files")
    parser.add_argument(
        "--force", action="store_true", help="replace files that differ"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing, exit 1 if an agent is missing or not pinned as expected",
    )
    for tier in ("small", "medium", "large"):
        parser.add_argument(
            f"--{tier}", metavar="MODEL", help=f"model identifier for the {tier} tier"
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run the command line.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name, ``sys.argv[1:]`` when None.

    Returns
    -------
    int
        0 on success, 1 when ``--check`` finds a missing or wrongly pinned
        agent, or when an existing entry was kept.
    """
    args = build_parser().parse_args(argv)
    target = destination(args.provider, args.scope, args.dest)

    models = dict(PROVIDERS[args.provider].models)
    for tier in models:
        override = getattr(args, tier)
        if override:
            models[tier] = override

    if args.check:
        problems = crew_problems(args.provider, target, models)
        if problems:
            print(f"crew not ready in {target}:")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(f"crew complete and pinned in {target}")
        return 0

    kept = install(args.provider, target, models, args.apply, args.force)
    if not args.apply:
        print("dry run: nothing written, add --apply to install")
    if args.provider == "gemini":
        print(
            "gemini: subagents are experimental, set "
            '"experimental": {"enableAgents": true} in settings.json'
        )
    print(f"rules to add to your instruction file: {RULES_FILE}")
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
