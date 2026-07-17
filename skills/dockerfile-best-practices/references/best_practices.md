# Dockerfile Best Practices Checklist

## Version Pinning Philosophy

### A tag is documentation, not a mechanism

Most pinning advice, including earlier versions of this skill, argues about tag
strings as if the string itself did something. It does not. Two properties get
attributed to tags that tags do not have:

- **"This tag receives security patches."** No tag patches anything. A floating
  tag such as `python:3.12-slim` only changes what you run when *someone
  rebuilds the image*. If you build once and deploy that image for a year, a
  floating tag leaves you exactly as unpatched as a frozen one. The patch came
  from the rebuild, not from the tag.
- **"This tag makes the build reproducible."** No tag guarantees bytes. Every
  tag is mutable: the registry lets the publisher move it whenever they like.
  `python:3.12-slim` today and `python:3.12-slim` in six months are two
  different images with the same name.

Both properties belong to a **process**, not to a string. Once that is clear,
the old "pin the runtime but never the OS" rule collapses: it was a floating tag
sold as a patching mechanism. So decide the tag on readability and stability,
then get patching and reproducibility from the process that rebuilds your
images.

### The rules

1. **Pin a readable tag, as specific as you are willing to maintain.**
   `python:3.12-slim` is fine. `python:3.12-slim-bookworm` is equally fine. The
   question is not which is "correct" but which one you will actually keep up to
   date.
1. **OS-pinned tags are legitimate.** `-bookworm`, `alpine3.19`, and friends are
   a valid stability choice: they trade silent OS rollover for a bump you
   perform deliberately. Nothing in this skill flags them.
1. **`:latest` and untagged images are rejected.** Not because mutability is
   uniquely evil there, but because they carry zero information about what you
   are running. `python:3.12-slim` at least tells a reader the major.minor and
   the variant. `:latest` tells them nothing at all. This is `DL002` (error) and
   `DL003` (warning).
1. **Be honest that every tag is mutable.** A tag is a rough contract and a note
   to the next reader. Treat it as documentation, and do not imply to your team
   that it froze anything.
1. **Security updates come from rebuilding regularly.** Name the process, not
   the string: a scheduled rebuild, a Renovate or Dependabot PR, a CI job on a
   timer. An image built eighteen months ago from a floating tag is an image
   full of known CVEs, regardless of how carefully the tag was chosen.
1. **Reproducibility, when you need it, comes from a process too**: digest
   pinning backed by renewal automation, or recording the resolved digest in
   build metadata. Provenance attestations already do the latter for you, so
   see `references/supply_chain.md` rather than reinventing it here.

### What each reference form actually gives you

| Reference form | What it tells a reader | What it freezes | Patches arrive |
| --- | --- | --- | --- |
| `python:3.12-slim` | major.minor and variant | nothing | on rebuild |
| `python:3.12-slim-bookworm` | the above, plus the OS release | nothing | on rebuild, until you bump the OS yourself |
| `python:latest` | nothing | nothing | on rebuild (rejected: `DL002`) |
| `python` (untagged) | nothing, and it means `:latest` | nothing | on rebuild (rejected: `DL003`) |
| tag + `@sha256:...` | the tag's intent, plus exact bytes | the image | only when automation moves the digest |

Note the column that is empty for every tag form. That is the whole point.

### Digests: an option, with an honest tradeoff

A digest is the strongest guarantee available. It names exact bytes, and it is
the only form in the table that actually freezes an image:

```dockerfile
# Fragment: illustrates the digest form; <digest> is a placeholder, not a real image
FROM python:3.12-slim@sha256:<digest>
```

Keep the tag in front of the digest. The digest does the pinning; the tag is
there so a human can tell what they are looking at.

The tradeoff is real and it is the reason this is not the default
recommendation: **a digest without renewal automation is just a tag that rots
silently.** A floating tag that goes stale at least picks up patches the next
time someone rebuilds. A pinned digest cannot: it will hand you the same
vulnerable bytes forever, with a reassuring air of rigour, while CVEs pile up
against the image you froze. That failure is worse than the problem it solves,
because it feels like control.

So pin digests only if you also run the automation that renews them (Renovate
and Dependabot both update digests in `FROM` lines). Most teams do not have that
automation. If you are one of them, a readable tag plus a scheduled rebuild is
the more honest choice, and this skill will not tell you otherwise.

## User Creation: UID/GID Strategy

### Default Approach (Simple)

Let the system auto-assign UID/GID:

```dockerfile
# Debian/Ubuntu
RUN groupadd -r app && useradd -r -g app app

# Alpine
RUN addgroup -S app && adduser -S -G app app
```

### Explicit UID/GID (Consistency)

When you need consistent permissions across environments:

```dockerfile
# Debian/Ubuntu - Use UID/GID >10000
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app

# Alpine
RUN addgroup -g 10001 app && \
    adduser -u 10001 -G app -S app
```

### Why >10000?

- Avoids conflicts with system users (typically <1000)
- Avoids conflicts with regular host users (typically 1000-9999)
- Safe range for containerized applications
- Kubernetes and orchestrators often enforce similar ranges

### When to Use Explicit UID/GID

- Volume mounts need specific file ownership
- Multi-container setups requiring shared file access
- Security policies mandate specific UID ranges
- Kubernetes SecurityContext with `runAsUser`
- NFS or shared storage with strict permission requirements

### Complete Pattern

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Create non-root user with explicit UID/GID
RUN groupadd -r -g 10001 app && \
    useradd -r -u 10001 -g app app

WORKDIR /app
RUN chown app:app /app

USER app

CMD ["python", "-m", "myapp"]
```

Order matters here: the `RUN` that creates `app` comes before anything that
refers to `app` by name, because names are resolved against this stage's own
`/etc/passwd`. Install dependencies as root, settle ownership of the workdir,
and put `USER app` last.

## Essential Rules

### 1. Use `COPY` for local files, and `ADD` for what only `ADD` can do

The blanket rule "always use `COPY`, never use `ADD`" was written when `ADD` had
no way to verify what it fetched. That is no longer true, and the blanket rule
now pushes people toward something worse.

**`COPY` for anything already in your build context.** It is the explicit
instruction and it does exactly one thing:

```dockerfile
COPY ./mydir /app/mydir
```

**`ADD --checksum` for a remote artifact.** This is strictly better than
`RUN curl | tar`, which this skill's own `DL017` flags: it is verified, it needs
no `curl` in the image, and it is one cacheable instruction instead of a shell
pipeline:

```dockerfile
ADD --checksum=sha256:<hash> https://example.com/tool-1.2.3.tar.gz /opt/
```

Without `--checksum`, nothing verifies the payload and you are trusting the
network. `DL006` warns on exactly that case, and stays silent when the checksum
is present.

**`ADD` for a Git repository.** BuildKit performs the clone, so no `git` binary
ends up in the image, and the `#<ref>` fragment pins what you get. The `.git`
directory is excluded by default; add `--keep-git-dir=true` only if you actually
need it:

```dockerfile
ADD https://github.com/example/repo.git#v1.2.3 /src/
```

For Git sources `--checksum` takes a commit SHA (full, or a unique prefix)
rather than a `sha256:` digest.

**Never `ADD` a local archive you did not build yourself.** This is the one real
trap left, and it is worth naming: a local `.tar.gz` is auto-extracted into your
image, which is easy to miss when reading the Dockerfile and unpleasant when the
archive contains paths you did not expect.

One correction to the folklore, because it is the usual reason people fear
`ADD`: **auto-extraction only applies to local archives.** A remote URL is
downloaded, not unpacked. If you want a remote archive extracted, you now have
to ask for it with `--unpack=true`, and you can suppress local extraction with
`--unpack=false`.

### 2. Watch layer content, not layer count

**The pre-BuildKit reflex was "each `RUN`, `COPY`, or `ADD` creates a layer, so
chain everything together to avoid bloat".** Layer count is close to irrelevant
now, and optimising for it produces unreadable Dockerfiles for no measurable
gain.

What actually matters is **layer content**, for exactly one reason:

> Anything written in a layer stays in the image, even if a later layer deletes
> it. A deletion in a later layer only adds a whiteout marker on top; the bytes
> are still there, still downloaded, still in your image.

So the real rule is about *when* you clean up, not about *how many* `RUN` lines
you have. Cleanup must happen in the **same instruction** that created the
files:

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/*
```

This is one `RUN` because the `rm` has to be in the same instruction as the
`apt-get update` that created the lists, not because three lines are somehow
better than four. Splitting it up would leave the package lists in the first
layer forever:

```dockerfile
# Anti-pattern: the rm is in a later layer, so the lists stay in the image
FROM debian:stable-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl
RUN rm -rf /var/lib/apt/lists/*
```

Corollary, stated plainly: **chaining fifteen unrelated commands into one
unreadable `RUN` for the sake of layer count is cargo cult.** If a command
creates nothing that needs cleaning up, it can have its own `RUN` and cost you
nothing that matters. Split on readability; group on cleanup.

#### Cleanup and cache mounts are alternatives, not a stack

This skill teaches both patterns, so it owes you the relationship between them.
Take the two flags separately, because they do different jobs:

- **`rm -rf /var/lib/apt/lists/*` is the cleanup you need when you are *not*
  using a cache mount.** With a cache mount on `/var/lib/apt`, that directory is
  a mount, not part of the layer: nothing written there ever enters the image,
  so the `rm` is redundant. Worse, it is counterproductive, because it deletes
  the cache you mounted the directory to keep. Use one or the other:

  ```dockerfile
  # Without a cache mount: clean up in the same instruction
  RUN apt-get update && \
      apt-get install -y --no-install-recommends curl && \
      rm -rf /var/lib/apt/lists/*
  ```

  ```dockerfile
  # With cache mounts: no rm, the mounted dirs are not part of the layer
  RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
      --mount=type=cache,target=/var/lib/apt,sharing=locked \
      apt-get update && apt-get install -y --no-install-recommends curl
  ```

- **`--no-install-recommends` is correct in both cases.** It is not part of the
  above trade at all, and it is worth being precise about why: it controls what
  gets *installed* into `/usr`, which is always part of the layer. Cache mounts
  only change where the downloaded `.deb` files live. Recommended packages you
  did not ask for end up in the image either way, so keep this flag always.

`DL007` encodes the first bullet (it accepts either the cleanup or a cache
mount), and `DL019` encodes the second (it asks for `--no-install-recommends`
regardless).

### 3. Use multi-stage builds

**Why:**

- Keeps build tools out of the final image
- Reduces size and attack surface
- Separates build and runtime concerns

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1-alpine AS builder
WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/root/.cache/go-build \
    go build -o /out/app ./cmd/app

FROM debian:stable-slim
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app app
COPY --from=builder --link /out/app /usr/local/bin/app
USER app
ENTRYPOINT ["/usr/local/bin/app"]
```

### 4. Handle secrets securely with BuildKit

**Critical:** Never pass secrets via `ARG` or `ENV`. Both are recorded in the
image history, and `ARG` values also show up in `max` mode provenance
attestations.

```dockerfile
# syntax=docker/dockerfile:1

RUN --mount=type=secret,id=api_key \
    curl -H "Authorization: Bearer $(cat /run/secrets/api_key)" https://api.example.com
```

### 5. Reuse cache with `--mount=type=cache`

**Why:** Speeds up builds by caching install/download steps. The cache is not
part of the image, so it costs nothing at runtime.

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

### 5a. Configure APT for cache mounts (Debian-based images)

**Critical step:** Debian images ship a config that deletes downloaded packages
automatically, which defeats a cache mount. Turn it off first:

```dockerfile
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
```

Then use cache mounts, as shown in rule 2 above. `DL033` fires when a cache
mount is used without this configuration.

### 6. Always use a `.dockerignore`

**Why:**

- Reduces build context size
- Prevents copying secrets or junk files

```dockerignore
.git
node_modules
.env
*.log
dist/
```

### 7. Use heredocs for multi-line scripts

Now that layer count is not something to optimise (rule 2), the main reason to
write a `&&`-chained wall of backslashes is gone. Heredocs are the readable way
to express a multi-line script, and they keep it in one instruction, which is
what actually matters for cleanup:

```dockerfile
RUN <<EOF
set -eux
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
rm -rf /var/lib/apt/lists/*
EOF
```

Note `set -eux` on the first line. Without it the heredoc runs under `sh`
defaults, where a failing command in the middle does **not** fail the build,
which is a genuinely dangerous difference from the `&&` chain it replaces. The
`&&` form gets this for free; the heredoc form does not.

Heredocs also write files inline, which beats a pile of `echo` redirects:

```dockerfile
COPY <<EOF /etc/myapp/config.toml
[server]
port = 8080
EOF
```

## Modern Instruction Features

Useful things BuildKit added that Dockerfiles in the wild rarely use. All of
these need `# syntax=docker/dockerfile:1` at the top, which resolves to the
latest 1.x release, so you get them automatically.

### `COPY --link`

What it actually buys you: the copied files land on their **own layer**, linked
on top of the previous state instead of merged into it. That layer stays valid
when the layers underneath it change, so it survives a base image update. For
multi-stage builds this is the difference between rebasing onto a patched base
image and rebuilding the whole thing. BuildKit can often perform that rebase by
writing a new manifest, without pulling or pushing the layers at all.

```dockerfile
COPY --from=builder --link /out/app /usr/local/bin/app
```

It is **not** a security feature. Any claim that `--link` is "more secure" is
noise: it changes layer topology and cache behaviour, nothing else.

When *not* to use it, because it does have traps. With `--link`, the copy cannot
read the previous state, and that has consequences:

- **Symlinks in the destination path are not followed.** If an earlier
  instruction made `/app` a symlink to `/opt/app`, a non-`--link` copy follows
  it; `--link` does not, and you get a real directory at `/app` instead. The
  destination path created by `--link` is always plain directories.
- **Copying a directory overrides its mode** with the mode of the copied path.
  If you rely on a specific mode on the destination (`/tmp` and its permissive
  bits are the classic case), either skip `--link`, copy the contents rather
  than the directory, or set the mode explicitly with `--chmod`.

Outside those two cases the docs are unambiguous that `--link` is the better
default: equal or better performance, and much better cache reuse.

### `COPY --parents` and `COPY --exclude`

`--parents` keeps the source's parent directories instead of flattening
everything into the destination:

```dockerfile
COPY --parents ./src/**/*.py /app/
```

`--exclude` filters a copy without touching `.dockerignore`, and can be repeated:

```dockerfile
COPY --exclude=*.md --exclude=tests ./src /app/src
```

Per the Dockerfile reference these need syntax `1.20` and `1.19` respectively.
Both are stable flags on the `docker/dockerfile:1` line, not labs-only.

### `RUN --network=none`

Runs one instruction with no network access. This is how you make a build step
hermetic and prove it: if a test or a build secretly reaches out to the network,
it fails here instead of silently working on your machine and breaking in CI.

```dockerfile
RUN --network=none pip install --no-index --find-links /wheels myapp
```

### `RUN --mount=type=bind`

Binds a path into the build container for the duration of one `RUN`, read-only
by default, **without copying it into a layer**. This skill's own uv template
uses it, so it is worth stating outright: use it for files you need *during* a
step but not *in* the image, such as a lockfile you only read.

```dockerfile
RUN --mount=type=bind,source=go.sum,target=go.sum \
    --mount=type=bind,source=go.mod,target=go.mod \
    --mount=type=cache,target=/go/pkg/mod \
    go mod download
```

`from=<stage>` binds from another stage or image instead of the build context.
Writes to the mount are discarded, so it is not a way to produce artifacts.

### `ARG` with defaults

`ARG` takes a default, which makes a Dockerfile that documents its own knobs and
still builds with a bare `docker build`:

```dockerfile
ARG APP_PORT=8080
```

`ARG` values are not in the final image, but they **are** visible in
`docker history` and in `max` mode provenance attestations. They are build
configuration, never secrets. Use `--mount=type=secret` for those (rule 4).

### `ONBUILD`

Registers instructions that fire in the *child* build, when someone uses your
image as a base. It is a base-image authoring tool, and mostly a footgun
elsewhere, because the triggers run invisibly from the child's point of view.
If you do use it, note that `ONBUILD ONBUILD` is not allowed and it cannot
trigger `FROM`.

```dockerfile
ONBUILD COPY . /app
```

## Process Signals and PID 1

Your container's main process is PID 1, and PID 1 is special in ways that
quietly break shutdown. This is the depth behind the short note in `SKILL.md`.

### Why PID 1 is different

The kernel gives PID 1 **no default signal handlers.** For every other process,
signals like `SIGTERM` have a kernel default action of "terminate". For PID 1
that default does not exist: a signal with no explicit handler installed is
simply discarded.

The consequence is a shutdown path that looks fine and is not:

1. `docker stop` sends `SIGTERM` to PID 1.
1. Your app never installed a `SIGTERM` handler, so the kernel drops it.
   Nothing happens.
1. Docker waits out the full grace period, ten seconds by default.
1. Docker sends `SIGKILL`. The app dies instantly, mid-request, with no cleanup,
   no connection draining, no flushed buffers.

Every stop takes ten seconds, and every stop is a hard kill. **Kubernetes
behaves identically** during pod termination: `SIGTERM`, wait
`terminationGracePeriodSeconds`, then `SIGKILL`. If your rolling deploys feel
slow and drop connections, this is a prime suspect.

The second PID 1 duty is **reaping**. When a process exits, its parent must
`wait()` on it to clear the entry from the process table. Orphans get reparented
to PID 1, so PID 1 must reap them. A normal init does this; your web server
probably does not. If your app spawns subprocesses that outlive their parent,
zombies accumulate until the process table fills.

### Fixes, in order of preference

1. **Handle `SIGTERM` in the application.** The real fix. Your app knows what a
   graceful shutdown means: stop accepting connections, finish in-flight
   requests, flush, exit. Nothing else can do this for you, and if the app
   handles its own signals it does not need any of the options below. Most
   frameworks have this built in or one library away.
1. **`docker run --init`.** When you cannot change the app. Docker ships a small
   init (tini) and puts it at PID 1; it forwards signals to your process, which
   then receives them under normal kernel defaults, and it reaps orphans.
   Compose exposes the same thing:

   ```yaml
   services:
     app:
       init: true
   ```

1. **Bake tini into the image** when it must work regardless of how the
   container is run, `--init` included or not:

   ```dockerfile
   ENTRYPOINT ["/sbin/tini", "--"]
   CMD ["node", "server.js"]
   ```

1. **dumb-init** is an equivalent alternative, common in Python images. It
   forwards signals and reaps; pick either one, not both.

Note that options 2 through 4 fix *delivery*: they get `SIGTERM` to your
process. If your process still ignores it, the container still takes the full
grace period and still gets `SIGKILL`ed. They cannot substitute for option 1.

### Use exec form, always

None of the above helps if you wrote the shell form:

```dockerfile
# Anti-pattern: /bin/sh -c becomes PID 1 and does not forward signals
FROM node:22-alpine
CMD node server.js
```

Shell form wraps the command in `/bin/sh -c`, so the **shell** is PID 1. It does
not forward signals to its child, so your app never hears `SIGTERM` even though
it handles it correctly. Exec form makes your application PID 1:

```dockerfile
CMD ["node", "server.js"]
```

This is why `DL025` is a **warning** as of v3.0.0, raised from `info`: it is not
a style preference, it is the difference between a clean stop and a ten-second
hang plus a `SIGKILL`.

### `STOPSIGNAL`

`STOPSIGNAL` changes which signal Docker sends on `docker stop`. The default is
`SIGTERM`, which is what you want almost always. Change it only when your
program has its own convention and you cannot change the program: nginx, for
instance, treats `SIGQUIT` as graceful shutdown and `SIGTERM` as a fast one.

```dockerfile
STOPSIGNAL SIGQUIT
```

It accepts a name (`SIGQUIT`) or a number. It affects `docker stop` and the
daemon, not Ctrl+C, which sends `SIGINT` straight to the process regardless.

## Security Best Practices

### Set USER to non-root

```dockerfile
RUN addgroup --system app && adduser --system --ingroup app appuser
USER appuser
```

### Use HEALTHCHECK where it is actually read

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s \
  CMD ["curl", "-f", "http://localhost/"]
```

Use a binary the image actually ships, and make the check fail on a non-2xx
response rather than only on a refused connection. See `SKILL.md` for the
details, including the fact that Kubernetes ignores `HEALTHCHECK` entirely and
uses its own probes.

## Optimization Checklist

| Best Practice | Reason |
| --- | --- |
| Use `COPY` for local files | Explicit, does one thing |
| Use `ADD --checksum` for remote artifacts | Verified, and no `curl` in the image |
| Use `COPY --link` | Layers survive base image changes, so cache reuse across rebases |
| Implement multi-stage builds | Keeps build tools out of the final image |
| Use `--mount=type=cache` for caching | Speeds up install and download steps |
| Use `--mount=type=bind` for build-only files | Never enters a layer |
| Use `--mount=type=secret` for secrets | Keeps secrets out of history and provenance |
| Include a `.dockerignore` file | Keeps build context clean |
| Set `USER` to non-root | Runs containers more securely |
| Use exec form for `ENTRYPOINT`/`CMD` | The app becomes PID 1 and receives `SIGTERM` |
| Handle `SIGTERM`, or add an init | Clean shutdown instead of a `SIGKILL` after the grace period |
| Pin a readable tag, and rebuild on a schedule | The rebuild is what patches you; the tag just documents intent |
| Clean up in the same instruction that created the files | A later `rm` does not reclaim the bytes |
| Avoid installing unnecessary packages | Keeps images smaller and reduces attack surface |
| Prefer `COPY --chown=user:group` | Sets ownership without a second layer |

## Quick Wins by Impact

### High Impact (do these first)

1. Use multi-stage builds
1. Add `.dockerignore`
1. Use `--mount=type=cache` for dependencies
1. Use exec form so your app receives `SIGTERM`
1. Rebuild on a schedule (this, not the tag, is what patches you)

### Medium Impact

1. Use slim/alpine base images
1. Order instructions for cache efficiency
1. Clean up in the same instruction that created the files
1. Use heredocs instead of `&&` walls for multi-line scripts
1. Use `COPY --link`

### Low Impact (polish)

1. Add `HEALTHCHECK` (if anything reads it)
1. Add labels and metadata
1. Use `COPY --parents` / `--exclude` to tidy up copies
