#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
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

Nothing is written without ``--apply``, and an existing file is never
replaced without ``--force``.

Usage
-----
    uv run setup_crew.py --provider claude              # dry run, user scope
    uv run setup_crew.py --provider codex --apply       # install
    uv run setup_crew.py --provider claude --check      # exit 1 if an agent is missing
"""

from __future__ import annotations

import argparse
import json
import sys
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
    """

    config_dir: str
    extension: str
    models: dict[str, str]
    labels: dict[str, str]


PROVIDERS = {
    "claude": Provider(
        config_dir=".claude",
        extension=".md",
        models={"small": "haiku", "medium": "sonnet", "large": "opus"},
        labels={"small": "Haiku", "medium": "Sonnet", "large": "Opus"},
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


def describe(agent: Agent, provider_name: str) -> str:
    """
    Return the agent description with the right model name in front.

    The bundled descriptions start with the Claude model name ("Haiku
    read-only code scout"). On another provider that word is replaced with
    the model of the same tier, so the description never names a model the
    agent does not run on.

    Parameters
    ----------
    agent : Agent
        The bundled definition.
    provider_name : str
        Key of ``PROVIDERS``.

    Returns
    -------
    str
        The description for that provider.
    """
    tier = AGENT_TIERS[agent.name]
    claude_label = PROVIDERS["claude"].labels[tier]
    label = PROVIDERS[provider_name].labels[tier]
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
    description = describe(agent, provider_name)
    body = agent.body.rstrip("\n") + "\n"

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
        The target directory. It may not exist yet.
    """
    if dest is not None:
        return dest
    root = Path.home() if scope == "user" else Path.cwd()
    return root / PROVIDERS[provider_name].config_dir / "agents"


def missing_agents(provider_name: str, target: Path) -> list[str]:
    """
    List the crew agents that have no definition in a directory.

    Parameters
    ----------
    provider_name : str
        Key of ``PROVIDERS``.
    target : Path
        Directory to look in.

    Returns
    -------
    list[str]
        Names of the missing agents, empty when the crew is complete.
    """
    extension = PROVIDERS[provider_name].extension
    return [n for n in AGENT_TIERS if not (target / f"{n}{extension}").is_file()]


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
        Replace a file that already exists and differs.

    Returns
    -------
    int
        Number of agents left out because an existing file differs.
    """
    extension = PROVIDERS[provider_name].extension
    kept = 0
    for agent in load_agents():
        path = target / f"{agent.name}{extension}"
        content = render(agent, provider_name, models)
        tier = AGENT_TIERS[agent.name]
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            action = "up to date"
        elif path.exists() and not force:
            action = "kept, differs (use --force to replace)"
            kept += 1
        else:
            action = "written" if apply else "would write"
            if apply:
                target.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
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
        help="write nothing, exit 1 if a crew agent is missing",
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
        0 on success, 1 when ``--check`` finds a missing agent or when an
        existing file was kept because it differs.
    """
    args = build_parser().parse_args(argv)
    target = destination(args.provider, args.scope, args.dest)

    if args.check:
        missing = missing_agents(args.provider, target)
        if missing:
            print(f"missing in {target}: {', '.join(missing)}")
            return 1
        print(f"crew complete in {target}")
        return 0

    models = dict(PROVIDERS[args.provider].models)
    for tier in models:
        override = getattr(args, tier)
        if override:
            models[tier] = override

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
