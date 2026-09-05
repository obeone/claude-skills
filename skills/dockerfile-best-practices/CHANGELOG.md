# Changelog

All notable changes to the `dockerfile-best-practices` skill are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The skill is versioned with [Semantic Versioning](https://semver.org/spec/v2.0.0.html), tracking `metadata.version` in `SKILL.md`.

## [3.2.0] - 2026-08-14

`SKILL.md` is loaded into the agent's context for an entire session, and the
front-matter description is loaded permanently whether or not the skill ever
triggers. Both were paying for content that only a fraction of sessions needs.
This release is a relocation, not a deletion: nothing is lost, and the six
templates are still extracted and linted in CI from their new home.

### Changed

- **The six language templates moved to `references/templates.md`.** `SKILL.md`
  keeps an index naming what each one demonstrates, so the right template is
  one targeted read away instead of 184 lines resident in every session. The
  extractor already walked `references/*.md`, so CI coverage is unchanged and
  all six blocks still validate.
- **Front-matter description trimmed** from 349 to 232 characters, keeping
  every routing trigger (Dockerfile, Compose, container images, build
  performance, Docker security).
- **`SKILL.md` is now 250 lines, down from 415** (18.6 KB to 13.8 KB).

### Fixed

- **`README.md` restyled** to the layout the other skills in this repo use,
  and its install section no longer ships a `curl` plus `unzip` of a release
  asset, which the skills.sh Snyk audit flags as an unverified download in
  skill instructions.

## [3.1.0] - 2026-07-18

The Compose reference covered writing a Compose file but not linting one. It
now documents DCLint, the established third-party Compose linter, states
honestly which of its 15 rules overlap with this skill's own
`analyze_compose.py` (two do), and which are ordering/formatting opinions
safe to turn off (eight are). `docker compose config --quiet` is documented as
the zero-install schema/interpolation check that should run before either
linter.

### Added

- **`## Linting` section in `references/compose_best_practices.md`.** Install
  and run lines for DCLint via `npx` and the `zavoloklom/dclint` Docker image,
  its `--fix` mode, and an overlap table against this skill's own analyzer
  rules (DC002, DC012, DC013). Also documents `docker compose config --quiet`
  as the pre-linter validation step.
- **`SKILL.md`'s Commands Reference** now lists `docker compose config
  --quiet`, a `dclint` invocation, and a hadolint invocation (`docker run
  --rm -i hadolint/hadolint < Dockerfile`) alongside the existing analyzer and
  `docker buildx build --check` commands.
- **A Compose file naming rule in `SKILL.md`.** All four names Compose V2
  accepts work, so the skill no longer picks silently: match an existing file
  first, then a recorded preference, and otherwise ask the user once and
  record the answer. `compose.yaml` is recommended as the canonical form, not
  imposed.

### Changed

- **Canonical Compose file name is now `compose.yaml`, not
  `docker-compose.yml`.** Every place in `references/compose_best_practices.md`
  that names the file you are writing (`Development vs Production`, `Override
  Files`, the `!reset`/`!override` examples) now uses `compose.yaml` /
  `compose.override.yaml`. A short note states the actual Compose V2 lookup
  order (`compose.yaml`, `compose.yml`, `docker-compose.yaml`,
  `docker-compose.yml`) for readers coming from an older project.

## [3.0.0] - 2026-07-17

v2.0.0 had two problems: its doctrine was wrong, and its own examples did not follow it.

The first is doctrine. v2.0.0 told you to pin the runtime and never the OS, because a floating OS tag would supposedly deliver security patches. It does not. "Receives security patches" and "reproducible" are properties of a process, not of a tag string. A tag patches nothing by itself: it patches when someone rebuilds. v2.0.0 rejected `:latest` as an error for being mutable, then recommended `debian:stable-slim` two sections later, which is mutable too. The skill now holds one position rather than arguing both sides of its own question.

The second is that the skill's own examples did not obey the skill. Four of the six language templates shipped a bug that silently produces root-owned files. A healthcheck called a binary its base image does not ship. Several examples could never have worked at all. Running the v2.0.0 analyzer over the v2.0.0 Python template, the one carrying both critical bugs, reported zero errors and zero warnings. That is why they shipped.

Digests are not the answer to any of this, and v3.0.0 does not make them the default. A digest without renewal automation is a tag that rots quietly while you ship known CVEs feeling safe. Most teams do not have that automation. Digests get one honest paragraph as an option with a real tradeoff.

### Removed

- **DL004 (OS version pinning) and DL005 (Alpine minor pinning) are retired.** OS-pinned tags such as `python:3.12-slim-bookworm` and `alpine:3.19` are a legitimate stability choice and are no longer flagged anywhere. This is breaking for anyone whose CI asserted on those rule ids: they no longer fire, and the ids stay retired permanently rather than being reused for something else. Retiring them is what makes DL002 and DL003 coherent, since the analyzer previously rejected one mutable tag while recommending others.
- **The "What NOT to Pin" section is gone**, along with the security note that warned SHA256 pinning "can complicate dependency updates". It contradicted the same file's advice to pin digests.

### Changed

- **DL006 is inverted, and this is breaking.** It used to exempt `ADD <url>`, the one case that actually needs verification, and flag the harmless local uses. It now flags `ADD <url>` without `--checksum` as a warning, never flags `ADD --checksum`, and keeps flagging `ADD` used for local files that `COPY` should handle. A Dockerfile that passed DL006 under v2.0.0 may fail it now, and vice versa.
- **DL025 is raised from info to warning.** Shell-form `CMD`/`ENTRYPOINT` wraps the process in `/bin/sh -c`, which makes the shell PID 1 and does not forward `SIGTERM`, so the container ignores `docker stop` until the timeout kills it. The message now says so. Anyone failing CI on warnings will see this where they did not before.
- **`ADD` is no longer banned wholesale.** `COPY` for local files, `ADD --checksum` for remote artifacts, `ADD` for git refs, and never `ADD` a local archive you did not build yourself.
- **Layer guidance is rewritten around content instead of count.** Merging unrelated commands saves nothing under BuildKit and widens the cache blast radius. What matters is that bytes written in a layer survive a later delete, so cleanup belongs in the instruction that created the files. Chaining commands to shrink a number is cargo cult.
- **`container_name` is no longer forbidden in seven places for reasons given in two of them.** Stated once, with the actual cost: it blocks `--scale`. A single-instance service addressed by name is a legitimate design.
- **The base image table is now a decision** rather than a list, and covers Docker Hardened Images and Chainguard. The musl caveat is given honestly: the DNS folklore was fixed in musl 1.2.4, shipped in Alpine 3.18. What remains is musllinux wheel coverage.
- Distroless stages moved from the unversioned `gcr.io/distroless/static` and `.../cc` to `static-debian13:nonroot` and `cc-debian13:nonroot`. The unversioned aliases are deprecated upstream and roll forward silently on the next Debian release. The `:nonroot` variant also ships a non-root account, which matters because `groupadd` does not exist in a distroless image.
- `uv` is pinned at `0.11.29` throughout: five references floated on `:latest` and four more sat on a stale `0.9.10`. `composer` and `nginx` no longer float on `:latest` either.
- The Compose reference banned `:latest` and then reached for `myapp:latest` in its own override example. The override examples now carry a real version.

### Added

- **DL036: a `--chown` naming a user that the same stage creates later.** This is the rule that would have caught the worst bug in v2.0.0, and no other tool can. See the ordering fix under Fixed for why the build staying green is the problem rather than the consolation.
- **DL037: a registry reference in `COPY --from`.** DL002 only ever inspected `FROM`, so `COPY --from=ghcr.io/astral-sh/uv:latest` and `COPY --from=composer:latest` both sailed straight through the analyzer and both shipped. Errors on `:latest`, warns on an untagged reference, never flags a stage alias or index.
- **DL038: a `HEALTHCHECK` calling `curl` or `wget` that the stage never installs.** `curl` is flagged whenever it is absent, since it ships on neither the slim nor the alpine images tested. `wget` is flagged only when the base is confidently identified as non-alpine, because BusyBox provides it on the alpine family with no install step. When the base image is a bare variable or an unrecognised private registry reference, the rule declines rather than guesses.
- **`references/build_checks.md`.** BuildKit has shipped a native linter since Dockerfile syntax 1.8 and this skill never mentioned it, presenting its own analyzer as the primary tool. Documents `docker build --check`, its 21 rules, the `check=error=true` directive, where it overlaps the DL rules, and hadolint's place as the only one of the three that lints shell inside `RUN`.
- **`references/supply_chain.md`.** SBOM, provenance, reproducible builds and signing were absent entirely. Includes two traps worth knowing: attestations do not survive `--load`, and a secret passed via `--build-arg` is recorded in the provenance attestation at `mode=max`, which `docker/build-push-action` applies automatically to public repositories.
- **`scripts/extract_dockerfile_blocks.py` and a CI job that lints the skill's own examples.** Nothing previously checked that the skill obeyed itself. Only complete image definitions are gated: a block with no `FROM`, or a `FROM` with no `CMD` or `ENTRYPOINT`, is a teaching snippet, and whole-image rules like the syntax directive or the non-root user check are meaningless there. Gating them would force boilerplate onto every two-line example, which is the failure mode this release exists to remove.
- An allowlist variant of the `.dockerignore` template, commented out, for projects where build-context leakage matters. Two traps in the existing blocklist are now documented: excluding `.git` breaks `git describe` version stamping, and excluding `Dockerfile*` breaks multi-Dockerfile setups that `COPY` one in.
- Sections on PID 1 and signal handling, `STOPSIGNAL`, `RUN --mount=type=bind` (which the templates already used and nothing explained), and Compose runtime hardening (`read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`, `user`, `init`) explained line by line, plus `pull_policy`, `profiles`, `include`, `develop.watch` and `!reset`.
- CVE-2025-62725 is noted in the Compose reference: a path traversal reachable from read-only commands such as `docker compose config`, fixed in Compose 2.40.2.

### Fixed

- **Five templates named a user in `COPY --chown` before the `RUN` that creates it.** The audit called this a build failure. It is not, and the truth is worse. On the `dockerfile:1` frontend the build exits 0 and silently discards the `--chown`, so the files land owned by root and the application only breaks at the first runtime write, long after CI went green. A build that dies gets fixed in five minutes; this ships. Nothing in the pipeline can see it, not the build, not `docker build --check`, which is why DL036 had to be a static rule. Fixed in all five: four of the six language templates, plus the one in `uv_integration.md`, a file no audit had looked at.
- **Healthchecks called binaries their images do not ship.** `python:3.12-slim` has neither `curl` nor `wget`, so the old rule 10 example (`HEALTHCHECK CMD wget ...` on a slim base) could never have run. The probes now use a binary the image actually has.
- **One healthcheck used `requests.get()`, which does not raise on HTTP 500**, so it reported a failing service as healthy. It now uses stdlib `urlopen`, which does raise. The reference also states plainly that Kubernetes ignores Docker `HEALTHCHECK` entirely and uses its own probes.
- **The Python multi-arch example produced an image advertised as `linux/amd64` containing aarch64 binaries.** It used `FROM --platform=$BUILDPLATFORM`, which is an escape from QEMU for languages that cross-compile. Python has nothing to cross-compile, so the flag only lied about the architecture. The image built green and ran on the arm64 laptop that built it, then died on the first amd64 host to pull it. Measured rather than reasoned: `e_machine` was `0xb7` inside an amd64 manifest. The flag is gone and the section now gives the rationale it never had, with a Go block as the contrast where the pattern is correct.
- **The Rust example shipped a stub binary that did nothing.** The dummy-project trick fingerprints by mtime, and `COPY . .` restores the context's older mtime, so cargo skipped the rebuild and `cp` shipped the `fn main() {}` placeholder. Exit code 0 throughout.
- **A distroless Python example built on 3.12 and ran on 3.13.** `pip --user` wrote `.local/lib/python3.12`, which a 3.13 interpreter never reads, so the build was green and the container died at startup. Found by building it. `PYTHONPATH` is the variable that matters here, not `PATH`, and distroless sets no `HOME`.
- **The Java example was amd64-only and failed outright on Apple Silicon.** It built on `maven:3.9-eclipse-temurin-17-alpine` and ran on `eclipse-temurin:17-jre-alpine`. Both tags exist and both publish no arm64 manifest, because Eclipse Temurin ships no musl JDK for aarch64, so anyone on an arm64 laptop or runner got `no match for platform in manifest`. Now on the non-alpine tags, which resolve on both architectures. Measured, the swap costs about 75 MB uncompressed (175 MB for the alpine JRE against 250 MB for the jammy one), and the JVM dominates either way, so the "Alpine = minimal size" line the section used to carry was overselling a rounding error on an image that did not run. Alpine remains reachable through a vendor that publishes multi-arch musl JREs, which is a decision to make deliberately rather than by copying a tag out of an example.
- **The Compose example ran as UID 100.** `adduser --system` auto-assigns a low uid, which is the exact thing another section of the same skill flags as an anti-pattern.
- **DL003 false-positived on stage aliases.** A bare `FROM builder` referencing an earlier `FROM ... AS builder` was reported as an untagged base image, though a build stage has no registry tag to begin with. DL002 was checked for the same bug and does not have it.
- **DL021 matched `root` as a substring.** `USER nonroot`, the canonical account in `gcr.io/distroless/*:nonroot` images, was reported as running as root and simultaneously drew DL030 for having no non-root user. `USER 0` was missed entirely. The check now compares the exact name.
- The Node template is rebuilt on `npm ci --omit=dev`. `--frozen-lockfile` is Yarn v1 and `--production` is legacy.
- The `uv` CLI example ran `groupadd`/`useradd` on `python:3.12-alpine`, which ships BusyBox `addgroup`/`adduser` instead, so that block could never have built.
- A remote install script was downloaded and executed unverified. It now carries a checksum.
- A hardcoded `@sha256` digest advertised as "most reproducible" is removed. An unverifiable digest with no renewal automation is worse than a tag, because it cannot even pick up patches on rebuild.
- The environment-variables example in the Compose reference declared `services:` three times in one document and could not have parsed.
- Dropped the claim that Compose names containers `{project}_{service}_{replica}`. Compose V2 does not. The reference points at the labels instead.

## Earlier versions

No changelog was kept before 3.0.0. See the git history for changes up to and including 2.0.0.
