# BuildKit Build Checks

BuildKit ships a native Dockerfile linter. It is the first tool to run against
any Dockerfile, before this skill's own analyzer.

```bash
docker build --check .
```

It runs the full build plan without executing any build step, and reports rule
violations against the resolved Dockerfile. Because it runs inside BuildKit, it
sees what the builder sees: resolved build arguments, stage graph, base image
metadata, and the `.dockerignore` context. No static parser can match that.

## Requirements

- Buildx **0.15.0+**
- Dockerfile syntax **1.8+**
- Docker Desktop **4.33+**

## Making checks blocking

`docker build --check` reports. A normal `docker build` only warns. To make
violations fail the build for everyone who builds the image, declare it in the
Dockerfile itself:

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true
```

The directive travels with the file, so it applies in CI, on a laptop, and in
any downstream build, without anyone remembering to pass a flag. Individual
rules can be skipped with `# check=skip=<RuleName>,<RuleName>`, and the two
forms combine on one line: `# check=skip=JSONArgsRecommended;error=true`.

## The rules

Twenty-one rules, as of the current BuildKit release. `InvalidDefinitionDescription`
is **experimental** and is not enabled by default; the other twenty are on by
default.

| Rule | What it flags |
| :--- | :--- |
| `StageNameCasing` | A multi-stage `AS <name>` that is not all lowercase, which reads like an instruction keyword. |
| `FromAsCasing` | The `AS` keyword written in a different case from the `FROM` keyword on the same line. |
| `NoEmptyContinuation` | A blank line after a `\` line continuation. Deprecated syntax; a future BuildKit will reject it. |
| `ConsistentInstructionCasing` | Instruction keywords mixing cases (`Run`, `copY`). Pick all-upper or all-lower and hold it. |
| `DuplicateStageName` | Two stages sharing a name, which the builder cannot resolve unambiguously. |
| `ReservedStageName` | A stage named `context` or `scratch`, both reserved by the builder. |
| `JSONArgsRecommended` | `CMD` or `ENTRYPOINT` in shell form, which puts a shell at PID 1 and swallows signals. |
| `MaintainerDeprecated` | The `MAINTAINER` instruction. Use the `org.opencontainers.image.authors` label instead. |
| `UndefinedArgInFrom` | A `FROM` interpolating a build argument that was never declared, including misspelled built-ins like `BUILDPLATFORM`. |
| `WorkdirRelativePath` | A relative `WORKDIR` with no absolute `WORKDIR` earlier in the stage, so the effective path depends on the base image and can move upstream without warning. |
| `UndefinedVar` | Use of a variable never declared by `ARG` or `ENV`, with typo detection (`$PAHT` against `$PATH`). Shell-form `RUN`/`CMD`/`ENTRYPOINT` are excluded, since the shell resolves those. |
| `MultipleInstructionsDisallowed` | More than one `CMD`, `ENTRYPOINT`, or `HEALTHCHECK` in a stage. Only the last survives; the others are silently dead. |
| `LegacyKeyValueFormat` | The space-separated `ENV key value` / `ARG key value` form. Use `key=value`. |
| `RedundantTargetPlatform` | `FROM --platform=$TARGETPLATFORM`, which is already the default. |
| `SecretsUsedInArgOrEnv` | An `ARG` or `ENV` whose key name suggests a secret. These persist in the image and its metadata. |
| `InvalidDefaultArgInFrom` | A global `ARG` used in `FROM` whose default value does not produce a valid image reference, so the build only works when the argument is passed. |
| `FromPlatformFlagConstDisallowed` | `FROM --platform=` with a hardcoded constant such as `linux/amd64`, which defeats multi-platform builds. Use `$BUILDPLATFORM`, or a per-arch stage selected by `$TARGETARCH`. |
| `CopyIgnoredFile` | A `COPY`/`ADD` source that `.dockerignore` excludes from the context, so the instruction cannot possibly find it. |
| `InvalidDefinitionDescription` | *(experimental)* A comment directly above a stage or `ARG` that does not follow the `# <arg/stage name> <description>` convention. |
| `ExposeProtoCasing` | A protocol in `EXPOSE` that is not lowercase (`80/TcP`). |
| `ExposeInvalidFormat` | An `EXPOSE` carrying an IP address or a host-port mapping. That is a `docker run -p` concern. Docker has stated this will become an error in a future release. |

Reference: <https://docs.docker.com/reference/build-checks/>

## Overlap with this skill's analyzer

`docker build --check` is the primary linter. This skill's
`scripts/analyze_dockerfile.py` is a **complement**, not a replacement. It
exists for two reasons:

1. It runs with **no Docker daemon**: a plain Python script over a text file. It
   works in a CI job with no builder, in a review of a Dockerfile you have not
   checked out, and on a machine where Docker is not installed.
1. It covers ground BuildKit does not touch at all: cache mounts, UID/GID
   ranges, apt cache configuration, non-root user presence, healthcheck and
   label presence, and the tag doctrine.

Only three rules genuinely overlap. Keep both: the DL versions are the
daemon-free path.

| BuildKit rule | DL rule | Relationship |
| :--- | :--- | :--- |
| `SecretsUsedInArgOrEnv` | DL020 (error) | Overlaps in part. Both flag secret-looking `ARG`/`ENV` keys by name heuristic. Neither can detect a secret hiding behind an innocuous key name, so a clean report from either is not proof. |
| `JSONArgsRecommended` | DL025 (warning) | Same defect, same reasoning: shell form puts `/bin/sh -c` at PID 1, signals are not forwarded, and `docker stop` waits out the full timeout before `SIGKILL`. |
| `WorkdirRelativePath` | DL024 (warning) | Same intent. BuildKit's version is more precise: it only fires when no absolute `WORKDIR` precedes the relative one in the stage. |

Everything else is disjoint. BuildKit owns the casing, stage-graph, variable, and
platform rules (`StageNameCasing`, `FromAsCasing`, `ConsistentInstructionCasing`,
`DuplicateStageName`, `ReservedStageName`, `MaintainerDeprecated`,
`UndefinedArgInFrom`, `UndefinedVar`, `MultipleInstructionsDisallowed`,
`LegacyKeyValueFormat`, `RedundantTargetPlatform`, `InvalidDefaultArgInFrom`,
`FromPlatformFlagConstDisallowed`, `CopyIgnoredFile`, `NoEmptyContinuation`,
`InvalidDefinitionDescription`, `ExposeProtoCasing`, `ExposeInvalidFormat`). It
has no counterpart for DL001, DL002, DL003, DL006, DL007 through DL019, DL021,
DL022, DL023, DL030, DL031, DL032, DL033, or DL034.

`CopyIgnoredFile` is worth calling out as a rule the skill's analyzer structurally
cannot implement: it requires reading `.dockerignore` and resolving it against
the real build context.

### Analyzer changes in v3.0.0 that affect this table

- **DL004 and DL005 are RETIRED.** They enforced the reversed pinning doctrine.
  Their IDs stay burned. OS-pinned tags are no longer flagged anywhere.
- **DL006 is rewritten.** It now flags `ADD <url>` *without* `--checksum` as a
  warning, and no longer flags `ADD --checksum` at all.
- **DL025 is raised** from info to warning, with the signal-handling reason in
  the message. This puts it at the same weight BuildKit gives
  `JSONArgsRecommended`.
- **DL003 no longer false-positives on stage aliases.** A bare
  `FROM builder` referencing an earlier `FROM ... AS builder` is the standard
  multi-stage pattern, not an untagged base image.
- **DL021 no longer false-positives on `nonroot`.** It matched `root` as a
  substring, so `USER nonroot` (the account in `gcr.io/distroless/*:nonroot`)
  was reported as running as root, and the same file also drew DL030 for having
  no non-root user. `USER 0` was missed entirely. Both are fixed.

Run both, in this order:

```bash
docker build --check .
uv run skills/dockerfile-best-practices/scripts/analyze_dockerfile.py Dockerfile
```

## hadolint

hadolint is the third option, and it covers one thing neither of the other two
does: it **embeds ShellCheck**. Neither BuildKit nor this skill's analyzer lints
the shell code inside a `RUN`. hadolint does, and shell inside `RUN` is where a
real share of Dockerfile bugs live: unquoted expansions, a pipeline whose failure
is swallowed because only the last command's exit status counts, `cd` that
silently does not happen.

It is also daemon-free and packaged as a container, so it drops into CI with no
builder. Its own Dockerfile rules overlap heavily with both tools above and it
carries the same historical pinning opinions this skill has now abandoned (see
the DL004/DL005 retirement above), so treat its Dockerfile findings as advisory
and configure them to taste. The ShellCheck half is the part worth adding.
